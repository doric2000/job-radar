from __future__ import annotations

from ..models import Job
from ..textutil import html_to_text, parse_iso


class Comeet:
    """https://www.comeet.co/careers-api/2.0/company/{uid}/positions?token={token}&details=true
    Needs both `uid` and `token`; both appear in the Comeet embed snippet of the company's own
    careers page (discover.py extracts them). `time_updated` is an update time, not a first publication."""

    name = "comeet"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        data = self.http.get_json(
            f"https://www.comeet.co/careers-api/2.0/company/{c['uid']}/positions",
            params={"token": c["token"], "details": "true"},
        )
        if not isinstance(data, list):
            raise ValueError("unexpected Comeet payload")
        out = []
        for p in data:
            uid = p.get("uid")
            if not uid:
                continue
            loc = p.get("location") or {}
            # the location's name may be an office or brand ("ProgrammaticX" at 44 Ventures), so the city and
            # country are added when the name does not already say them
            country = {"IL": "Israel"}.get(loc.get("country") or "", loc.get("country") or "")
            location = loc.get("name") or ""
            for x in (loc.get("city"), country):
                if x and x.lower() not in location.lower():
                    location = f"{location}, {x}" if location else x
            parts = []
            for d in p.get("details") or []:
                parts.append(f"{d.get('name', '')}\n{html_to_text(d.get('value'))}")
            exp = p.get("experience_level") or ""
            wt = (p.get("workplace_type") or "").lower()
            out.append(Job(
                company_id=c["id"], company=c["name"], job_id=str(uid),
                title=(p.get("name") or "").strip(),
                # url_active_page can be the company's general careers page when the job is not on its site
                # (Team8 "Cyber Stealth Startup - AI Engineer" -> team8.vc/careers/); url_detected_page is set
                # only when Comeet found the job's own page there. Otherwise Comeet's page for the job.
                url=p.get("url_detected_page") or p.get("url_comeet_hosted_page") or p.get("url_active_page")
                or p.get("position_url") or "",
                location=location or "", description="\n".join(parts),
                posted_at=parse_iso(p.get("time_updated")), date_kind="updated", date_source="comeet.time_updated",
                remote=True if wt == "remote" else None,
                employment=p.get("employment_type") or "", level=exp, source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
