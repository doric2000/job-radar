from __future__ import annotations

from ..models import Job
from ..textutil import from_ms, html_to_text


class Eightfold:
    """Eightfold PCSX career sites (Microsoft, Qualcomm, Amdocs, ...):
    https://{host}/api/pcsx/search?domain={domain}&location={location}&start=N&sort_by=timestamp
    10 positions per page regardless of `num`. `postedTs` is the publication time (epoch seconds).
    The list has no description, so enrich() reads position_details."""

    name = "eightfold"
    PAGE = 10

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        out, start, total = [], 0, None
        while total is None or start < min(total, int(c.get("max_jobs", 400))):
            data = self.http.get_json(f"https://{c['host']}/api/pcsx/search", params={
                "domain": c["domain"], "query": "", "location": c.get("location", "Israel"),
                "start": start, "sort_by": "timestamp"})
            d = data.get("data") or {}
            total = int(d.get("count") or 0)
            items = d.get("positions") or []
            if not items:
                break
            for p in items:
                out.append(Job(
                    company_id=c["id"], company=c["name"], job_id=str(p.get("id")),
                    title=(p.get("name") or "").strip(), url=f"https://{c['host']}/careers/job/{p.get('id')}",
                    location=" | ".join(p.get("locations") or []), posted_at=from_ms(p.get("postedTs")),
                    date_kind="published", date_source="eightfold.postedTs",
                    remote=True if p.get("workLocationOption") == "remote" else None, source=self.name,
                ))
            start += self.PAGE
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        data = self.http.get_json(f"https://{c['host']}/api/pcsx/position_details",
                                  params={"position_id": job.job_id, "domain": c["domain"], "hl": "en"})
        d = data.get("data") or {}
        job.description = html_to_text(d.get("jobDescription"))
        emp = d.get("efcustomTextEmploymentType") or job.employment
        job.employment = ", ".join(emp) if isinstance(emp, list) else str(emp or "")
        if d.get("publicUrl"):
            job.url = d["publicUrl"]
        return job
