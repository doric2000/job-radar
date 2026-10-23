from __future__ import annotations

import re

from ..models import Job
from ..textutil import html_to_text, parse_relative_en


class Workday:
    """BEST-EFFORT, undocumented 'cxs' endpoint used by Workday career sites:
    POST https://{host}/wday/cxs/{tenant}/{site}/jobs   body {limit<=20, offset, searchText, appliedFacets}
    Config keys: host (e.g. nvidia.wd5.myworkdayjobs.com), tenant, site, search (country, default 'Israel'), max_pages.
    Jobs are filtered with the board's own location facet for that country (found on each run).
    `postedOn` is a localised relative string ('Posted Today', 'Posted 3 Days Ago', 'Posted 30+ Days Ago'),
    so dates are day-precision at best and marked date_kind='relative'."""

    name = "workday"
    PAGE = 20  # requests with limit > 20 return an empty list with HTTP 200

    def __init__(self, http):
        self.http = http

    def _post(self, c: dict, body: dict) -> dict:
        return self.http.get_json(
            f"https://{c['host']}/wday/cxs/{c['tenant']}/{c['site']}/jobs", method="POST",
            json={"limit": self.PAGE, "offset": 0, "searchText": "", "appliedFacets": {}, **body},
            headers={"Accept-Language": "en-US", "Content-Type": "application/json"},
        )

    @staticmethod
    def country_facet(facets: list, country: str) -> dict:
        """The board's own location filter for `country`: a country-level value ('Israel') when there is one,
        otherwise every location value that names the country ('Israel, Haifa', 'Tel Aviv-Yafo, Israel').
        Free-text search for 'Israel' also matches jobs elsewhere that mention Israel and misses others."""
        exact, partial = {}, {}

        def walk(items, param=None):
            for f in items or []:
                p = f.get("facetParameter", param)
                for v in f.get("values") or []:
                    if v.get("values"):
                        walk([v], p)
                        continue
                    name = (v.get("descriptor") or "").strip().lower()
                    if name == country.lower():
                        exact.setdefault(p, []).append(v["id"])
                    elif re.search(rf"\b{re.escape(country.lower())}\b", name):
                        partial.setdefault(p, []).append(v["id"])

        walk(facets)
        if exact:
            p = next(iter(exact))
            return {p: exact[p]}
        if partial:
            p = max(partial, key=lambda k: len(partial[k]))
            return {p: partial[p]}
        return {}

    def list_jobs(self, c: dict) -> list[Job]:
        host, site = c["host"], c["site"]
        search = c.get("search", "Israel")
        facets = self.country_facet(self._post(c, {"limit": 1}).get("facets") or [], search)
        body = {"appliedFacets": facets} if facets else {"searchText": search}
        out, seen, total = [], set(), None
        max_pages = int(c.get("max_pages", 30))
        for page in range(max_pages):
            d = self._post(c, {**body, "offset": page * self.PAGE})
            if page == 0:
                total = int(d.get("total") or 0)  # later pages report total=0
            posts = d.get("jobPostings") or []
            if not posts:
                if page == 0 and total:
                    raise ValueError("Workday returned total>0 but no postings (limit/headers changed?)")
                break
            fresh = 0
            for p in posts:
                path = p.get("externalPath") or ""
                if not path or path in seen:
                    continue
                seen.add(path)
                fresh += 1
                when, exact = parse_relative_en(p.get("postedOn", ""))
                out.append(Job(
                    company_id=c["id"], company=c["name"], job_id=path, title=(p.get("title") or "").strip(),
                    url=f"https://{host}/{site}{path}", location=p.get("locationsText") or "",
                    posted_at=when if exact else None, date_kind="relative" if exact else "unknown",
                    date_source=f"workday.postedOn='{p.get('postedOn', '')}'", source=self.name,
                ))
            if not fresh or (page + 1) * self.PAGE >= total:  # some boards ignore offset and repeat page 1
                break
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        host, tenant, site = c["host"], c["tenant"], c["site"]
        d = self.http.get_json(f"https://{host}/wday/cxs/{tenant}/{site}{job.job_id}", headers={"Accept-Language": "en-US"})
        info = d.get("jobPostingInfo") or {}
        job.description = html_to_text(info.get("jobDescription"))
        extra = ", ".join(info.get("additionalLocations") or [])
        if extra:
            job.location = f"{job.location} | {extra}".strip(" |")
        if info.get("timeType"):
            job.employment = info["timeType"]
        return job
