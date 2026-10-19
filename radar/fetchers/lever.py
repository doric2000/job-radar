from __future__ import annotations

from ..models import Job
from ..textutil import from_ms, html_to_text


class Lever:
    """https://api.lever.co/v0/postings/{site}?mode=json  (EU tenants: api.eu.lever.co).
    The list already contains the full description, so no detail call is needed.
    `createdAt` is epoch milliseconds and means creation of the posting."""

    name = "lever"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        base = "https://api.eu.lever.co" if c.get("region") == "eu" else "https://api.lever.co"
        data = self.http.get_json(f"{base}/v0/postings/{c['token']}", params={"mode": "json"})
        if not isinstance(data, list):
            raise ValueError("unexpected Lever payload")
        out = []
        for p in data:
            if not p.get("id"):
                continue
            cats = p.get("categories") or {}
            location = cats.get("location") or ", ".join(cats.get("allLocations") or [])
            parts = [p.get("descriptionPlain") or html_to_text(p.get("description"))]
            for lst in p.get("lists") or []:
                parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
            parts.append(p.get("additionalPlain") or html_to_text(p.get("additional")))
            wt = (p.get("workplaceType") or "").lower()
            out.append(Job(
                company_id=c["id"], company=c["name"], job_id=str(p["id"]),
                title=(p.get("text") or "").strip(), url=p.get("hostedUrl") or p.get("applyUrl") or "",
                location=location or "", description="\n".join(x for x in parts if x),
                posted_at=from_ms(p.get("createdAt")), date_kind="created", date_source="lever.createdAt",
                remote=True if wt == "remote" else None,
                employment=cats.get("commitment") or "", source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
