from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Job

BASE = "https://careers.eladsoft.com/jobs/"


class Elad:
    """careers.eladsoft.com (Elad Software, staffing for Israeli tech): a WordPress list of
    article.job-card, 10 per page via ?pg=N, not sorted by date and without dates, so every page is
    read each scan and new jobs alert once the baseline exists. All positions are in Israel; the
    card only carries a Hebrew region tag, so ', Israel' is appended for the location filter."""

    name = "elad"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        out: dict[str, Job] = {}
        for page in range(1, int(c.get("max_pages", 40)) + 1):
            html = self.http.get_text(BASE, params={"pg": page})
            new = 0
            for card in BeautifulSoup(html, "html.parser").select("article.job-card"):
                a = card.select_one("h3.job-title a[href]")
                m = re.search(r"/jobs/(\d+)", a["href"]) if a else None
                if not m or m.group(1) in out:
                    continue
                areas = [t.get_text(" ", strip=True) for t in card.select(".job-areas .job-tag")]
                out[m.group(1)] = Job(
                    company_id=c["id"], company=c["name"], job_id=m.group(1), title=a.get_text(" ", strip=True),
                    url=a["href"], location=", ".join(areas + ["Israel"]), source=self.name,
                )
                new += 1
            if not new:
                break
        return list(out.values())

    def enrich(self, job: Job, c: dict) -> Job:
        soup = BeautifulSoup(self.http.get_text(job.url), "html.parser")
        body = soup.select_one(".job-description") or soup.select_one("main")
        if body is None:
            raise ValueError("Elad job page without a description")
        job.description = body.get_text("\n", strip=True)
        return job
