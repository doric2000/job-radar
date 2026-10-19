import unittest
from datetime import timedelta

from radar.config import load_config
from radar.fetchers.linkedin import Blocked, LinkedIn, parse_ago
from radar.http import HttpError
from radar.notify import format_alert
from radar.run import Radar
from radar.state import State
from tests.test_fetchers_and_run import NOW, FakeHttp


def card(jid, title, company="Acme", loc="Tel Aviv-Yafo, Tel Aviv District, Israel", ago="26 minutes ago", date="2026-10-19"):
    return f'''<li><div class="base-card base-search-card" data-entity-urn="urn:li:jobPosting:{jid}">
      <a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/x-{jid}?trk=1"></a>
      <h3 class="base-search-card__title">{title}</h3>
      <h4 class="base-search-card__subtitle"><a class="hidden-nested-link">{company}</a></h4>
      <span class="job-search-card__location">{loc}</span>
      <time class="job-search-card__listdate--new" datetime="{date}">{ago}</time></div></li>'''


DETAIL = '''<div class="show-more-less-html__markup"><p>Join our backend team.</p><ul><li>BSc in Computer Science</li></ul></div>
<ul><li class="description__job-criteria-item"><h3>Seniority level</h3><span>Associate</span></li>
<li class="description__job-criteria-item"><h3>Employment type</h3><span>Full-time</span></li></ul>'''

LI = {"id": "linkedin", "name": "LinkedIn", "ats": "linkedin", "gap_seconds": 0, "cooldown_seconds": 0,
      "queries": [{"keywords": "backend", "f_E": "1,2"}, {"keywords": "security"}]}


def limited(url):
    raise HttpError("HTTP 429", 429)


class TestLinkedIn(unittest.TestCase):
    def test_parse_ago(self):
        when, kind = parse_ago("26 minutes ago", "2026-10-19", NOW)
        self.assertEqual((when, kind), (NOW - timedelta(minutes=26), "published"))
        self.assertEqual(parse_ago("3 days ago", "2026-10-16", NOW)[1], "relative")
        self.assertEqual(parse_ago("", "2026-10-16", NOW)[1], "relative")
        self.assertEqual(parse_ago("", "", NOW), (None, "unknown"))

    def test_list_dedupes_across_queries(self):
        http = FakeHttp({
            "keywords=backend": card(1, "Junior Backend Engineer") + card(2, "Senior Backend Engineer"),
            "keywords=security": card(1, "Junior Backend Engineer") + card(3, "Security Analyst", company="Bank"),
        })
        jobs = LinkedIn(http).list_jobs(LI)
        self.assertEqual([j.job_id for j in jobs], ["1", "2", "3"])
        self.assertEqual(jobs[0].url, "https://www.linkedin.com/jobs/view/1/")
        self.assertEqual((jobs[0].company, jobs[0].date_kind), ("Acme", "published"))
        self.assertIn("f_E=1%2C2", http.calls[0])
        self.assertIn("geoId=101620260", http.calls[0])

    def test_rate_limit_keeps_partial_results_then_blocks(self):
        http = FakeHttp({"keywords=backend": card(1, "Junior Backend Engineer"), "keywords=security": limited})
        li = LinkedIn(http)
        jobs = li.list_jobs(LI)
        self.assertEqual([j.job_id for j in jobs], ["1"])
        with self.assertRaises(Blocked):  # no further LinkedIn requests in this run
            li.enrich(jobs[0], LI)

    def test_rate_limit_with_nothing_collected_raises(self):
        with self.assertRaises(Blocked):
            LinkedIn(FakeHttp({"seeMoreJobPostings": limited})).list_jobs(LI)

    def test_enrich_reads_description_not_seniority(self):
        li = LinkedIn(FakeHttp({"seeMoreJobPostings": card(1, "Backend Engineer"), "jobPosting/1": DETAIL}))
        job = li.enrich(li.list_jobs(LI)[0], LI)
        self.assertIn("BSc in Computer Science", job.description)
        self.assertEqual((job.employment, job.level), ("Full-time", ""))

    def test_run_alerts_junior_and_tags_linkedin(self):
        http = FakeHttp({
            "keywords=backend": card(1, "Junior Backend Engineer") + card(2, "Senior Backend Engineer"),
            "keywords=security": "",
            "jobPosting/1": DETAIL,
        })
        cfg = load_config(None)
        cfg["leads"]["linkedin"].update(enabled=True, gap_seconds=0, cooldown_seconds=0, queries=LI["queries"])
        r = Radar(cfg, [], State(), http, now=NOW, dry_run=True)
        out = r.run(0)
        self.assertEqual([a[0].job_id for a in out["alerts"]], ["1"])
        self.assertFalse(any("jobPosting/2" in u for u in http.calls))  # senior title rejected before the detail call
        j, v, c = out["alerts"][0]
        text = format_alert(j, v, c, NOW)
        self.assertIn("LinkedIn", text)
        self.assertNotIn("⭐", text)


if __name__ == "__main__":
    unittest.main()
