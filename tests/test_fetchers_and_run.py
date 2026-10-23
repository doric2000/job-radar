import json
import unittest
from datetime import datetime, timedelta, timezone

from radar.config import load_config
from radar.discover import candidates_from_html, slug_variants
from radar.http import HttpError
from radar.notify import format_alert
from radar.run import Radar
from radar.state import State
from radar.textutil import html_to_text, parse_relative_en

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeHttp:
    """Maps URL substrings to canned payloads. Raises HttpError for 'FAIL' payloads."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _find(self, url):
        self.calls.append(url)
        for k, v in self.routes.items():
            if k in url:
                if v == "FAIL":
                    raise HttpError("HTTP 500", 500)
                return v(url) if callable(v) else v
        raise HttpError("HTTP 404", 404)

    def get_json(self, url, method="GET", **kw):
        return self._find(url)

    def get_text(self, url, **kw):
        return self._find(url)


GH_LIST = {"jobs": [
    {"id": 1, "title": "Junior Backend Engineer", "updated_at": iso(NOW - timedelta(hours=1)), "absolute_url": "https://x/1", "location": {"name": "Tel Aviv, Israel"}},
    {"id": 2, "title": "Senior Backend Engineer", "updated_at": iso(NOW), "absolute_url": "https://x/2", "location": {"name": "Tel Aviv, Israel"}},
    {"id": 3, "title": "Security Engineer", "updated_at": iso(NOW), "absolute_url": "https://x/3", "location": {"name": "Tel Aviv, Israel"}},
    {"id": 4, "title": "Junior Software Engineer", "updated_at": iso(NOW), "absolute_url": "https://x/4", "location": {"name": "Haifa"}},
]}
GH_DETAIL = {
    "1": {"content": "&lt;p&gt;We build things.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;BSc in CS&lt;/li&gt;&lt;/ul&gt;", "first_published": iso(NOW - timedelta(hours=2)), "location": {"name": "Tel Aviv, Israel"}},
    "3": {"content": "&lt;ul&gt;&lt;li&gt;1+ years of experience in application security&lt;/li&gt;&lt;/ul&gt;", "first_published": iso(NOW - timedelta(days=60)), "location": {"name": "Tel Aviv, Israel"}},
    "4": {"content": "&lt;p&gt;Great team&lt;/p&gt;", "first_published": iso(NOW - timedelta(days=3)), "location": {"name": "Haifa"}},
}


def gh_route(url):
    if url.endswith("/jobs"):
        return GH_LIST
    return GH_DETAIL[url.rsplit("/", 1)[1]]


COMPANY = {"id": "acme", "name": "Acme", "ats": "greenhouse", "token": "acme", "tier": 1}


class TestRun(unittest.TestCase):
    def mk(self, http, state=None, companies=None, now=NOW):
        return Radar(load_config(None), companies or [COMPANY], state or State(), http, notifier=None, now=now, dry_run=True)

    def test_baseline_then_new(self):
        http = FakeHttp({"boards-api.greenhouse.io": gh_route})
        r = self.mk(http)
        s1 = r.run(0)
        titles = [a[0].title for a in s1["alerts"]]
        # baseline: only the fresh Junior role alerts; the 60-day-old and 3-day-old ones are silent
        self.assertEqual(titles, ["Junior Backend Engineer"])
        self.assertEqual(s1["alerts"][0][0].date_kind, "published")
        # second run, nothing changes -> nothing alerts, and no detail refetch for known jobs
        n_calls = len(http.calls)
        s2 = r.run(1)
        self.assertEqual(s2["alerts"], [])
        self.assertEqual(len(http.calls), n_calls + 1)  # only the list call
        # a new posting appears
        GH_LIST["jobs"].append({"id": 5, "title": "Software Engineer", "updated_at": iso(NOW), "absolute_url": "https://x/5", "location": {"name": "Tel Aviv, Israel"}})
        GH_DETAIL["5"] = {"content": "&lt;ul&gt;&lt;li&gt;2 years of experience in Go&lt;/li&gt;&lt;/ul&gt;", "first_published": iso(NOW - timedelta(minutes=3)), "location": {"name": "Tel Aviv, Israel"}}
        try:
            s3 = r.run(2)
        finally:
            GH_LIST["jobs"].pop()
        self.assertEqual([(a[0].title, a[1].tier) for a in s3["alerts"]], [("Software Engineer", "C")])

    def test_stale_and_rejects_are_recorded_not_alerted(self):
        http = FakeHttp({"boards-api.greenhouse.io": gh_route})
        r = self.mk(http)
        r.run(0)
        jobs = r.state.company("acme")["jobs"]
        self.assertEqual(set(jobs), {"1", "2", "3", "4"})
        self.assertEqual(jobs["1"]["a"], 1)
        self.assertEqual(jobs["2"]["r"], "seniority: Senior")
        self.assertEqual(jobs["3"]["r"], "baseline")

    def test_failure_does_not_touch_state_and_counts_streak(self):
        r = self.mk(FakeHttp({"boards-api.greenhouse.io": "FAIL"}))
        s = r.run(0)
        self.assertEqual(s["ok"], 0)
        self.assertEqual(r.state.company("acme")["fail_streak"], 1)
        self.assertEqual(r.state.company("acme")["jobs"], {})
        r.run(1)
        self.assertEqual(r.state.company("acme")["fail_streak"], 2)
        self.assertTrue(r.state.is_first_scan("acme"))  # still baseline: nothing silently swallowed

    def test_enrich_failure_retries_next_run(self):
        calls = {"n": 0}

        def route(url):
            if url.endswith("/jobs"):
                return {"jobs": [GH_LIST["jobs"][0]]}
            calls["n"] += 1
            if calls["n"] == 1:
                raise HttpError("HTTP 500", 500)
            return GH_DETAIL["1"]

        r = self.mk(FakeHttp({"boards-api.greenhouse.io": route}))
        self.assertEqual(r.run(0)["alerts"], [])
        self.assertEqual(r.state.company("acme")["jobs"], {})
        self.assertEqual(len(r.run(1)["alerts"]), 1)

    def test_tier_schedule(self):
        cs = [dict(COMPANY, id="t1", tier=1), dict(COMPANY, id="t3", tier=3, name="T3")]
        r = self.mk(FakeHttp({"x": {}}), companies=cs)
        r.state.ensure_company("t1", NOW); r.state.mark_ok("t1", NOW, set())
        r.state.ensure_company("t3", NOW); r.state.mark_ok("t3", NOW, set())
        self.assertEqual([c["id"] for c in r.due(cs, 1, False)], ["t1"])
        self.assertEqual([c["id"] for c in r.due(cs, 6, False)], ["t1", "t3"])
        self.assertEqual(len(r.due(cs, 1, True)), 2)

    def test_cross_source_dedupe(self):
        a = dict(COMPANY, id="acme-gh")
        b = dict(COMPANY, id="acme-lever", ats="lever", token="acme")
        lever = [{"id": "L1", "text": "Junior Backend Engineer", "categories": {"location": "Tel Aviv, Israel", "commitment": "Full-time"},
                  "descriptionPlain": "x", "hostedUrl": "https://l/1", "createdAt": int((NOW - timedelta(hours=1)).timestamp() * 1000)}]
        http = FakeHttp({"boards-api.greenhouse.io": gh_route, "api.lever.co": lever})
        s = self.mk(http, companies=[a, b]).run(0)
        self.assertEqual(len([x for x in s["alerts"] if x[0].title == "Junior Backend Engineer"]), 1)


class TestFetchers(unittest.TestCase):
    def run_one(self, ats, payload, extra=None, url_key=None):
        c = dict(COMPANY, id=ats, ats=ats, token="acme", **(extra or {}))
        http = FakeHttp({url_key or "": payload})
        r = Radar(load_config(None), [c], State(), http, now=NOW, dry_run=True)
        return r.fetchers[ats].list_jobs(c), r, c

    def test_lever(self):
        jobs, _, _ = self.run_one("lever", [{"id": "a", "text": "Graduate Security Engineer", "categories": {"location": "Herzliya", "commitment": "Full-time"},
                                              "descriptionPlain": "Be great", "lists": [{"text": "Requirements", "content": "<li>1 year of experience</li>"}],
                                              "hostedUrl": "https://l/a", "createdAt": 1760875200000, "workplaceType": "hybrid"}])
        j = jobs[0]
        self.assertEqual(j.date_kind, "created")
        self.assertEqual(j.posted_at.year, 2025)
        self.assertIn("1 year of experience", j.description)

    def test_ashby_skips_unlisted(self):
        jobs, _, _ = self.run_one("ashby", {"jobs": [
            {"id": "1", "title": "Backend Engineer", "location": "Tel Aviv", "secondaryLocations": [{"location": "Remote"}], "isListed": True,
             "descriptionPlain": "d", "publishedAt": "2026-10-19T10:00:00.000+00:00", "jobUrl": "https://a/1", "workplaceType": "Hybrid"},
            {"id": "2", "title": "Hidden", "isListed": False}]})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].location, "Tel Aviv | Remote")
        self.assertEqual(jobs[0].date_kind, "published")

    def test_comeet(self):
        jobs, _, _ = self.run_one("comeet", [{"uid": "AB.123", "name": "Junior Developer", "location": {"name": "Tel Aviv, Israel"}, "experience_level": "Entry level",
                                              "time_updated": "2026-10-19T09:00:00Z", "url_active_page": "https://c/1", "details": [{"name": "Requirements", "value": "<p>BSc</p>", "order": 1}]}],
                                  extra={"uid": "U1"})
        self.assertEqual(jobs[0].level, "Entry level")
        self.assertEqual(jobs[0].date_kind, "updated")

    def test_smartrecruiters_paging(self):
        calls = []

        def route(url):
            calls.append(url)
            return {"totalFound": 150, "content": [{"id": str(i), "name": "Dev", "releasedDate": "2026-10-19T08:00:00.000Z",
                                                    "location": {"city": "Tel Aviv", "country": "il"}} for i in range(100 if len(calls) == 1 else 50)]}

        jobs, _, _ = self.run_one("smartrecruiters", route)
        self.assertEqual(len(jobs), 150)

    def test_workday_relative_dates(self):
        d, ok = parse_relative_en("Posted Yesterday", NOW)
        self.assertTrue(ok)
        self.assertEqual(d.day, 18)
        d, ok = parse_relative_en("Posted 30+ Days Ago", NOW)
        self.assertFalse(ok)
        payload = {"total": 2, "jobPostings": [
            {"title": "Junior Software Engineer", "externalPath": "/job/Israel/Junior-SWE_JR1", "locationsText": "Israel, Yokneam", "postedOn": "Posted Today"},
            {"title": "Old", "externalPath": "/job/Israel/Old_JR2", "locationsText": "Israel", "postedOn": "Posted 30+ Days Ago"}]}
        jobs, _, _ = self.run_one("workday", payload, extra={"host": "x.wd5.myworkdayjobs.com", "tenant": "x", "site": "S"})
        self.assertEqual(jobs[0].date_kind, "relative")
        self.assertEqual(jobs[1].date_kind, "unknown")
        self.assertIsNone(jobs[1].posted_at)

    def test_workday_uses_israel_facet_and_reads_every_page(self):
        from radar.fetchers.workday import Workday
        facets = [{"facetParameter": "locationMainGroup", "values": [{"facetParameter": "locations", "values": [
            {"descriptor": "India, Bangalore", "id": "in"}, {"descriptor": "Israel, Haifa", "id": "hf"},
            {"descriptor": "Israel, Petah-Tikva", "id": "pt"}]}]}]

        class Http:
            bodies = []

            def get_json(self, url, method="GET", json=None, **kw):
                self.bodies.append(json)
                if json["limit"] == 1:
                    return {"total": 900, "facets": facets, "jobPostings": []}
                off = json["offset"]
                posts = [{"title": f"Job {i}", "externalPath": f"/job/{i}", "postedOn": "Posted Today"}
                         for i in range(off, min(off + 20, 45))]
                return {"total": 45 if off == 0 else 0, "jobPostings": posts}  # later pages report total=0

        http = Http()
        jobs = Workday(http).list_jobs({"id": "x", "name": "X", "host": "x.wd1.myworkdayjobs.com", "tenant": "x", "site": "S"})
        self.assertEqual(len(jobs), 45)
        self.assertEqual(http.bodies[1]["appliedFacets"], {"locations": ["hf", "pt"]})
        self.assertEqual(Workday.country_facet([{"facetParameter": "Country", "values": [
            {"descriptor": "Israel", "id": "il"}]}] + facets, "Israel"), {"Country": ["il"]})

    def test_telegram_channel(self):
        html = '''<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="jobs_il/42">
        <div class="tgme_widget_message_text js-message_text">Junior Backend Developer at Acme<br/>Tel Aviv <a href="https://acme.com/careers/7">apply</a></div>
        <a class="tgme_widget_message_date" href="https://t.me/jobs_il/42"><time datetime="2026-10-19T11:30:00+00:00" class="time">11:30</time></a></div></div>'''
        c = dict(COMPANY, id="tg-jobs_il", ats="tgchannel", token="jobs_il")
        r = Radar(load_config(None), [], State(), FakeHttp({"t.me/s/jobs_il": html}), now=NOW, dry_run=True)
        jobs = r.fetchers["tgchannel"].list_jobs(c)
        self.assertEqual(jobs[0].url, "https://acme.com/careers/7")
        self.assertEqual(jobs[0].date_kind, "message")
        s = Radar(load_config({}) if False else load_config(None), [], State(), FakeHttp({"t.me/s/jobs_il": html}), now=NOW, dry_run=True)
        s.cfg["leads"]["telegram_channels"] = ["jobs_il"]
        out = s.run(0)
        self.assertEqual(len(out["alerts"]), 1)


class TestMisc(unittest.TestCase):
    def test_forget_rejections_only_new_jobs_with_matching_notes(self):
        s = State()
        s.record("acme", NOW - timedelta(hours=10), "0", "baseline job", False, "no experience signal")
        for jid, alerted, note in [("1", False, "no experience signal"), ("2", True, "ok"), ("3", False, "seniority: Senior"),
                                   ("4", False, "role excluded: Frontend"), ("5", False, "role excluded: Sales")]:
            s.record("acme", NOW, jid, "t", alerted, note)
        s.company("acme")["first_scan"] = iso(NOW - timedelta(hours=10))
        self.assertEqual(s.forget_rejections(NOW - timedelta(hours=72), r"^no experience signal$|^role excluded: .*front"), 2)
        self.assertEqual(sorted(s.company("acme")["jobs"]), ["0", "2", "3", "5"])

    def test_html_to_text_bullets(self):
        t = html_to_text("&lt;p&gt;Intro&lt;/p&gt;&lt;ul&gt;&lt;li&gt;3 years&lt;/li&gt;&lt;li&gt;BSc&lt;/li&gt;&lt;/ul&gt;")
        self.assertEqual(t.splitlines(), ["Intro", "• 3 years", "• BSc"])

    def test_discovery_extracts_ats(self):
        html = '''<a href="https://boards.greenhouse.io/acme/jobs/123">x</a>
        <iframe src="https://jobs.lever.co/acme-labs"></iframe><a href="https://jobs.ashbyhq.com/Acme%20Inc">
        <a href="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite">w</a>
        <script>Comeet.init({'token':'0123456789ABCDEF','company-uid':'12.345'})</script>
        <a href="https://www.comeet.com/jobs/acme/12.345">c</a>'''
        c = candidates_from_html(html)
        kinds = {(x["ats"], x.get("token") or x.get("tenant") or x.get("uid")) for x in c}
        self.assertIn(("greenhouse", "acme"), kinds)
        self.assertIn(("lever", "acme-labs"), kinds)
        self.assertIn(("workday", "nvidia"), kinds)
        self.assertTrue(any(x["ats"] == "comeet" and x.get("token") == "0123456789ABCDEF" for x in c) or any(x["ats"] == "comeet" for x in c))

    def test_slug_variants(self):
        v = slug_variants("Cato Networks", "catonetworks.com", ["hint"])
        self.assertEqual(v[0], "hint")
        self.assertIn("catonetworks", v)
        self.assertIn("cato-networks", v)

    def test_alert_format_escapes_and_labels(self):
        from radar.models import Job, Verdict
        j = Job("a", "Acme <b>", "1", "Junior <script> Dev", "https://x/?a=1&b=2", "Tel Aviv", posted_at=NOW - timedelta(minutes=5), date_kind="published", date_source="x.y")
        v = Verdict(True, tier="A", region="israel", reasons=["כותרת: Junior"], tags=["clearance"])
        txt = format_alert(j, v, {"tier": 1}, NOW)
        self.assertNotIn("<script>", txt)
        self.assertIn("&amp;b=2", txt)
        self.assertIn("פורסמה", txt)
        self.assertIn("🔒", txt)


if __name__ == "__main__":
    unittest.main()
