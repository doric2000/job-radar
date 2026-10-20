"""Scan loop.  python -m radar.run [--dry-run] [--all] [--only id,id] [--healthcheck]"""
from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import load_config
from .fetchers import FETCHERS
from .filters import FILTERS_VERSION, RECHECK_NOTES, Classifier
from .http import Http, HttpError
from .leads import TgChannel
from .models import Job, Verdict
from .notify import Telegram, format_alert
from .registry import load_registry
from .state import State
from .textutil import norm

DATED_KINDS = {"published", "created", "relative", "message"}
TIER_RANK = {"A": 0, "B": 1, "C": 2}
REGION_RANK = {"israel": 0, "remote": 1, "relocation": 2}


def dedupe_key(job: Job) -> str:
    first_loc = (job.location or "").split(",")[0].split("|")[0]
    # LinkedIn writes "Tel Aviv-Yafo" where company boards write "Tel Aviv"
    first_loc = re.sub(r"[\s-]*(yafo|jaffa)\s*$", "", first_loc, flags=re.I)
    return f"{norm(job.company)}|{norm(job.title)[:80]}|{norm(first_loc)[:20]}"


class Radar:
    def __init__(self, cfg: dict, companies: list[dict], state: State, http: Http, notifier=None, now=None, dry_run=False):
        self.cfg, self.companies, self.state, self.http = cfg, companies, state, http
        self.notifier, self.dry_run = notifier, dry_run
        self.clf = Classifier(cfg)
        self.now = now or datetime.now(timezone.utc)
        self.fetchers = {k: cls(http) for k, cls in FETCHERS.items()}
        self.fetchers["tgchannel"] = TgChannel(http)

    # ---------------------------------------------------------------- scheduling
    def due(self, companies: list[dict], run_index: int, force_all: bool) -> list[dict]:
        every = self.cfg["scan"]["tier_every_n_runs"]
        out = []
        for c in companies:
            if not c.get("ats"):
                continue
            k = every.get(int(c.get("tier", 2)), 1)
            if force_all or run_index % max(1, k) == 0 or self.state.is_first_scan(c["id"]):
                out.append(c)
        return out

    def with_channels(self) -> list[dict]:
        extra = [{"id": f"tg-{h}", "name": f"טלגרם · {h}", "ats": "tgchannel", "token": h, "tier": 1, "cat": "lead"}
                 for h in self.cfg["leads"]["telegram_channels"]]
        li = self.cfg["leads"].get("linkedin") or {}
        if li.get("enabled"):
            extra.append({**li, "id": "linkedin", "name": "LinkedIn", "ats": "linkedin", "cat": "lead"})
        return self.companies + extra

    # ---------------------------------------------------------------- one company
    def scan_company(self, c: dict) -> dict:
        res = {"c": c, "ok": False, "error": "", "present": set(), "items": [], "n_jobs": 0}
        fetcher = self.fetchers.get(c["ats"])
        if fetcher is None:
            res["error"] = f"unknown ats {c['ats']}"
            return res
        try:
            jobs = fetcher.list_jobs(c)
        except Exception as e:  # noqa: BLE001 - one broken board must never stop the run
            res["error"] = f"{e.__class__.__name__}: {e}"[:160]
            return res
        res["ok"], res["n_jobs"] = True, len(jobs)
        st = self.state.company(c["id"])
        known = st["jobs"] if st else {}
        first = self.state.is_first_scan(c["id"])
        res["first"] = first
        res["present"] = {j.job_id for j in jobs}
        sc = self.cfg["scan"]
        for j in jobs:
            if j.job_id in known:
                continue
            v = self.clf.stage1(j)
            if v.accept and not j.description:
                try:
                    j = fetcher.enrich(j, c)
                except Exception:  # noqa: BLE001
                    continue  # not recorded -> retried on the next run
            if v.accept:
                try:
                    v = self.clf.classify(j)
                except Exception:  # noqa: BLE001 - one malformed job must not stop the whole run
                    continue  # not recorded -> retried on the next run
            alert, note = v.accept, v.reject_reason
            if alert:
                age_h = (self.now - j.posted_at).total_seconds() / 3600 if j.posted_at else None
                dated = j.date_kind in DATED_KINDS and age_h is not None
                if first and not (dated and age_h <= sc["baseline_alert_within_hours"]):
                    alert, note = False, "baseline"
                elif dated and age_h > sc["max_age_days"] * 24:
                    alert, note = False, "stale"
            res["items"].append((j, v, alert, note))
        return res

    # ---------------------------------------------------------------- whole run
    def run(self, run_index: int, force_all: bool = False, only: set[str] | None = None) -> dict:
        pool = self.with_channels()
        if only:
            pool = [c for c in pool if c["id"] in only]
        todo = self.due(pool, run_index, force_all)
        with ThreadPoolExecutor(max_workers=self.cfg["scan"]["threads"]) as ex:
            results = list(ex.map(self.scan_company, todo))

        alerts: list[tuple[Job, Verdict, dict]] = []
        errors: list[tuple[str, str, int]] = []
        for r in results:
            c = r["c"]
            if not r["ok"]:
                self.state.mark_fail(c["id"], self.now, r["error"])
                errors.append((c["name"], r["error"], self.state.company(c["id"])["fail_streak"]))
                continue
            for j, v, alert, note in r["items"]:
                if alert and self.state.was_alerted(dedupe_key(j)):
                    alert, note = False, "dup"
                self.state.record(c["id"], self.now, j.job_id, j.title, alert, note or "ok")
                if alert:
                    self.state.add_alerted(dedupe_key(j), self.now)
                    alerts.append((j, v, c))
            self.state.ensure_company(c["id"], self.now)
            self.state.mark_ok(c["id"], self.now, r["present"])

        alerts.sort(key=lambda a: (TIER_RANK.get(a[1].tier, 9), REGION_RANK.get(a[1].region, 9), a[2].get("tier", 2)))
        self._notify(alerts)
        self.state.prune(self.now)
        return {"scanned": len(todo), "ok": sum(r["ok"] for r in results), "errors": errors,
                "alerts": alerts, "new_jobs": sum(len(r["items"]) for r in results)}

    # ---------------------------------------------------------------- notify
    def _notify(self, alerts) -> None:
        cap = self.cfg["notify"]["max_alerts_per_run"]
        tz = self.cfg["timezone"]
        for j, v, c in alerts[:cap]:
            text = format_alert(j, v, c, self.now, tz)
            if self.dry_run or self.notifier is None:
                print("----- ALERT (not sent) -----\n" + text)
            else:
                self.notifier.send(text)
                time.sleep(0.4)
        if len(alerts) > cap:
            msg = f"➕ עוד {len(alerts) - cap} משרות מתאימות בריצה הזו. פתח את state/ או הפעל ריצה ידנית."
            if not self.dry_run and self.notifier:
                self.notifier.send(msg)

    def maybe_digest(self, summary: dict) -> None:
        """Once a day: proof of life + broken boards. Silent if everything is fine except the heartbeat."""
        n = self.cfg["notify"]
        local = self.now.astimezone(ZoneInfo(self.cfg["timezone"]))
        today = local.strftime("%Y-%m-%d")
        meta = self.state.d["meta"]
        if meta.get("last_digest") == today or local.hour < n["daily_digest_hour"]:
            return
        broken = [(name, err, s) for name, err, s in summary["errors"] if s >= 6]
        total = len(self.state.d["companies"])
        alive = sum(1 for c in self.state.d["companies"].values() if c.get("last_ok"))
        lines = [f"✅ הבוט פעיל · {today}", f"חברות במעקב: {alive}/{total} נסרקו בהצלחה לפחות פעם אחת"]
        if broken:
            lines.append("חברות שנכשלות ברצף (טוקן שגוי / החברה עברה מערכת?):")
            lines += [f"• {name}: {err[:70]}" for name, err, _ in broken[:12]]
        meta["last_digest"] = today
        if self.dry_run or self.notifier is None:
            print("----- DIGEST (not sent) -----\n" + "\n".join(lines))
        else:
            self.notifier.send("\n".join(lines), silent=True)


