import unittest
from urllib.parse import urlencode

from radar.config import load_config
from radar.fetchers.amazon import Amazon
from radar.fetchers.checkpoint import CheckPoint
from radar.fetchers.eightfold import Eightfold
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

    def test_bad_job_does_not_stop_the_run(self):
        http = ParamHttp({"start=10": EF_PAGE2, "pcsx/search": EF_PAGE, "position_details": EF_DETAIL})
        c = {"id": "ms", "name": "MS", "ats": "eightfold", "host": "h", "domain": "d", "tier": 1}
        r = Radar(load_config(None), [c], State(), http, now=NOW, dry_run=True)
        r.clf.classify = lambda j: (_ for _ in ()).throw(TypeError("boom"))
        out = r.run(0)
        self.assertEqual(out["errors"], [])


if __name__ == "__main__":
    unittest.main()
