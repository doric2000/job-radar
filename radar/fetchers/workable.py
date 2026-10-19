from __future__ import annotations

from ..models import Job
from ..textutil import html_to_text, parse_iso


class Workable:
    """BEST-EFFORT. Widget API: https://www.workable.com/api/accounts/{subdomain}?details=true
    Field names (`published_on`, `created_at`, `shortcode`) come from public descriptions of the widget
    feed and have not been verified live from this build environment: run `--healthcheck` first."""

    name = "workable"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        d = self.http.get_json(f"https://www.workable.com/api/accounts/{c['token']}", params={"details": "true"})
        out = []
        for j in d.get("jobs", []):
            jid = j.get("shortcode") or j.get("code") or j.get("id")
            if not jid:
                continue
            loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
            out.append(Job(
                company_id=c["id"], company=c["name"], job_id=str(jid), title=(j.get("title") or "").strip(),
                url=j.get("url") or j.get("shortlink") or j.get("application_url") or "",
                location=loc, description=html_to_text(j.get("description")),
                posted_at=parse_iso(j.get("published_on") or j.get("created_at")),
                date_kind="published" if j.get("published_on") else "created",
                date_source="workable.published_on" if j.get("published_on") else "workable.created_at",
                remote=True if j.get("telecommuting") else None,
                employment=j.get("employment_type") or "", level=j.get("experience") or "", source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
