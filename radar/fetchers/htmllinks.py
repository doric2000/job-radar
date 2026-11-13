from __future__ import annotations

import re
from urllib.parse import urljoin

import soupsieve as sv
from bs4 import BeautifulSoup

from ..models import Job


class HtmlLinks:
    """Small career sites that list jobs as plain links: `list_url` + `link_pattern` (a regex on the href,
    whose first group is used as the job id). The title is the link text (the first non-empty one per job),
    falling back to the job page's <h1>. No dates, so new jobs alert once the baseline exists.
    `title_drop`: a CSS selector removed from the link before reading its text (Logica puts the
    category and area in <span class="metas"> inside the link).
    `card` + `card_title`: when the link text is only a button ("View Details", Moveo), the title is read
    from `card_title` inside the link's closest ancestor matching `card`."""

    name = "htmllinks"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        rx = re.compile(c["link_pattern"])
        soup = BeautifulSoup(self.http.get_text(c["list_url"]), "html.parser")
        out: dict[str, Job] = {}
        for a in soup.find_all("a", href=True):
            m = rx.search(a["href"])
            if not m:
                continue
            if c.get("title_drop"):
                for junk in a.select(c["title_drop"]):
                    junk.decompose()
            jid, text = m.group(1), a.get_text(" ", strip=True)
            if c.get("card"):
                box = next((p for p in a.parents if p.name and sv.match(c["card"], p)), None)
                el = box.select_one(c["card_title"]) if box else None
                text = el.get_text(" ", strip=True) if el else ""
            if jid in out:
                if text and not out[jid].title:
                    out[jid].title = text
                continue
            out[jid] = Job(company_id=c["id"], company=c["name"], job_id=jid, title=text,
                           url=urljoin(c["list_url"], a["href"]), location=c.get("location", "Israel"), source=self.name)
        return list(out.values())

    def enrich(self, job: Job, c: dict) -> Job:
        soup = BeautifulSoup(self.http.get_text(job.url), "html.parser")
        if not job.title and soup.find("h1"):
            job.title = soup.find("h1").get_text(" ", strip=True)
        body = soup.select_one(c.get("desc_selector", "main")) or soup.body
        for junk in body.select("script, style, nav, header, footer"):
            junk.decompose()
        # inline tags stay on their line: "<strong>3+ years</strong> of experience" is one requirement (Moveo)
        for tag in body.select("strong, b, em, i, span, a, u"):
            tag.unwrap()
        body.smooth()
        job.description = body.get_text("\n", strip=True)
        return job
