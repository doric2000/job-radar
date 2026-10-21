from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ISO = "%Y-%m-%dT%H:%M:%SZ"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(ISO)


def from_iso(s: str) -> datetime:
    return datetime.strptime(s, ISO).replace(tzinfo=timezone.utc)


class State:
    """Everything the bot remembers. Plain JSON, safe to keep in a public repo:
    it holds only public job ids/titles and timestamps, no personal data."""

    def __init__(self, data: Optional[dict] = None):
        self.d = data or {"version": 1, "companies": {}, "meta": {}}
        self.d.setdefault("companies", {})
        self.d.setdefault("meta", {})

    @classmethod
    def load(cls, path: str | Path) -> "State":
        p = Path(path)
        if p.exists():
            try:
                return cls(json.loads(p.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                pass
        return cls()

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(p)

    # -- companies ----------------------------------------------------------------
    def company(self, cid: str) -> Optional[dict]:
        return self.d["companies"].get(cid)

    def ensure_company(self, cid: str, now: datetime) -> dict:
        c = self.d["companies"].get(cid)
        if c is None:
            c = {"first_scan": iso(now), "last_ok": None, "fail_streak": 0, "last_error": "", "jobs": {}}
            self.d["companies"][cid] = c
        return c

    def mark_ok(self, cid: str, now: datetime, present_ids: set[str]) -> None:
        # Timestamps are refreshed lazily so an unchanged scan leaves state.json byte-identical
        # (the workflow then skips the commit instead of pushing every 5 minutes).
        c = self.ensure_company(cid, now)
        if not c.get("last_ok") or now - from_iso(c["last_ok"]) > timedelta(hours=1):
            c["last_ok"] = iso(now)
        c["fail_streak"], c["last_error"] = 0, ""
        for jid in present_ids:
            j = c["jobs"].get(jid)
            if j and now - from_iso(j["ls"]) > timedelta(hours=6):
                j["ls"] = iso(now)

    def mark_fail(self, cid: str, now: datetime, err: str) -> None:
        c = self.d["companies"].get(cid)
        if c is None:
            # keep first_scan unset-ish: a company that never succeeded is still "first scan" later
            c = {"first_scan": None, "last_ok": None, "fail_streak": 0, "last_error": "", "jobs": {}}
            self.d["companies"][cid] = c
        c["fail_streak"] += 1
        c["last_error"] = err[:160]

    def is_first_scan(self, cid: str) -> bool:
        c = self.d["companies"].get(cid)
        return c is None or c.get("first_scan") is None or c.get("last_ok") is None

    def record(self, cid: str, now: datetime, job_id: str, title: str, alerted: bool, note: str) -> None:
        c = self.ensure_company(cid, now)
        if c.get("first_scan") is None:
            c["first_scan"] = iso(now)
        c["jobs"][job_id] = {"t": title[:70], "fs": iso(now), "ls": iso(now), "a": 1 if alerted else 0, "r": note[:60]}

    def forget_rejections(self, since: datetime, notes: str, removed: list | None = None) -> int:
        """Drop jobs rejected since `since` whose reject note matches the regex `notes`, so the next scan
        re-evaluates them under changed filters. Only jobs that appeared after the company's first scan
        are dropped: jobs recorded by the baseline were already open, and must not come back as new."""
        cut, rx, n = iso(since), re.compile(notes, re.I), 0
        for cid, c in self.d["companies"].items():
            first = c.get("first_scan") or ""
            for jid, j in list(c["jobs"].items()):
                fs = j.get("fs", "")
                if not j.get("a") and fs >= cut and fs > first and rx.search(j.get("r", "")):
                    del c["jobs"][jid]
                    n += 1
                    if removed is not None:
                        removed.append((cid, jid, j.get("t", "")))
        return n

    # -- cross-source dedupe ---------------------------------------------------------
    def was_alerted(self, key: str) -> bool:
        return key in self.d["meta"].setdefault("alerted", {})

    def add_alerted(self, key: str, now: datetime) -> None:
        self.d["meta"].setdefault("alerted", {})[key] = iso(now)

    # -- housekeeping ----------------------------------------------------------------
    def prune(self, now: datetime, job_days: int = 45, alert_days: int = 30) -> None:
        cut = iso(now - timedelta(days=job_days))
        for c in self.d["companies"].values():
            c["jobs"] = {k: v for k, v in c["jobs"].items() if v.get("ls", "") >= cut}
        cut2 = iso(now - timedelta(days=alert_days))
        al = self.d["meta"].get("alerted", {})
        self.d["meta"]["alerted"] = {k: v for k, v in al.items() if v >= cut2}
