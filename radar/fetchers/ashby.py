from __future__ import annotations

from ..models import Job
from ..textutil import html_to_text, parse_iso


class Ashby:
    """https://api.ashbyhq.com/posting-api/job-board/{name}  (public, no key).
    Description is part of the list. `publishedAt` = when the posting was last published.
    Postings with isListed == false are reachable only by direct link and are skipped."""

    name = "ashby"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        data = self.http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{c['token']}")
        out = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False or not j.get("id"):
                continue
            locs = [j.get("location") or ""]
            for s in j.get("secondaryLocations") or []:
                locs.append(s.get("location", "") if isinstance(s, dict) else str(s))
            wt = (j.get("workplaceType") or "").lower()
            desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
            out.append(Job(
                company_id=c["id"], company=c["name"], job_id=str(j["id"]),
                title=(j.get("title") or "").strip(), url=j.get("jobUrl") or j.get("applyUrl") or "",
                location=" | ".join(x for x in locs if x), description=desc or "",
                posted_at=parse_iso(j.get("publishedAt")), date_kind="published", date_source="ashby.publishedAt",
                remote=True if (j.get("isRemote") or wt == "remote") else None,
                employment=j.get("employmentType") or "", source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
