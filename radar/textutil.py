from __future__ import annotations

import hashlib
import html
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from bs4 import BeautifulSoup


def html_to_text(s: Optional[str]) -> str:
    """HTML (possibly entity-encoded, as Greenhouse returns it) -> readable text
    with one bullet/paragraph per line, which the experience parser relies on."""
    if not s:
        return ""
    if "&lt;" in s and "<" not in s:
        s = html.unescape(s)
    soup = BeautifulSoup(s, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    for t in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "ul", "ol", "tr"]):
        t.insert_after("\n")
    txt = soup.get_text()
    txt = txt.replace("\xa0", " ")
    txt = re.sub(r"[ \t\r\f\v]+", " ", txt)
    txt = re.sub(r"\n[ \t]*", "\n", txt)
    txt = re.sub(r"\n{2,}", "\n", txt)
    return txt.strip()


def parse_iso(s) -> Optional[datetime]:
    if not s:
        return None
    s = str(s).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                d = datetime.strptime(s[:19] if " " in s else s[:10], fmt)
                break
            except ValueError:
                d = None
        if d is None:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def from_ms(ms) -> Optional[datetime]:
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    if ms > 1e11:  # milliseconds
        ms /= 1000.0
    return datetime.fromtimestamp(ms, tz=timezone.utc)


_REL = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.I)


def parse_relative_en(s: str, now: Optional[datetime] = None) -> tuple[Optional[datetime], bool]:
    """Workday-style 'Posted 3 Days Ago'. Returns (date at day precision, is_exact_enough).
    '30+ Days Ago' is returned as 30 days and flagged inexact."""
    now = now or datetime.now(timezone.utc)
    m = _REL.search(s or "")
    if not m:
        return None, False
    word = m.group(1).lower()
    if word == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), True
    if word == "yesterday":
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0), True
    n = int(m.group(2))
    exact = "+" not in m.group(0)
    return (now - timedelta(days=n)).replace(hour=0, minute=0, second=0, microsecond=0), exact


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9֐-׿]+", "", (s or "").lower())


# ----------------------------------------------------------------------------- description signatures
_P = (1 << 61) - 1
_MH = [(random.Random(i).randrange(1, _P), random.Random(i + 1000).randrange(_P)) for i in range(32)]


def text_sig(text: str) -> str:
    """MinHash of the description's word 3-grams (32 x 16 bits, hex). Two signatures agree in about the
    share of 3-grams the texts have in common, so a repost or the same job on another board scores high
    and two different jobs with the same generic title score low. "" when the text is too short to judge."""
    words = re.findall(r"\w+", (text or "").lower())
    if len(words) < 40:
        return ""
    grams = {int.from_bytes(hashlib.blake2b(" ".join(words[i:i + 3]).encode(), digest_size=8).digest(), "big")
             for i in range(len(words) - 2)}
    return "".join(f"{min((a * g + b) % _P for g in grams) & 0xFFFF:04x}" for a, b in _MH)


def sig_similarity(a: str, b: str) -> float:
    pa, pb = [a[i:i + 4] for i in range(0, len(a), 4)], [b[i:i + 4] for i in range(0, len(b), 4)]
    return sum(x == y for x, y in zip(pa, pb)) / max(len(pa), 1)
