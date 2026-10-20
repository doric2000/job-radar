from __future__ import annotations

from datetime import datetime, timezone

from ..models import Job
from ..textutil import html_to_text


class Amazon:
    """https://www.amazon.jobs/en/search.json?country=ISR  - the JSON behind amazon.jobs search (no key).
    The list already carries the description and qualifications, so enrich() is a no-op.
    `posted_date` ('October 19, 2026') is a publication date with day precision -> date_kind='relative'."""

    name = "amazon"
    URL = "https://www.amazon.jobs/en/search.json"
    PAGE = 100

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        out, offset, total = [], 0, None
        while total is None or offset < min(total, 2000):
            data = self.http.get_json(self.URL, params={
                "country": c.get("country", "ISR"), "result_limit": self.PAGE, "offset": offset, "sort": "recent"})
            total = int(data.get("hits") or 0)
            items = data.get("jobs") or []
            if not items:
                break
            for p in items:
                try:
                    when = datetime.strptime(p.get("posted_date") or "", "%B %d, %Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    when = None
                desc = "\n".join(x for x in (
                    html_to_text(p.get("description")),
                    "Basic qualifications\n" + html_to_text(p.get("basic_qualifications")),
                    "Preferred qualifications\n" + html_to_text(p.get("preferred_qualifications")),
                ) if x.strip())
                out.append(Job(
                    company_id=c["id"], company=p.get("company_name") or c["name"], job_id=str(p.get("id_icims") or p.get("id")),
                    title=(p.get("title") or "").strip(), url=f"https://www.amazon.jobs{p.get('job_path', '')}",
                    location=", ".join(x for x in (p.get("city"), "Israel" if p.get("country_code") == "ISR" else p.get("country_code")) if x),
                    description=desc, posted_at=when, date_kind="relative" if when else "unknown",
                    date_source="amazon.posted_date", employment=p.get("job_schedule_type") or "", source=self.name,
                ))
            offset += self.PAGE
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
