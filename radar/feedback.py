"""User feedback on alerts, for the twice-daily review.

Every alert is logged in state meta["sent"] under a short id and carries two Telegram buttons
(relevant / not relevant). Each scan reads the bot's pending updates: a button press is stored in
meta["feedback"][sid]; a text reply to an alert is stored there as a note; any other text message to
the bot goes to meta["notes"]. The state is in a public repo, so only job titles/links and the user's
verdicts are kept - never message metadata such as names or usernames."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from .models import Job, Verdict
from .state import iso

KEEP_DAYS = 30


def sent_id(job: Job) -> str:
    return hashlib.sha1(f"{job.company_id}:{job.job_id}".encode()).hexdigest()[:10]


def buttons(sid: str) -> dict:
    return {"inline_keyboard": [[{"text": "👍 רלוונטי", "callback_data": f"fb|{sid}|1"},
                                 {"text": "👎 לא רלוונטי", "callback_data": f"fb|{sid}|0"}]]}


def record_sent(meta: dict, sid: str, job: Job, v: Verdict, message_id, now: datetime) -> None:
    meta.setdefault("sent", {})[sid] = {
        "ts": iso(now), "t": job.title[:90], "co": job.company[:40], "url": job.url, "src": job.source,
        "cid": job.company_id, "tier": v.tier, "why": "; ".join(v.reasons + v.warnings)[:160],
        "years": v.req_years, "mid": message_id,
    }


def collect(meta: dict, tg, now: datetime) -> int:
    """Read pending bot updates once. Returns how many feedback items were stored."""
    updates = tg.get_updates(offset=meta.get("tg_offset", 0) + 1)
    if updates is None:
        return 0
    by_mid = {str(s.get("mid")): sid for sid, s in meta.get("sent", {}).items() if s.get("mid")}
    fb, n = meta.setdefault("feedback", {}), 0
    for u in updates:
        meta["tg_offset"] = max(meta.get("tg_offset", 0), int(u.get("update_id", 0)))
        cq = u.get("callback_query")
        if cq and str((cq.get("message") or {}).get("chat", {}).get("id")) == str(tg.chat_id):
            parts = (cq.get("data") or "").split("|")
            if len(parts) == 3 and parts[0] == "fb" and parts[1] in meta.get("sent", {}):
                good = parts[2] == "1"
                fb.setdefault(parts[1], {}).update({"v": 1 if good else 0, "ts": iso(now)})
                n += 1
                tg.answer_callback(cq.get("id"), "נרשם, תודה")
                tg.edit_buttons(cq["message"]["message_id"], {"inline_keyboard": [[{
                    "text": "✅ סומן רלוונטי" if good else "❌ סומן לא רלוונטי", "callback_data": cq["data"]}]]})
            continue
        msg = u.get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != str(tg.chat_id) or not msg.get("text"):
            continue
        text = msg["text"][:500]
        if text.startswith("/"):
            continue
        sid = by_mid.get(str((msg.get("reply_to_message") or {}).get("message_id")))
        if sid:
            fb.setdefault(sid, {}).update({"note": text, "ts": iso(now)})
        else:
            meta.setdefault("notes", []).append({"ts": iso(now), "text": text})
            meta["notes"] = meta["notes"][-100:]
        n += 1
    return n


def prune(meta: dict, now: datetime) -> None:
    cut = iso(now - timedelta(days=KEEP_DAYS))
    meta["sent"] = {k: v for k, v in meta.get("sent", {}).items() if v.get("ts", "") >= cut}
    meta["feedback"] = {k: v for k, v in meta.get("feedback", {}).items() if k in meta["sent"]}
