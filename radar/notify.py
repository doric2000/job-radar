from __future__ import annotations

import html
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from .models import Job, Verdict

KIND_HE = {
    "published": "פורסמה", "created": "נוצרה", "updated": "עודכנה", "relative": "פורסמה (דיוק יומי)",
    "message": "הודעה בטלגרם", "unknown": "תאריך לא ידוע",
}
TIER_HE = {"A": "🟢 מתחילים במפורש", "B": "🟡 עד שנת ניסיון", "C": "🟠 עד שנתיים ניסיון"}
REGION_HE = {"israel": "ישראל", "remote": "מרחוק", "relocation": "חו״ל · רילוקיישן"}


def age_text(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return ""
    secs = (now - dt).total_seconds()
    if secs < 0:
        return "עכשיו"
    if secs < 3600:
        return f"לפני {max(1, int(secs // 60))} דק׳"
    if secs < 86400:
        return f"לפני {int(secs // 3600)} שע׳"
    return f"לפני {int(secs // 86400)} ימים"


def format_alert(job: Job, v: Verdict, company: dict, now: datetime, tz: str = "Asia/Jerusalem") -> str:
    e = html.escape
    star = " ⭐" if company.get("tier") == 1 and company.get("cat") != "lead" else ""
    lines = [f"🔔 <b>{e(job.title[:140])}</b>", f"🏢 {e(job.company)}{star}"]
    loc = job.location[:100] if job.location else "לא צוין"
    lines.append(f"📍 {e(loc)} · {REGION_HE.get(v.region, v.region)}")
    reason = "; ".join(v.reasons) if v.reasons else ""
    lines.append(f"🎯 {TIER_HE.get(v.tier, v.tier)}" + (f" — {e(reason)}" if reason else ""))
    when = KIND_HE.get(job.date_kind, job.date_kind)
    if job.posted_at:
        local = job.posted_at.astimezone(ZoneInfo(tz))
        fmt = "%d/%m" if job.date_kind == "relative" else "%d/%m %H:%M"
        lines.append(f"🕒 {when}: {local.strftime(fmt)} ({age_text(job.posted_at, now)}) · מקור: {e(job.date_source)}")
    else:
        lines.append(f"🕒 {when} · זוהתה אצלנו עכשיו")
    tags = []
    if "clearance" in v.tags:
        tags.append("🔒 אישור/סיווג בטחוני")
    if "internship" in v.tags:
        tags.append("🧪 התמחות")
    if job.source == "tgchannel":
        tags.append("🧭 ליד מטלגרם: לאמת במקור")
    if job.source == "linkedin":
        tags.append("🔗 LinkedIn")
    if tags:
        lines.append(" · ".join(tags))
    for w in v.warnings:
        lines.append(f"⚠️ {e(w)}")
    if v.exp_snippet:
        lines.append(f"📋 {e(v.exp_snippet[:200])}")
    lines.append(f'<a href="{e(job.url, quote=True)}">פתח משרה</a>')
    return "\n".join(lines)


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token, self.chat_id = token, chat_id

    @classmethod
    def from_env(cls):
        t, c = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        return cls(t, c) if t and c else None

    def _call(self, method: str, data: dict, timeout: int = 20):
        """POST to the Bot API with retries. Returns the parsed `result`, or None on failure."""
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        for attempt in range(3):
            try:
                r = requests.post(url, data=data, timeout=timeout)
            except requests.RequestException:
                time.sleep(2)
                continue
            if r.status_code == 200:
                try:
                    return r.json().get("result")
                except ValueError:
                    return None
            if r.status_code == 429:
                try:
                    wait = int(r.json().get("parameters", {}).get("retry_after", 5))
                except ValueError:
                    wait = 5
                time.sleep(min(wait, 30))
                continue
            # Never print the URL (it contains the bot token); method and status code only.
            print(f"telegram {method}: HTTP {r.status_code}")
            return None
        return None

    def send(self, text: str, silent: bool = False, markup: dict | None = None):
        """Returns the sent message_id (truthy) or None."""
        data = {"chat_id": self.chat_id, "text": text[:4000], "parse_mode": "HTML",
                "disable_web_page_preview": "true", "disable_notification": "true" if silent else "false"}
        if markup:
            data["reply_markup"] = json.dumps(markup)
        res = self._call("sendMessage", data)
        return res.get("message_id") if isinstance(res, dict) else None

    def get_updates(self, offset: int):
        res = self._call("getUpdates", {"offset": offset, "timeout": 0,
                                        "allowed_updates": json.dumps(["message", "callback_query"])})
        return res if isinstance(res, list) else None

    def answer_callback(self, callback_id: str, text: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def edit_buttons(self, message_id: int, markup: dict) -> None:
        self._call("editMessageReplyMarkup", {"chat_id": self.chat_id, "message_id": message_id,
                                              "reply_markup": json.dumps(markup)})
