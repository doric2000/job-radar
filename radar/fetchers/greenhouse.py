from __future__ import annotations

from ..models import Job
from ..textutil import html_to_text, parse_iso


class Greenhouse:
    """https://boards-api.greenhouse.io/v1/boards/{token}/jobs  (public, no key).
    The list carries `updated_at` only; `first_published` exists on the single-job call,
    so enrich() upgrades the date for new jobs."""

    name = "greenhouse"
    BASE = "https://boards-api.greenhouse.io/v1/boards"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        data = self.http.get_json(f"{self.BASE}/{c['token']}/jobs")
        out = []
        for j in data.get("jobs", []):
            if j.get("id") is None:
                continue
            out.append(Job(
                company_id=c["id"], company=c["name"], job_id=str(j["id"]),
                title=(j.get("title") or "").strip(), url=j.get("absolute_url") or "",
                location=(j.get("location") or {}).get("name", "") or "",
                posted_at=parse_iso(j.get("first_published") or j.get("updated_at")),
                date_kind="published" if j.get("first_published") else "updated",
                date_source="greenhouse.first_published" if j.get("first_published") else "greenhouse.updated_at",
                source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        d = self.http.get_json(f"{self.BASE}/{c['token']}/jobs/{job.job_id}")
        job.description = html_to_text(d.get("content"))
        if d.get("first_published"):
            job.posted_at = parse_iso(d["first_published"])
            job.date_kind, job.date_source = "published", "greenhouse.first_published"
        loc = (d.get("location") or {}).get("name")
        if loc and not job.location:
            job.location = loc
        offices = ", ".join(o.get("location") or o.get("name", "") for o in (d.get("offices") or []) if o)
        if offices and offices not in job.location:
            job.location = f"{job.location} | {offices}".strip(" |")
        return job
