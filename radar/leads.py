from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .models import Job
from .textutil import parse_iso

_URL = re.compile(r"https?://[^\s<>\"')]+")


class TgChannel:
    """Reads the PUBLIC web preview of a Telegram channel (https://t.me/s/<handle>): no login, no API key.
    These are *leads*, not source-of-truth postings: the message time is not the job's publication time
    (date_kind='message'), and the message usually points at an original posting that should be opened."""

    name = "tgchannel"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        handle = c["token"]
        html = self.http.get_text(f"https://t.me/s/{handle}")
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for wrap in soup.select("div.tgme_widget_message"):
            post = wrap.get("data-post", "")  # "handle/123"
            if "/" not in post:
                continue
            body = wrap.select_one("div.tgme_widget_message_text")
            if body is None:
                continue
            for br in body.find_all("br"):
                br.replace_with("\n")
            text = re.sub(r"[ \t]+", " ", body.get_text()).strip()
            if not text:
                continue
            link = next((a.get("href") for a in body.find_all("a") if (a.get("href") or "").startswith("http")), None)
            if not link:
                m = _URL.search(text)
                link = m.group(0) if m else f"https://t.me/{post}"
            t = wrap.select_one("a.tgme_widget_message_date time")
            when = parse_iso(t.get("datetime")) if t is not None else None
            one_line = re.sub(r"\s+", " ", text)
            out.append(Job(
                company_id=c["id"], company=f"טלגרם · {handle}", job_id=post.split("/")[-1],
                title=one_line[:300], url=link, location=one_line[:400], description=text,
                posted_at=when, date_kind="message", date_source="telegram.message_time", source=self.name,
            ))
        return out

    def enrich(self, job: Job, c: dict) -> Job:
        return job
