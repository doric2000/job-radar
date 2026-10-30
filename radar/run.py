"""Scan loop.  python -m radar.run [--dry-run] [--all] [--only id,id] [--healthcheck]"""
from __future__ import annotations

import argparse
import html
import queue
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import feedback
from .config import load_config
from .fetchers import FETCHERS
from .filters import FILTERS_VERSION, RECHECK_NOTES, Classifier, _any
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
            extra.append({**li, "id": "linkedin", "name": "LinkedIn", "ats": "linkedin", "cat": "lead",
                          "recheck_ids": self.state.d["meta"].get("li_recheck", [])})
        return self.companies + extra

    # ---------------------------------------------------------------- one company
    def scan_source(self, c: dict, emit) -> None:
        """Scans one source and emits its results as they come. A fetcher with split() (LinkedIn: one part
        per query) emits one result per part, so its alerts go out without waiting for the remaining parts."""
        fetcher = self.fetchers.get(c["ats"])
        split = getattr(fetcher, "split", None)
        parts = split(c) if split else [c]
        first, seen, started, read = self.state.is_first_scan(c["id"]), set(), time.monotonic(), 0
        for i, part in enumerate(parts):
            res = self.scan_company(part, first=first, seen=seen)
            res["c"], res["last"] = c, i == len(parts) - 1
            if res["ok"]:
                read += 1
            elif read:
                # keep what the earlier parts found; say where and why the source stopped
                print(f"{c['name']}: stopped at part {i + 1}/{len(parts)}: {res['error']}")
                res.update(ok=True, error="", last=True)
            emit(res)
            if res["last"] or not res["ok"]:
                break
        if split:
            print(f"{c['name']}: {read}/{len(parts)} parts read in {time.monotonic() - started:.0f}s,"
                  f" rate-limited {getattr(fetcher, 'rate_limited', 0)} time(s)")

    def scan_company(self, c: dict, first: bool | None = None, seen: set | None = None) -> dict:
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
        first = self.state.is_first_scan(c["id"]) if first is None else first
        res["first"] = first
        res["present"] = {j.job_id for j in jobs}
        sc = self.cfg["scan"]
        seen = set() if seen is None else seen  # shared by the parts of a split source (a job can match two queries)
        for j in jobs:
            if j.job_id in known or j.job_id in seen:
                continue
            seen.add(j.job_id)
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
        # Results are handled (state + alerts) on this thread as each source finishes, so a job found by a
        # fast board is sent at once instead of waiting for the slowest source (LinkedIn takes minutes).
        q: queue.Queue = queue.Queue()

        def work(c):
            try:
                self.scan_source(c, q.put)
            except Exception as e:  # noqa: BLE001 - one broken source must never stop the run
                q.put({"c": c, "ok": False, "error": f"{e.__class__.__name__}: {e}"[:160], "items": [], "last": True})
            finally:
                q.put(None)

        alerts: list[tuple[Job, Verdict, dict]] = []
        errors: list[tuple[str, str, int]] = []
        self._sent_count, self._overflow = 0, 0
        ok = new_jobs = 0
        with ThreadPoolExecutor(max_workers=self.cfg["scan"]["threads"]) as ex:
            for c in todo:
                ex.submit(work, c)
            pending = len(todo)
            while pending:
                r = q.get()
                if r is None:
                    pending -= 1
                    continue
                c = r["c"]
                new_jobs += len(r["items"])
                if not r["ok"]:
                    self.state.mark_fail(c["id"], self.now, r["error"])
                    errors.append((c["name"], r["error"], self.state.company(c["id"])["fail_streak"]))
                    continue
                batch = []
                for j, v, alert, note in r["items"]:
                    if alert and self.state.was_alerted(dedupe_key(j)):
                        alert, note = False, "dup"
                    self.state.record(c["id"], self.now, j.job_id, j.title, alert, note or "ok")
                    if alert:
                        self.state.add_alerted(dedupe_key(j), self.now)
                        batch.append((j, v, c))
                self.state.ensure_company(c["id"], self.now)
                self.state.mark_ok(c["id"], self.now, r["present"])
                if r.get("last", True):
                    ok += 1
                    if c["id"] == "linkedin":
                        self.state.d["meta"].pop("li_recheck", None)
                batch.sort(key=lambda a: (TIER_RANK.get(a[1].tier, 9), REGION_RANK.get(a[1].region, 9)))
                self._notify(batch)
                alerts += batch

        if self._overflow and not self.dry_run and self.notifier:
            self.notifier.send(f"➕ עוד {self._overflow} משרות מתאימות בריצה הזו. פתח את state/ או הפעל ריצה ידנית.")
        alerts.sort(key=lambda a: (TIER_RANK.get(a[1].tier, 9), REGION_RANK.get(a[1].region, 9), a[2].get("tier", 2)))
        self.state.prune(self.now)
        return {"scanned": len(todo), "ok": ok, "errors": errors, "alerts": alerts, "new_jobs": new_jobs}

    # ---------------------------------------------------------------- notify
    def _notify(self, alerts) -> None:
        """Sends one source's alerts; the per-run cap counts across sources, the rest become one summary line."""
        room = max(0, self.cfg["notify"]["max_alerts_per_run"] - self._sent_count)
        self._overflow += max(0, len(alerts) - room)
        self._sent_count += min(room, len(alerts))
        for j, v, c in alerts[:room]:
            self._send_alert(j, v, c)

    def _send_alert(self, j: Job, v: Verdict, c: dict) -> None:
        text = format_alert(j, v, c, self.now, self.cfg["timezone"])
        if self.dry_run or self.notifier is None:
            print("----- ALERT (not sent) -----\n" + text)
        else:
            sid = feedback.sent_id(j)
            mid = self.notifier.send(text)
            feedback.record_sent(self.state.d["meta"], sid, j, v, mid, self.now)
            time.sleep(0.4)

    # ---------------------------------------------------------------- backlog
    def backlog(self) -> list[tuple[Job, Verdict, dict]]:
        """Jobs recorded by a company's first (baseline) scan are never alerted, so postings that were
        already open when the bot started, or that only fit after a rule change, stay silent. This
        re-classifies them under the current rules and returns the ones that fit (sent as one digest)."""
        def one(c):
            st = self.state.company(c["id"])
            if not st or not st.get("first_scan"):
                return []
            fetcher, out = self.fetchers.get(c["ats"]), []
            try:
                jobs = fetcher.list_jobs(c)
            except Exception as e:  # noqa: BLE001
                print(f"backlog: {c['name']} skipped: {e.__class__.__name__}: {e}"[:200])
                return []
            for j in jobs:
                k = st["jobs"].get(j.job_id)
                if not k or k.get("a") or k.get("fs") != st["first_scan"] or k.get("r") in ("dup", "stale"):
                    continue
                if not self.clf.stage1(j).accept:
                    continue
                try:
                    if not j.description:
                        j = fetcher.enrich(j, c)
                    v = self.clf.classify(j)
                except Exception as e:  # noqa: BLE001
                    print(f"backlog: {c['name']} / {j.title}: {e.__class__.__name__}: {e}"[:200])
                    continue
                if v.accept:  # still listed = still open, however long ago it was first published
                    out.append((j, v, c))
            return out

        pool = [c for c in self.companies if c.get("ats") and c.get("cat") != "lead"]
        with ThreadPoolExecutor(max_workers=self.cfg["scan"]["threads"]) as ex:
            found = [x for r in ex.map(one, pool) for x in r]
        fresh, seen = [], set()
        for j, v, c in found:
            self.state.company(c["id"])["jobs"][j.job_id].update({"a": 1, "r": "backlog"})
            same = (norm(j.company), norm(j.title))  # one line per role, not per location
            if self.state.was_alerted(dedupe_key(j)) or same in seen:
                continue
            seen.add(same)
            self.state.add_alerted(dedupe_key(j), self.now)
            fresh.append((j, v, c))
        fresh.sort(key=lambda a: (TIER_RANK.get(a[1].tier, 9), a[0].company))
        return fresh

    def send_backlog(self, items) -> None:
        # explicit junior/graduate/intern titles get a full alert (a line in a long list is easy to miss:
        # Elad's "Full Stack Junior" was line 15 of 28); the rest go in one list
        full = [x for x in items if _any(self.clf.entry, x[0].title)]
        for j, v, c in full:
            self._send_alert(j, v, c)
        items = [x for x in items if x not in full]
        if not items:
            return
        e = html.escape
        head = f"📚 משרות שכבר היו פתוחות כשהבוט התחיל ומתאימות לכללים הנוכחיים ({len(items)}):"
        def age(j):
            if not j.posted_at or (self.now - j.posted_at).days < 30:
                return ""
            return f" · פתוחה {(self.now - j.posted_at).days // 30} חודשים"

        lines = [f'• <a href="{e(j.url, quote=True)}">{e(j.title[:80])}</a> · {e(j.company[:30])}'
                 + (f" · {e(v.reasons[0][:40])}" if v.reasons else "") + age(j) for j, v, _ in items]
        chunks, cur = [], [head]
        for ln in lines:
            if len("\n".join(cur + [ln])) > 3800:
                chunks.append(cur)
                cur = ["📚 (המשך)"]
            cur.append(ln)
        chunks.append(cur)
        for ch in chunks:
            if self.dry_run or self.notifier is None:
                print("----- BACKLOG (not sent) -----\n" + "\n".join(ch))
            else:
                self.notifier.send("\n".join(ch))
                time.sleep(0.4)

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
    ap.add_argument("--backlog", action="store_true", help="one digest of already-open jobs that fit the current rules")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    companies = load_registry(a.companies, a.resolved)
    state = State.load(a.state)
    if state.d["meta"].get("filters_version") != FILTERS_VERSION:
        removed: list = []
        n = state.forget_rejections(datetime.now(timezone.utc) - timedelta(hours=72), RECHECK_NOTES, removed)
        # LinkedIn jobs leave the last-hour search window, so they are re-fetched by id on the next scan
        # (only those whose stored title now passes the title stage, to keep the next run short)
        clf = Classifier(cfg)
        state.d["meta"]["li_recheck"] = [
            jid for cid, jid, title in removed
            if cid == "linkedin" and clf.stage1(Job(company_id=cid, company="", job_id=jid, title=title, url="",
                                                    location="Israel")).accept][:40]
        state.d["meta"]["filters_version"] = FILTERS_VERSION
        print(f"filters changed: re-evaluating {n} recent rejections")
    notifier = Telegram.from_env() if cfg["notify"]["telegram"] else None
    if notifier is None and not a.dry_run and not a.healthcheck:
        print("WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - alerts will only be printed", file=sys.stderr)
    radar = Radar(cfg, companies, state, Http(), notifier, dry_run=a.dry_run)
    only = {x for x in a.only.split(",") if x} or None

    if a.healthcheck:
        return healthcheck(radar, only)
    if notifier is not None and not a.dry_run:
        n = feedback.collect(state.d["meta"], notifier, radar.now)
        if n:
            print(f"feedback: {n} new item(s)")
        removed = feedback.remove_old_buttons(state.d["meta"], notifier)
        if removed:
            print(f"feedback: removed buttons from {removed} old alert(s)")
    if a.backlog:
        items = radar.backlog()
        radar.send_backlog(items)
        print(f"backlog: {len(items)} job(s)")
        if not a.dry_run:
            state.save(a.state)
        return 0

    run_index = int(time.time() // (60 * cfg["scan"]["run_interval_minutes"]))
    summary = radar.run(run_index, force_all=a.all, only=only)
    radar.maybe_digest(summary)
    print(f"scanned={summary['scanned']} ok={summary['ok']} errors={len(summary['errors'])} "
          f"new_jobs={summary['new_jobs']} alerts={len(summary['alerts'])}")
    for name, err, streak in summary["errors"][:15]:
        print(f"  ! {name} (x{streak}): {err}")
    feedback.prune(state.d["meta"], radar.now)
    if not a.dry_run:
        state.save(a.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
