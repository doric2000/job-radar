from __future__ import annotations

from ..models import Job
from ..textutil import html_to_text, parse_iso


class Recruitee:
    """BEST-EFFORT. https://{subdomain}.recruitee.com/api/offers/
    Field names (`published_at`, `careers_url`, `remote`) not verified live from the build environment."""

    name = "recruitee"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        d = self.http.get_json(f"https://{c['token']}.recruitee.com/api/offers/")
        out = []
        for o in d.get("offers", []):
            if o.get("id") is None or o.get("status") not in (None, "published"):
                continue
            loc = o.get("location") or ", ".join(x for x in (o.get("city"), o.get("country")) if x)
            desc = f"{html_to_text(o.get('description'))}\n{html_to_text(o.get('requirements'))}"
            out.append(Job(
                company_id=c["id"], company=c["name"], job_id=str(o["id"]), title=(o.get("title") or "").strip(),
                url=o.get("careers_url") or "", location=loc or "", description=desc.strip(),
                posted_at=parse_iso(o.get("published_at") or o.get("created_at")),
                date_kind="published" if o.get("published_at") else "created",
                date_source="recruitee.published_at" if o.get("published_at") else "recruitee.created_at",
                remote=True if o.get("remote") else None, employment=o.get("employment_type_code") or "",
                source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
