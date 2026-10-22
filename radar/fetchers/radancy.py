from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..filters import ISRAEL_TERMS
from ..models import Job
from ..textutil import parse_iso

PARAMS = {"ActiveFacetID": 0, "RecordsPerPage": 100, "Distance": 50, "RadiusUnitType": 0, "Keywords": "", "Location": "",
          "ShowRadius": "False", "IsPagination": "True", "SearchResultsModuleName": "Search Results",
          "SearchFiltersModuleName": "Search Filters", "SortCriteria": 0, "SortDirection": 0, "SearchType": 5}


class Radancy:
    """Radancy (TalentBrew) career fronts such as jobs.intuit.com: /search-jobs/results returns JSON whose
    `results` is HTML with a.sr-item cards (title in h2, location in span.job-location), 100 per page,
    newest first. The location filter in the URL is ignored, so cards are kept when their location matches
    `location_filter` (default 'Israel'). The job page has a schema.org JobPosting with datePosted."""

    name = "radancy"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        keep = re.compile(c.get("location_filter", "Israel"), re.I)
        out: dict[str, Job] = {}
        for page in range(1, int(c.get("max_pages", 10)) + 1):
            data = self.http.get_json(f"https://{c['host']}/search-jobs/results", params={**PARAMS, "CurrentPage": page},
                                      headers={"X-Requested-With": "XMLHttpRequest"})
            cards = BeautifulSoup(data.get("results") or "", "html.parser").select("a.sr-item[href*='/job/']")
            for a in cards:
                m = re.search(r"/(\d+)/?$", a["href"])
                loc = a.select_one(".job-location")
                location = loc.get_text(" ", strip=True) if loc else ""
                if not keep.search(location):
                    # cards often say "Multiple Locations"; the primary city is in the URL: /job/petah-tikva/...
                    parts = a["href"].strip("/").split("/")
                    city = parts[1].replace("-", " ") if len(parts) > 1 else ""
                    if not ISRAEL_TERMS.search(city):
                        continue
                    location = f"{city.title()}, Israel ({location})" if location else f"{city.title()}, Israel"
                if not m or m.group(1) in out:
                    continue
                title = a.select_one("h2")
                out[m.group(1)] = Job(
                    company_id=c["id"], company=c["name"], job_id=m.group(1),
                    title=(title.get_text(" ", strip=True) if title else a.get("data-title", "")),
                    url=f"https://{c['host']}{a['href']}", location=location, source=self.name,
                )
            if len(cards) < PARAMS["RecordsPerPage"]:
                break
        return list(out.values())

    def enrich(self, job: Job, c: dict) -> Job:
        soup = BeautifulSoup(self.http.get_text(job.url), "html.parser")
        body = soup.select_one("section.job-description") or soup.select_one(".job-description")
        if body is None:
            raise ValueError("Radancy job page without a description")
        job.description = body.get_text("\n", strip=True)
        for s in soup.select('script[type="application/ld+json"]'):
            try:
                d = json.loads(s.string or "")
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("datePosted"):
                job.posted_at, job.date_kind, job.date_source = parse_iso(d["datePosted"]), "published", "radancy.datePosted"
                break
        return job
