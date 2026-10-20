"""Job classification: role family, seniority, location, experience requirement.

Design notes
- Stage 1 (title + location only) is cheap and decides whether we spend a detail request.
- Stage 2 adds the description: required years of experience, entry-level phrases, clearance.
- "Required" vs "preferred" experience is separated; only required years can reject a job.
- A job with no entry signal and no stated years is NOT alerted unless
  match.include_unspecified_experience is true (the owner chose explicit/<=1y/<=2y only).
"""
from __future__ import annotations

import re
from typing import Optional

from .models import Job, Verdict

# Bump when the match rules change: the next scan then re-evaluates jobs rejected in the last 72h
# whose reject note matches RECHECK_NOTES (the rejections the change can flip).
FILTERS_VERSION = 3
RECHECK_NOTES = r"^role excluded: .*(devops|qa|quality|ios|android|mobile|data|ml|machine|solution|sre|site)"

_FLAGS = re.I | re.U


def _compile(patterns) -> list:
    return [re.compile(p, _FLAGS) for p in patterns]


def _any(rx_list, text: str) -> Optional[str]:
    for rx in rx_list:
        m = rx.search(text)
        if m:
            return m.group(0)
    return None


# ----------------------------------------------------------------------------- locations
ISRAEL_TERMS = re.compile(
    r"israel|tel[\s-]?aviv|ramat[\s-]?gan|herzliy?a|petah[\s-]?tik|petach|jerusalem|haifa|be'?er[\s-]?sheva|"
    r"beersheba|rehovot|ra'?anana|kfar[\s-]?saba|netanya|rishon|holon|bnei[\s-]?brak|yokneam|caesarea|"
    r"hod[\s-]?hasharon|modi'?in|lod\b|or[\s-]?yehuda|airport[\s-]?city|yavne|ashdod|ashkelon|nazareth|"
    r"kiryat|qiryat|givatayim|bat[\s-]?yam|rosh[\s-]?ha'?ayin|misgav|migdal[\s-]?haemek|tirat|"
    r"\bIL\b|ישראל|תל[\s-]?אביב|רמת[\s-]?גן|הרצליה|פתח[\s-]?תקו|ירושלים|חיפה|באר[\s-]?שבע|רחובות|רעננה|"
    r"כפר[\s-]?סבא|נתניה|ראשון|חולון|בני[\s-]?ברק|יוקנעם|קיסריה|הוד[\s-]?השרון|מודיעין|לוד|אור[\s-]?יהודה|"
    r"יבנה|אשדוד|אשקלון|נצרת|קריית|גבעתיים|בת[\s-]?ים|ראש[\s-]?העין|מרכז|צפון|דרום|שרון|שפלה",
    re.I | re.U,
)
REMOTE_TERMS = re.compile(r"\bremote\b|work\s+from\s+home|\bwfh\b|anywhere|distributed|מרחוק|עבודה\s+מהבית", re.I | re.U)
RELOCATION_TERMS = re.compile(r"relocat|visa\s+sponsor|sponsorship|work\s+permit|רילוקיישן|רילוקיישן", re.I | re.U)


def classify_location(job: Job, cfg: dict) -> tuple[str, list]:
    """-> (region, warnings). region '' means: not acceptable."""
    loc = job.location or ""
    desc_head = (job.description or "")[:1500]
    lc = cfg["location"]
    remote_rx = _compile(lc["remote_reject_scope"])
    warnings: list = []

    is_israel = bool(ISRAEL_TERMS.search(loc))
    is_remote = bool(job.remote) or bool(REMOTE_TERMS.search(loc))

    if is_israel and lc["israel"]:
        return "israel", warnings
    if is_remote and lc["remote"]:
        scope_text = f"{loc} {desc_head[:400]}"
        hit = _any(remote_rx, scope_text)
        if hit:
            return "", [f"remote restricted: {hit.strip()}"]
        if not loc.strip():
            warnings.append("מיקום לא צוין")
        return "remote", warnings
    if not loc.strip() and lc["israel"]:
        # Some boards hide the location. Treat as Israel-possible, flagged.
        if ISRAEL_TERMS.search(desc_head):
            return "israel", warnings
        return "", ["no location"]
    if lc["relocation"] and RELOCATION_TERMS.search(f"{loc} {desc_head}"):
        return "relocation", warnings
    return "", ["location outside scope"]