def healthcheck(radar: Radar, only: set[str] | None) -> int:
    """Run list_jobs once per resolved company and report per-ATS success + field coverage.
    Use after discovery to verify the fetchers against the live services."""
    stats: dict = {}
    for c in radar.with_channels():
        if not c.get("ats") or (only and c["id"] not in only):
            continue
        s = stats.setdefault(c["ats"], {"ok": 0, "fail": 0, "jobs": 0, "dated": 0, "loc": 0, "desc": 0, "errs": []})
        try:
            jobs = radar.fetchers[c["ats"]].list_jobs(c)
        except Exception as e:  # noqa: BLE001 - diagnostic tool
            s["fail"] += 1
            s["errs"].append(f"{c['name']}: {e.__class__.__name__}: {e}"[:140])
            continue
        s["ok"] += 1
        s["jobs"] += len(jobs)
        s["dated"] += sum(1 for j in jobs if j.posted_at)
        s["loc"] += sum(1 for j in jobs if j.location)
        s["desc"] += sum(1 for j in jobs if j.description)
    bad = 0
    for ats, s in sorted(stats.items()):
        n = max(1, s["jobs"])
        print(f"{ats:16s} boards ok={s['ok']} fail={s['fail']} jobs={s['jobs']} "
              f"with_date={s['dated'] * 100 // n}% with_location={s['loc'] * 100 // n}% with_description={s['desc'] * 100 // n}%")
        for e in s["errs"][:5]:
            print("   !", e)
        bad += s["fail"]
    if not stats:
        print("no resolved companies yet - run the discover workflow first")
    return 1 if bad and not any(s["ok"] for s in stats.values()) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--companies", default="companies.yaml")
    ap.add_argument("--resolved", default="data/resolved.json")
    ap.add_argument("--state", default="state/state.json")
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending, do not save state")
    ap.add_argument("--all", action="store_true", help="ignore tier schedule, scan everything")
    ap.add_argument("--only", default="", help="comma separated company ids")
    ap.add_argument("--healthcheck", action="store_true")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    companies = load_registry(a.companies, a.resolved)
    state = State.load(a.state)
    if state.d["meta"].get("filters_version") != FILTERS_VERSION:
        n = state.forget_rejections(datetime.now(timezone.utc) - timedelta(hours=72), RECHECK_NOTES)
        state.d["meta"]["filters_version"] = FILTERS_VERSION
        print(f"filters changed: re-evaluating {n} recent rejections")
    notifier = Telegram.from_env() if cfg["notify"]["telegram"] else None
    if notifier is None and not a.dry_run and not a.healthcheck:
        print("WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - alerts will only be printed", file=sys.stderr)
    radar = Radar(cfg, companies, state, Http(), notifier, dry_run=a.dry_run)
    only = {x for x in a.only.split(",") if x} or None

    if a.healthcheck:
        return healthcheck(radar, only)

    run_index = int(time.time() // (60 * cfg["scan"]["run_interval_minutes"]))
    summary = radar.run(run_index, force_all=a.all, only=only)
    radar.maybe_digest(summary)
    print(f"scanned={summary['scanned']} ok={summary['ok']} errors={len(summary['errors'])} "
          f"new_jobs={summary['new_jobs']} alerts={len(summary['alerts'])}")
    for name, err, streak in summary["errors"][:15]:
        print(f"  ! {name} (x{streak}): {err}")
    if not a.dry_run:
        state.save(a.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
