import unittest
from urllib.parse import urlencode

from radar.config import load_config
from radar.fetchers.amazon import Amazon
from radar.fetchers.checkpoint import CheckPoint
from radar.fetchers.eightfold import Eightfold
from radar.fetchers.htmllinks import HtmlLinks
from radar.fetchers.manatal import Manatal
from radar.fetchers.topmatch import TopMatch
from radar.fetchers.wordpress import WordPress
from radar.run import Radar
from radar.state import State
from tests.test_fetchers_and_run import NOW, FakeHttp


class ParamHttp(FakeHttp):
    """FakeHttp that routes on the query string too, so paging can be tested."""

    def get_json(self, url, method="GET", params=None, **kw):
        return self._find(f"{url}?{urlencode(params or {})}")

    def get_text(self, url, params=None, **kw):
        return self._find(f"{url}?{urlencode(params or {})}")


AMAZON = {"hits": 1, "jobs": [{
    "id_icims": "10582850", "title": "Software Development Engineer", "company_name": "Annapurna Labs Ltd.",
    "city": "Haifa", "country_code": "ISR", "posted_date": "October 19, 2026", "job_path": "/en/jobs/10582850/sde",
    "description": "Build things.", "basic_qualifications": "- Bachelor's degree in CS", "preferred_qualifications": "- 3+ years of experience",
    "job_schedule_type": "full-time"}]}

EF_PAGE = {"data": {"count": 11, "positions": [
    {"id": i, "name": f"Software Engineer {i}", "locations": ["Israel, Tel Aviv, Herzliya"], "postedTs": 1792478398,
     "workLocationOption": "onsite"} for i in range(10)]}}
EF_PAGE2 = {"data": {"count": 11, "positions": [{"id": 10, "name": "Security Research Intern", "locations": ["Israel, Herzliya"],
                                                  "postedTs": 1792478398}]}}
EF_DETAIL = {"data": {"jobDescription": "<p>Students welcome</p>", "efcustomTextEmploymentType": ["Internship"],
                      "publicUrl": "https://jobs.example/10"}}

CP_POS = '''<div class="position"><div class="icons-position-container"><div class="shareMenu share-menu hidden">
  <a href="https://wa.me/?text=index.php?m=cpcareers&a=show&joborderid={jid}">WhatsApp</a></div></div>
  <a href="https://careers.checkpoint.com/index.php?m=cpcareers&a=show&joborderid={jid}">{title}</a>
  <div class="posInfo"><p>Israel: Tel Aviv-Yafo</p><p>R&amp;D <span>|</span> Full-time <span>|</span> Job ID: REF1</p></div></div>'''


def cp_page(start):
    if start == 0:
        return CP_POS.format(jid="0001", title="Junior Backend Developer") + CP_POS.format(jid="0002", title="Senior Pipeline Engineer")
    return ""


