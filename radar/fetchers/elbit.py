from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from ..models import Job
from ..textutil import html_to_text

FEED = "https://elbitsystemscareer.com/cron/jobs.json"
JOB_URL = "https://elbitsystemscareer.com/job/?jid={id}"


class Elbit:
    """elbitsystemscareer.com publishes every open position (~550) in one JSON file that its own site loads:
    title, HTML-escaped description and requirements, division (employerName), area/cities and openDate
    (Israel local time, publication). No detail request is needed."""

    name = "elbit"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        data = self.http.get_json(c.get("feed", FEED))
        if not isinstance(data, list):
            raise ValueError("unexpected Elbit feed")
        out = []
        for p in data:
            if str(p.get("status", "1")) != "1":
                continue
            props = {x.get("PropertyName"): x.get("Value") for x in p.get("extendedProperties") or [] if isinstance(x, dict)}
            try:
                when = datetime.fromisoformat((p.get("openDate") or "")[:19]).replace(tzinfo=ZoneInfo("Asia/Jerusalem"))
            except ValueError:
                when = None
            desc = "\n".join(html_to_text(html.unescape(p.get(k) or "")) for k in ("description", "requirements", "skills"))
            out.append(Job(
                company_id=c["id"], company=f"{c['name']} · {p['employerName']}" if p.get("employerName") else c["name"],
                job_id=str(p.get("jobId")), title=(p.get("jobTitle") or "").strip(), url=JOB_URL.format(id=p.get("jobId")),
                # "Cities" holds internal city ids, so the area name ("Center", "Sharon") is used instead
                location=", ".join(x for x in (p.get("area") or props.get("Area"), "Israel") if x),
                description=desc.strip(), posted_at=when, date_kind="published" if when else "unknown",
                date_source="elbit.openDate", source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