# ----------------------------------------------------------------------------- experience
_WORDNUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "שנה": 1, "שנתיים": 2, "שלוש": 3, "ארבע": 4, "חמש": 5, "שש": 6, "שבע": 7, "שמונה": 8, "תשע": 9, "עשר": 10,
}
_EN_YEARS = re.compile(
    r"(?:(?:at\s+least|minimum(?:\s+of)?|min\.?|over|more\s+than|up\s+to)\s+)?"
    r"(?P<a>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s*(?:\+|(?:-|–|—|to)\s*(?P<b>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten))?\s*\+?\s*"
    r"(?:years?|yrs?)\b",
    re.I,
)
_HE_YEARS = re.compile(
    r"(?:(?P<a>\d{1,2})\s*(?:\+|[-–]\s*(?P<b>\d{1,2}))?\s*\+?\s*(?:שנות|שנים|שנה)(?:\s+של)?\s*ניסיון)"
    r"|(?:ניסיון\s+(?:של\s+)?(?:לפחות\s+)?(?P<c>\d{1,2})\s*(?:\+|[-–]\s*(?P<d>\d{1,2}))?\s*\+?\s*(?:שנות|שנים|שנה))"
    r"|(?P<w>שנתיים|שנת)\s*ניסיון",
    re.U,
)
_EXP_CONTEXT = re.compile(
    r"experience|exp\.|ניסיון|hands[\s-]?on|background|proven|track\s+record|working\s+(?:with|as|in)|"
    r"developing|development|building|professional|worked|work\s+in|in\s+(?:a\s+)?(?:role|field|position)",
    re.I | re.U,
)
_OPTIONAL = re.compile(
    r"nice\s+to\s+have|preferred|a\s+plus|bonus|advantage|desirable|desired|an?\s+asset|would\s+be\s+(?:a\s+)?(?:plus|great)|"
    r"yitaron|יתרון|רצוי|עדיפות|מועדף|יהווה\s+יתרון|דרישות\s+רשות",
    re.I | re.U,
)
_OPT_HEADER = re.compile(r"^\W*(nice\s+to\s+have|preferred|bonus|advantages?|plus(es)?|desirable|יתרון|יתרונות|דרישות\s+רשות)\b", re.I | re.U)
_REQ_HEADER = re.compile(r"^\W*(requirements?|qualifications?|must[\s-]?have|what\s+you(?:'ll|\s+will)?\s+(?:need|bring)|basic\s+qualifications|דרישות|דרישות\s+התפקיד|נדרש)\b", re.I | re.U)


def _num(tok: Optional[str]) -> Optional[int]:
    if tok is None:
        return None
    tok = tok.strip().lower()
    if tok.isdigit():
        return int(tok)
    return _WORDNUM.get(tok)


def extract_experience(text: str) -> tuple[Optional[int], str, list]:
    """-> (required_years or None, snippet, optional_years_list).
    required_years = the largest *lower bound* among mandatory mentions."""
    if not text:
        return None, "", []
    required: list = []
    optional: list = []
    best_snip = ""
    mode = "req"
    for raw in text.splitlines():
        line = raw.strip(" \t•-–*·")
        if not line:
            continue
        # section headers switch the mode
        if len(line) <= 60:
            if _OPT_HEADER.search(line):
                mode = "opt"
            elif _REQ_HEADER.search(line):
                mode = "req"
        # split long lines into sentences so one "preferred" clause doesn't poison the rest
        for sent in re.split(r"(?<=[.;!?])\s+", line):
            if not sent:
                continue
            sent_opt = mode == "opt" or bool(_OPTIONAL.search(sent))
            found: list = []
            for m in _EN_YEARS.finditer(sent):
                a = _num(m.group("a"))
                if a is None:
                    continue
                if "up to" in sent[max(0, m.start() - 8):m.end()].lower():
                    # "up to 2 years" is a ceiling, not a requirement
                    continue
                found.append(a)
            for m in _HE_YEARS.finditer(sent):
                if m.group("w"):
                    found.append(2 if m.group("w") == "שנתיים" else 1)
                    continue
                a = m.group("a") or m.group("c")
                if a:
                    found.append(int(a))
            if not found or not _EXP_CONTEXT.search(sent):
                continue
            if sent_opt:
                optional.extend(found)
            else:
                required.extend(found)
                v = max(found)
                if not best_snip or v >= max(required):
                    best_snip = sent.strip()[:220]
    return (max(required) if required else None), best_snip, optional


