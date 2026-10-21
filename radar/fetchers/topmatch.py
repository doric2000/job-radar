from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..models import Job
from ..textutil import html_to_text

API = "https://careers.topmatch.co.il/CandidateAPI/api//position/Search/{guid}"
APPLY = "https://careers.topmatch.co.il/{site}/redmatch-apply/redmatch.apply.html?compPositionID={pid}&affiliateGUID={guid}"


class TopMatch:
    """TopMatch / RedMatch career sites (careers.topmatch.co.il/{site}/...), used by Israeli hospitals,
    public bodies and companies. One POST returns every open position with its HTML description.
    Config: token = the affiliateGUID from the site's links, site = the path segment after the host.
    `activationDate` is the publication time in Israel local time."""

    name = "topmatch"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        data = self.http.get_json(API.format(guid=c["token"]), method="POST",
                                  json={"KeyWords": "", "CategoryId": [], "countryId": "2", "cityId": []})
        if not isinstance(data, dict):
            raise ValueError("unexpected TopMatch payload")
        if data.get("errorDescription") and not data.get("positions"):
            raise ValueError(f"TopMatch: {data['errorDescription']}")  # e.g. "Execution error" for a bad request body
        out = []
        for p in data.get("positions") or []:
            pid = str(p.get("compPositionID"))
            try:
                when = datetime.fromisoformat((p.get("activationDate") or "")[:19]).replace(tzinfo=ZoneInfo("Asia/Jerusalem"))
            except ValueError:
                when = None
            loc = p.get("displayLocation") or p.get("location") or ""
            out.append(Job(
                company_id=c["id"], company=c["name"], job_id=pid, title=(p.get("jobTitleText") or "").strip(),
                url=APPLY.format(site=c["site"], pid=pid, guid=c["token"]),
                location=", ".join(x for x in (loc, "Israel") if x),
                description=html_to_text(p.get("description")),
                posted_at=when, date_kind="published" if when else "unknown", date_source="topmatch.activationDate",
                source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
