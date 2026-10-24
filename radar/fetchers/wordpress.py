from __future__ import annotations

import html

from ..models import Job
from ..textutil import html_to_text, parse_iso


class WordPress:
    """Career sites that publish jobs as a WordPress post type, readable through the core REST API:
    https://{host}/wp-json/wp/v2/{rest_base}?per_page=100&page=N  (e.g. Comblack 'careers', High Sec Labs 'jobs').
    Posts carry title, content and date_gmt (publication time), so no detail request is needed.
    Location is rarely structured; `location` from the company config (default 'Israel') is used."""

    name = "wordpress"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        out: dict[str, Job] = {}
        for page in range(1, int(c.get("max_pages", 10)) + 1):
            try:
                posts = self.http.get_json(f"https://{c['host']}/wp-json/wp/v2/{c['rest_base']}",
                                           params={"per_page": 100, "page": page, "orderby": "date", "order": "desc"})
            except Exception:  # noqa: BLE001 - WordPress answers 400 past the last page
                if page == 1:
                    raise
                break
            if not isinstance(posts, list) or not posts:
                break
            # dates: false - the site re-publishes every post at once (UCL: all 101 jobs dated the same minute)
            dated = c.get("dates", True)
            for p in posts:
                jid = str(p.get("id"))
                when = parse_iso((p.get("date_gmt") or "") + "Z" if p.get("date_gmt") else None) if dated else None
                out[jid] = Job(
                    company_id=c["id"], company=c["name"], job_id=jid,
                    title=html.unescape((p.get("title") or {}).get("rendered", "")).strip(),
                    url=p.get("link", ""), location=c.get("location", "Israel"),
                    description=html_to_text((p.get("content") or {}).get("rendered")),
                    posted_at=when, date_kind="published" if when else "unknown",
                    date_source="wordpress.date_gmt" if when else "", source=self.name,
                )
            if len(posts) < 100:
                break
        return list(out.values())

    def enrich(self, job: Job, c: dict) -> Job:
        return job