# ----------------------------------------------------------------------------- main entry
class Classifier:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        m = cfg["match"]
        self.role_inc = _compile(m["role_include"])
        self.role_exc = _compile(m["role_exclude"])
        self.role_exc_soft = _compile(m["role_exclude_soft"])
        self.role_core = _compile(m["role_core"])
        self.sen_exc = _compile(m["seniority_exclude"])
        self.entry = _compile(m["entry_signals"])
        self.intern = _compile(m["internship_signals"])
        self.student = _compile(m["student_signals"])
        self.desc_entry = _compile(m["desc_entry_signals"])
        self.clearance = _compile(m["clearance_signals"])
        self.max_years = int(m["max_years_accept"])

    # -- stage 1: title/location only -------------------------------------------------
    def stage1(self, job: Job) -> Verdict:
        t = job.title or ""
        m = self.cfg["match"]
        if (hit := _any(self.role_exc, t)):
            return Verdict(False, reject_reason=f"role excluded: {hit}", stage=1)
        if (hit := _any(self.role_exc_soft, t)) and not _any(self.role_core, t):
            return Verdict(False, reject_reason=f"role excluded: {hit}", stage=1)
        if not _any(self.role_inc, t):
            return Verdict(False, reject_reason="title not in role families", stage=1)
        entry_hit = _any(self.entry, t)
        intern_hit = _any(self.intern, t)
        # explicit entry-level wording wins over a seniority word only for interns
        if (hit := _any(self.sen_exc, t)) and not intern_hit:
            return Verdict(False, reject_reason=f"seniority: {hit}", stage=1)
        if (lvl := (job.level or "").lower()) and re.search(r"senior|lead|manager|director|executive|mid[\s-]?senior|principal", lvl):
            return Verdict(False, reject_reason=f"source level: {job.level}", stage=1)
        student_hit = _any(self.student, t)
        if student_hit and not m["include_student_parttime"] and not intern_hit:
            return Verdict(False, reject_reason="student/part-time position", stage=1)
        if intern_hit and not m["include_internships"]:
            return Verdict(False, reject_reason="internship excluded", stage=1)
        region, warns = classify_location(job, self.cfg)
        if not region:
            return Verdict(False, reject_reason="; ".join(warns) or "location", stage=1)
        v = Verdict(True, region=region, warnings=warns, stage=1)
        if entry_hit:
            v.reasons.append(f"כותרת: {entry_hit}")
        if intern_hit:
            v.tags.append("internship")
            v.reasons.append(f"התמחות: {intern_hit}")
        return v

    # -- stage 2: with description --------------------------------------------------------
    def classify(self, job: Job) -> Verdict:
        v = self.stage1(job)
        if not v.accept:
            return v
        v.stage = 2
        t = job.title or ""
        desc = job.description or ""
        m = self.cfg["match"]

        # region may need the description (e.g. missing location)
        if job.description:
            region, warns = classify_location(job, self.cfg)
            if region:
                v.region, v.warnings = region, warns

        if _any(self.clearance, f"{t}\n{desc}"):
            v.tags.append("clearance")

        years, snippet, optional_years = extract_experience(desc)
        v.req_years, v.exp_snippet = years, snippet

        title_entry = _any(self.entry, t)
        level_entry = bool(re.search(r"entry|junior|intern|graduate|student|trainee", job.level or "", re.I))
        employment_intern = bool(re.search(r"intern", job.employment or "", re.I))
        desc_entry = _any(self.desc_entry, desc)

        if employment_intern and "internship" not in v.tags and m["include_internships"]:
            v.tags.append("internship")

        if title_entry or level_entry or "internship" in v.tags:
            v.tier = "A"
            if level_entry and not title_entry:
                v.reasons.append(f"רמת ניסיון במקור: {job.level}")
            if years is not None and years > self.max_years:
                v.warnings.append(f"⚠️ כותרת מתחילה אבל התיאור מזכיר {years} שנות ניסיון")
            return v

        if years is not None:
            if years <= 1:
                v.tier = "B"
                v.reasons.append("דורש עד שנת ניסיון" if years == 1 else "לא נדרשות שנות ניסיון")
                return v
            if years <= self.max_years:
                v.tier = "C"
                v.reasons.append(f"דורש {years} שנות ניסיון")
                return v
            v.accept = False
            v.reject_reason = f"requires {years}+ years"
            return v

        if desc_entry:
            v.tier = "A"
            v.reasons.append(f"בתיאור: {desc_entry}")
            return v

        if m["include_unspecified_experience"]:
            v.tier = "C"
            v.warnings.append("ותק לא צוין במשרה")
            return v
        v.accept = False
        v.reject_reason = "no experience signal"
        return v
