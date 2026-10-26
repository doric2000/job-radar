from __future__ import annotations

import html
import re
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from ..models import Job
from ..textutil import html_to_text


class Rss:
    """Career sites whose job post type has an RSS feed but no REST API (Log-On:
    https://b.log-on.com/feed/?post_type=job, 10 items per page, newest first, &paged=N).
    Items carry title, link, guid (?p=ID) and pubDate (publication time). The feed has no job text,
    so enrich() reads the job page and takes `desc_selector` (e.g. 'div.job').
    Config: feed_url, pages (default 3), desc_selector, location (default 'Israel')."""

    name = "rss"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        out: dict[str, Job] = {}
        sep = "&" if "?" in c["feed_url"] else "?"
        for page in range(1, int(c.get("pages", 3)) + 1):
            try:
                xml = self.http.get_text(c["feed_url"] + (f"{sep}paged={page}" if page > 1 else ""))
            except Exception:  # noqa: BLE001 - WordPress answers 404 past the last page
                if page == 1:
                    raise
                break
            items = re.findall(r"<item>(.*?)</item>", xml, re.S)
            for it in items:
                tag = lambda t: html.unescape(m.group(1).strip()) if (m := re.search(rf"<{t}[^>]*>(.*?)</{t}>", it, re.S)) else ""  # noqa: E731
                link, guid = tag("link"), tag("guid")
                jid = (m.group(1) if (m := re.search(r"[?&]p=(\d+)", guid)) else link.rstrip("/").rsplit("/", 1)[-1])
                try:
                    when = parsedate_to_datetime(tag("pubDate"))
                except (TypeError, ValueError):
                    when = None
                out[jid] = Job(
                    company_id=c["id"], company=c["name"], job_id=jid, title=tag("title"), url=link,
                    location=c.get("location", "Israel"), posted_at=when,
                    date_kind="published" if when else "unknown", date_source="rss.pubDate" if when else "",
                    source=self.name,
                )
            if len(items) < 10:
                break
        return list(out.values())

    def enrich(self, job: Job, c: dict) -> Job:
        soup = BeautifulSoup(self.http.get_text(job.url), "html.parser")
        body = soup.select_one(c.get("desc_selector", "article")) or soup.select_one("main")
        job.description = html_to_text(str(body)) if body else ""
        if not job.description:
            raise ValueError("job page without a description")
        return job
