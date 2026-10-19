from __future__ import annotations

from ..models import Job
from ..textutil import html_to_text, parse_iso


class SmartRecruiters:
    """https://api.smartrecruiters.com/v1/companies/{id}/postings  (public when the customer enabled it).
    Paged with limit/offset. `releasedDate` is the posting release time; the list has no description,
    so enrich() reads the single posting."""

    name = "smartrecruiters"
    BASE = "https://api.smartrecruiters.com/v1/companies"
    PAGE = 100

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        out, offset, total = [], 0, None
        while total is None or offset < total:
            data = self.http.get_json(f"{self.BASE}/{c['token']}/postings", params={"limit": self.PAGE, "offset": offset})
            total = int(data.get("totalFound", 0))
            items = data.get("content") or []
            if not items:
                break
            for p in items:
                loc = p.get("location") or {}
                location = loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("country", "").upper()) if x)
                out.append(Job(
                    company_id=c["id"], company=c["name"], job_id=str(p.get("id")),
                    title=(p.get("name") or "").strip(),
                    url=f"https://jobs.smartrecruiters.com/{c['token']}/{p.get('id')}",
                    location=location, posted_at=parse_iso(p.get("releasedDate")),
                    date_kind="published", date_source="smartrecruiters.releasedDate",
                    remote=True if loc.get("remote") else None,
                    employment=(p.get("typeOfEmployment") or {}).get("label", ""),
                    level=(p.get("experienceLevel") or {}).get("label", ""), source=self.name,
                ))
            offset += self.PAGE
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        d = self.http.get_json(f"{self.BASE}/{c['token']}/postings/{job.job_id}")
        secs = ((d.get("jobAd") or {}).get("sections")) or {}
        job.description = "\n".join(
            f"{v.get('title', '')}\n{html_to_text(v.get('text'))}" for v in secs.values() if isinstance(v, dict)
        )
        if d.get("postingUrl"):
            job.url = d["postingUrl"]
        return job
