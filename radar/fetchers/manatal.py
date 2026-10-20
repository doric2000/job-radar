from __future__ import annotations

from ..models import Job
from ..textutil import html_to_text


class Manatal:
    """Manatal career pages (careers-page.com/{slug}): https://api.manatal.com/open/v3/career-page/{slug}/jobs/
    Paged with `next`; each job carries its description. No publication date is exposed."""

    name = "manatal"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        out, url, params = [], f"https://api.manatal.com/open/v3/career-page/{c['token']}/jobs/", {}
        for _ in range(20):
            data = self.http.get_json(url, params=params)
            for p in data.get("results") or []:
                out.append(Job(
                    company_id=c["id"], company=c["name"], job_id=str(p.get("id")),
                    title=(p.get("position_name") or "").strip(),
                    url=f"https://www.careers-page.com/{c['token']}/job/{p.get('hash')}",
                    location=p.get("location_display") or ", ".join(x for x in (p.get("city"), p.get("country")) if x),
                    description=html_to_text(p.get("description")), remote=True if p.get("is_remote") else None,
                    employment=p.get("contract_details") or "", source=self.name,
                ))
            if not data.get("next"):
                break
            url, params = data["next"], {}
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
