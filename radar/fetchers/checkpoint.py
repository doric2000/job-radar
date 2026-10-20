from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Job

BASE = "https://careers.checkpoint.com/index.php"
# the search returns an empty list to non-browser user agents
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
    "Referer": "https://careers.checkpoint.com/",
}


class CheckPoint:
    """careers.checkpoint.com: a server-rendered PHP/Solr search, 10 positions per page (`start`),
    filtered with fa[]=country_s:Israel. The list has no dates, so jobs are dated 'unknown' and only
    alert once the company baseline exists (i.e. when they appear after the first scan)."""

    name = "checkpoint"

    def __init__(self, http):
        self.http = http

    def list_jobs(self, c: dict) -> list[Job]:
        out: dict[str, Job] = {}
        start = 0
        while start < int(c.get("max_jobs", 500)):
            html = self.http.get_text(BASE, params={"m": "cpcareers", "a": "search",
                                                    "fa[]": f"country_s:{c.get('country', 'Israel')}", "start": start},
                                      headers=HEADERS)
            new = 0
            for pos in BeautifulSoup(html, "html.parser").select("div.position"):
                link = next((a for a in pos.find_all("a", href=True)
                             if "joborderid=" in a["href"] and not a.find_parent(class_="shareMenu")), None)
                if link is None:
                    continue
                jid = re.search(r"joborderid=(\d+)", link["href"]).group(1)
                if jid in out:
                    continue
                info = [p.get_text(" ", strip=True) for p in pos.select(".posInfo p")]
                parts = [x.strip() for x in info[1].split("|")] if len(info) > 1 else []
                out[jid] = Job(
                    company_id=c["id"], company=c["name"], job_id=jid, title=link.get_text(" ", strip=True),
                    url=f"{BASE}?m=cpcareers&a=show&joborderid={jid}",
                    location=(info[0] if info else "").replace("Israel:", "").strip() + ", Israel",
                    employment=parts[1] if len(parts) > 1 else "", source=self.name,
                )
                new += 1
            if not new:
                break
            start += 10
        return list(out.values())

    def enrich(self, job: Job, c: dict) -> Job:
        soup = BeautifulSoup(self.http.get_text(job.url, headers=HEADERS), "html.parser")
        body = soup.select_one("#pageBody")
        if body is None:
            raise ValueError("Check Point job page without #pageBody")
        for junk in body.select("script, style, .shareMenu, .icons-position-container"):
            junk.decompose()
        job.description = body.get_text("\n", strip=True)
        return job
