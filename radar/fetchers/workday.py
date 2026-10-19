from __future__ import annotations

from ..models import Job
from ..textutil import html_to_text, parse_relative_en


class Workday:
    """BEST-EFFORT, undocumented 'cxs' endpoint used by Workday career sites:
    POST https://{host}/wday/cxs/{tenant}/{site}/jobs   body {limit<=20, offset, searchText, appliedFacets}
    Config keys: host (e.g. nvidia.wd5.myworkdayjobs.com), tenant, site, search (default 'Israel'), max_pages.
    `postedOn` is a localised relative string ('Posted Today', 'Posted 3 Days Ago', 'Posted 30+ Days Ago'),
    so dates are day-precision at best and marked date_kind='relative'."""

    name = "workday"
    PAGE = 20  # requests with limit > 20 return an empty list with HTTP 200

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        host, tenant, site = c["host"], c["tenant"], c["site"]
        search = c.get("search", "Israel")
        out, offset, total = [], 0, None
        max_pages = int(c.get("max_pages", 10))
        for _ in range(max_pages):
            d = self.http.get_json(
                f"https://{host}/wday/cxs/{tenant}/{site}/jobs", method="POST",
                json={"appliedFacets": {}, "limit": self.PAGE, "offset": offset, "searchText": search},
                headers={"Accept-Language": "en-US", "Content-Type": "application/json"},
            )
            total = d.get("total", total)
            posts = d.get("jobPostings") or []
            if not posts:
                if offset == 0 and total:
                    raise ValueError("Workday returned total>0 but no postings (limit/headers changed?)")
                break
            for p in posts:
                path = p.get("externalPath") or ""
                if not path:
                    continue
                when, exact = parse_relative_en(p.get("postedOn", ""))
                out.append(Job(
                    company_id=c["id"], company=c["name"], job_id=path, title=(p.get("title") or "").strip(),
                    url=f"https://{host}/{site}{path}", location=p.get("locationsText") or "",
                    posted_at=when if exact else None, date_kind="relative" if exact else "unknown",
                    date_source=f"workday.postedOn='{p.get('postedOn', '')}'", source=self.name,
                ))
            offset += self.PAGE
            if total is not None and offset >= int(total):
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
