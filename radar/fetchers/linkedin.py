from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..http import HttpError
from ..models import Job
from ..textutil import html_to_text

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
# LinkedIn's guest endpoints reject obvious bot user agents
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
_AGO = re.compile(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", re.I)
_UNIT = {"minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400}


class Blocked(Exception):
    """LinkedIn answered 429/999: stop all LinkedIn requests for the rest of this run."""


def parse_ago(text: str, date_attr: str, now: datetime) -> tuple[datetime | None, str]:
    """'26 minutes ago' / '3 hours ago' are precise enough to call 'published'; days and longer
    are day precision ('relative'). Falls back to the card's datetime="YYYY-MM-DD"."""
    m = _AGO.search(text or "")
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        when = now - timedelta(seconds=n * _UNIT[unit])
        return when, "published" if unit in ("minute", "hour") else "relative"
    if re.search(r"just now|moments? ago", text or "", re.I):
        return now, "published"
    try:
        return datetime.strptime(date_attr, "%Y-%m-%d").replace(tzinfo=timezone.utc), "relative"
    except (TypeError, ValueError):
        return None, "unknown"


class LinkedIn:
    """LinkedIn's public, logged-out job search (the same endpoint its public /jobs pages load).
    No account and no cookies are used. One pseudo-company runs every configured query, newest first.

    LinkedIn rate-limits these endpoints hard (HTTP 429 after a burst), so every request is spaced by
    `gap_seconds` across threads, a 429 gets one long pause and retry, and a second 429 aborts LinkedIn
    for the run (jobs already collected are still returned). Its own experience filter (f_E) is not
    reliable - it labels Staff roles 'Associate' - so it only narrows the search; the Classifier decides."""

    name = "linkedin"
    _lock = threading.Lock()
    _next = 0.0

    def __init__(self, http):
        self.http = http
        self.blocked = False
        self.rate_limited = 0  # 429/999 answers this run (logged by the run)

    def _get(self, url: str, gap: float, cooldown: float) -> str:
        if self.blocked:
            raise Blocked("LinkedIn rate limit hit earlier in this run")
        for attempt in range(2):
            with LinkedIn._lock:
                now = time.monotonic()
                slot = max(now, LinkedIn._next)
                LinkedIn._next = slot + gap
            if slot > now:
                time.sleep(slot - now)
            try:
                return self.http.get_text(url, headers=HEADERS)
            except HttpError as e:
                if e.status not in (429, 999):
                    raise
                self.rate_limited += 1
                if attempt == 0:
                    time.sleep(cooldown)
        self.blocked = True
        raise Blocked("LinkedIn rate limit (HTTP 429/999)")

    def split(self, c: dict) -> list[dict]:
        """One part per query (then the re-checks), scanned in order, so each query's alerts go out as soon
        as that query is read instead of after all of them (a full pass takes ~3-4 minutes)."""
        parts = [{**c, "queries": [q], "recheck_ids": []} for q in c.get("queries") or []]
        if c.get("recheck_ids"):
            parts.append({**c, "queries": []})
        return parts or [c]

    def list_jobs(self, c: dict) -> list[Job]:
        gap, cooldown = float(c.get("gap_seconds", 5)), float(c.get("cooldown_seconds", 25))
        now = datetime.now(timezone.utc)
        out: dict[str, Job] = {}
        for q in c["queries"]:
            params = {"keywords": q["keywords"], "geoId": c.get("geo_id", "101620260"), "f_TPR": c.get("time_window", "r86400"),
                      "sortBy": "DD"}
            for k in ("f_E", "f_WT", "f_JT"):
                if q.get(k):
                    params[k] = q[k]
            for page in range(int(q.get("pages", c.get("pages", 1)))):
                try:
                    html = self._get(f"{SEARCH}?{urlencode({**params, 'start': page * 10})}", gap, cooldown)
                except Blocked:
                    if out:
                        return list(out.values())
                    raise
                cards = BeautifulSoup(html, "html.parser").select("div.base-card")
                for card in cards:
                    m = re.search(r"jobPosting:(\d+)", card.get("data-entity-urn", ""))
                    if not m or m.group(1) in out:
                        continue
                    jid = m.group(1)
                    txt = lambda sel: card.select_one(sel).get_text(" ", strip=True) if card.select_one(sel) else ""  # noqa: E731
                    t = card.select_one("time")
                    when, kind = parse_ago(t.get_text(strip=True) if t else "", t.get("datetime") if t else "", now)
                    out[jid] = Job(
                        company_id=c["id"], company=txt(".base-search-card__subtitle") or "LinkedIn", job_id=jid,
                        title=txt(".base-search-card__title"), url=f"https://www.linkedin.com/jobs/view/{jid}/",
                        location=txt(".job-search-card__location"), posted_at=when, date_kind=kind,
                        date_source="linkedin.listdate", source=self.name,
                    )
                if len(cards) < 10:
                    break
        # jobs rejected under older rules have usually left the last-hour window: fetch them by id
        for jid in c.get("recheck_ids") or []:
            if jid in out:
                continue
            try:
                out[jid] = self.fetch_one(jid, c, now)
            except Blocked:
                break
            except Exception:  # noqa: BLE001 - closed or removed posting
                continue
        return list(out.values())

    def fetch_one(self, jid: str, c: dict, now: datetime) -> Job:
        """A single posting from its detail page (title, company, location, date and description)."""
        html = self._get(DETAIL.format(id=jid), float(c.get("gap_seconds", 5)), float(c.get("cooldown_seconds", 25)))
        soup = BeautifulSoup(html, "html.parser")
        txt = lambda sel: soup.select_one(sel).get_text(" ", strip=True) if soup.select_one(sel) else ""  # noqa: E731
        title = txt("h2.top-card-layout__title") or txt(".topcard__title")
        if not title:
            raise ValueError("LinkedIn posting without a title (closed?)")
        when, kind = parse_ago(txt(".posted-time-ago__text"), "", now)
        job = Job(company_id=c["id"], company=txt("a.topcard__org-name-link") or txt(".topcard__flavor") or "LinkedIn",
                  job_id=jid, title=title, url=f"https://www.linkedin.com/jobs/view/{jid}/",
                  location=txt(".topcard__flavor--bullet"), posted_at=when, date_kind=kind,
                  date_source="linkedin.detail", source=self.name)
        return self._fill_detail(job, soup)

    def enrich(self, job: Job, c: dict) -> Job:
        html = self._get(DETAIL.format(id=job.job_id), float(c.get("gap_seconds", 5)), float(c.get("cooldown_seconds", 25)))
        return self._fill_detail(job, BeautifulSoup(html, "html.parser"))

    def _fill_detail(self, job: Job, soup) -> Job:
        body = soup.select_one(".show-more-less-html__markup")
        job.description = html_to_text(str(body)) if body else ""
        for li in soup.select("li.description__job-criteria-item"):
            h, v = li.select_one("h3"), li.select_one("span")
            if h and v and h.get_text(strip=True).lower() == "employment type":
                job.employment = v.get_text(strip=True)
        # LinkedIn's "Seniority level" is deliberately not copied into job.level: posters mislabel it often
        if not job.description:
            raise ValueError("LinkedIn job detail without a description")
        return job