class TestCompanySites(unittest.TestCase):
    def test_amazon(self):
        c = {"id": "amazon-israel", "name": "Amazon Israel"}
        [j] = Amazon(FakeHttp({"amazon.jobs/en/search.json": AMAZON})).list_jobs(c)
        self.assertEqual((j.job_id, j.company, j.location, j.date_kind), ("10582850", "Annapurna Labs Ltd.", "Haifa, Israel", "relative"))
        self.assertEqual(j.url, "https://www.amazon.jobs/en/jobs/10582850/sde")
        self.assertIn("Preferred qualifications", j.description)

    def test_eightfold_pages_and_detail(self):
        http = ParamHttp({"start=10": EF_PAGE2, "pcsx/search": EF_PAGE, "position_details": EF_DETAIL})
        c = {"id": "microsoft-israel", "name": "Microsoft Israel", "host": "apply.careers.microsoft.com", "domain": "microsoft.com"}
        ef = Eightfold(http)
        jobs = ef.list_jobs(c)
        self.assertEqual(len(jobs), 11)
        j = ef.enrich(jobs[-1], c)
        self.assertEqual((j.employment, j.url, j.date_kind), ("Internship", "https://jobs.example/10", "published"))

    def test_checkpoint_skips_share_links(self):
        http = ParamHttp({"start=0": cp_page(0), "start=10": cp_page(10)})
        jobs = CheckPoint(http).list_jobs({"id": "check-point", "name": "Check Point"})
        self.assertEqual([(j.job_id, j.title) for j in jobs], [("0001", "Junior Backend Developer"), ("0002", "Senior Pipeline Engineer")])
        self.assertEqual((jobs[0].location, jobs[0].employment), ("Tel Aviv-Yafo, Israel", "Full-time"))

    def test_wordpress_pages_until_short_page(self):
        post = {"id": 7, "title": {"rendered": "Full-Stack Developer &#8211; Junior"}, "link": "https://x.co.il/careers/7/",
                "content": {"rendered": "<p>No experience required</p>"}, "date_gmt": "2026-10-19T15:50:09"}
        http = ParamHttp({"page=1&": [post] * 100, "page=2&": [dict(post, id=8)]})
        jobs = WordPress(http).list_jobs({"id": "comblack", "name": "Comblack", "host": "x.co.il", "rest_base": "careers"})
        self.assertEqual(sorted(j.job_id for j in jobs), ["7", "8"])
        self.assertEqual((jobs[0].title, jobs[0].location, jobs[0].date_kind), ("Full-Stack Developer – Junior", "Israel", "published"))
        self.assertEqual(jobs[0].posted_at.isoformat(), "2026-10-19T15:50:09+00:00")

    def test_manatal(self):
        data = {"next": None, "results": [{"id": 1, "hash": "QWR35XXW", "position_name": "Full Stack Engineer",
                                           "location_display": "Tel Aviv, Israel", "description": "<p>React</p>"}]}
        [j] = Manatal(FakeHttp({"career-page/cydome/jobs": data})).list_jobs({"id": "cydome", "name": "Cydome", "token": "cydome"})
        self.assertEqual((j.url, j.location, j.description), ("https://www.careers-page.com/cydome/job/QWR35XXW", "Tel Aviv, Israel", "React"))

    def test_htmllinks_takes_first_non_empty_link_text(self):
        page = '<a href="/job-offer/full-stack/"><img></a><a href="/job-offer/full-stack/">Full-Stack Engineer</a><a href="/about/">x</a>'
        c = {"id": "m", "name": "M", "list_url": "https://m.ai/careers/", "link_pattern": "/job-offer/([^/]+)/?$"}
        [j] = HtmlLinks(FakeHttp({"m.ai/careers": page})).list_jobs(c)
        self.assertEqual((j.job_id, j.title, j.url), ("full-stack", "Full-Stack Engineer", "https://m.ai/job-offer/full-stack/"))

    def test_topmatch(self):
        data = {"positions": [{"compPositionID": 199462, "jobTitleText": "מפתח.ת AI ג׳וניור ", "activationDate": "2026-10-21T09:29:15.23",
                               "description": "<p>Python, SQL</p>", "displayLocation": "איכילוב"}], "responseStatus": 1}
        c = {"id": "ichilov", "name": "Ichilov", "token": "GUID", "site": "ichilovEmployeeReferral"}
        [j] = TopMatch(FakeHttp({"position/Search/GUID": data})).list_jobs(c)
        self.assertEqual((j.title, j.location, j.description, j.date_kind), ("מפתח.ת AI ג׳וניור", "איכילוב, Israel", "Python, SQL", "published"))
        self.assertEqual(j.posted_at.isoformat(), "2026-10-21T09:29:15+03:00")
        self.assertIn("compPositionID=199462&affiliateGUID=GUID", j.url)
        bad = {"positions": [], "responseStatus": 2, "errorDescription": "Execution error"}
        with self.assertRaises(ValueError):
            TopMatch(FakeHttp({"position/Search/GUID": bad})).list_jobs(c)

    def test_bad_job_does_not_stop_the_run(self):
        http = ParamHttp({"start=10": EF_PAGE2, "pcsx/search": EF_PAGE, "position_details": EF_DETAIL})
        c = {"id": "ms", "name": "MS", "ats": "eightfold", "host": "h", "domain": "d", "tier": 1}
        r = Radar(load_config(None), [c], State(), http, now=NOW, dry_run=True)
        r.clf.classify = lambda j: (_ for _ in ()).throw(TypeError("boom"))
        out = r.run(0)
        self.assertEqual(out["errors"], [])


if __name__ == "__main__":
    unittest.main()
