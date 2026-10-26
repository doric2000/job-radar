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
FILTERS_VERSION = 8
# v8: "N+ years" above MAX_PLAUSIBLE_YEARS is company history, not a requirement (KLA "over 40 years of ... experience")
RECHECK_NOTES = r"^requires (1[6-9]|[2-9]\d|\d{3,})\+ years$"
# No posting asks for more than this; a larger number next to "experience" describes the company
MAX_PLAUSIBLE_YEARS = 15

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
_HE_NUM = r"\d{1,2}|שלוש|ארבע|חמש|שש|שבע|שמונה|תשע|עשר"
# qualifiers that may sit between "ניסיון" and the number: "ניסיון של מעל 3 שנים", "ניסיון של כ-4 שנים"
_HE_QUAL = r"(?:(?:מעל|לפחות|מינימום|יותר\s+מ[-־]?|כ[-־]?|בן|בת)\s*)*"
# adjectives between "ניסיון" and the number: "ניסיון מוכח של כ-5 שנים", "ניסיון מעשי של 3 שנים"
_HE_ADJ = r"(?:(?:מוכח|מעשי|רלוונטי|קודם|מקצועי|תעסוקתי|טכני)\s+)*"
_HE_YEARS = re.compile(
    rf"(?:(?P<a>{_HE_NUM})\s*(?:\+|[-–]\s*(?P<b>\d{{1,2}}))?\s*\+?\s*(?:שנות|שנים|שנה)(?:\s+של)?\s*ניסיון)"
    rf"|(?:ניסיון\s+{_HE_ADJ}(?:של\s+)?{_HE_QUAL}(?P<c>{_HE_NUM})\s*(?:\+|[-–]\s*(?P<d>\d{{1,2}}))?\s*\+?\s*(?:שנות|שנים|שנה))"
    rf"|(?:(?:מעל|לפחות|מינימום|יותר\s+מ[-־]?)\s*(?P<e>{_HE_NUM})\s*\+?\s*(?:שנות|שנים))"
    rf"|(?:ניסיון\s+{_HE_ADJ}(?:של\s+)?{_HE_QUAL}(?P<w2>שנתיים|שנה)(?=\s|$|[.,;]))"
    r"|(?P<w>שנתיים|שנת|שנה)\s*ניסיון",
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
_REQ_HEADER = re.compile(
    r"^\W*(requirements?|qualifications?|must[\s-]?have|what\s+you(?:'ll|\s+will)?\s+(?:need|bring)|basic\s+qualifications|"
    # KLA: "Mandatory:" ... "Advantages:" ... "Minimum Qualifications" (5 years with a BSc)
    r"(?:minimum|required|mandatory)\s+(?:qualifications|requirements)|mandatory|"
    r"what\s+we(?:'re|\s+are)\s+looking\s+for|who\s+you\s+are|about\s+you|you\s+(?:have|bring|should\s+have)|"
    r"דרישות|דרישות\s+התפקיד|נדרש|מה\s+אנחנו\s+מחפשים|מה\s+נדרש|מי\s+את[הן]?|כישורים)\b", re.I | re.U)
# a short line ending with ':' or '?' is a section header (used to stop the requirements excerpt)
_ANY_HEADER = re.compile(r"^.{2,60}[:?]\s*$", re.U)
# call-to-action lines end the requirements section
_CTA = re.compile(r"שלחו|קורות\s+חיים|מעוניינ|\bapply\b|send\s+(?:us\s+)?your|interested\?|equal\s+opportunity|about\s+(?:us|the\s+company)", re.I | re.U)


_ROLE_HEADER = re.compile(
    r"^\W*(about\s+the\s+(?:role|position|job)|the\s+role|role\s+overview|what\s+you(?:'ll|\s+will)\s+do|"
    r"responsibilities|your\s+(?:role|mission|impact)|in\s+this\s+role|job\s+description|"
    r"קצת\s+על\s+התפקיד|על\s+התפקיד|תיאור\s+(?:ה)?תפקיד|התפקיד\s+כולל|תחומי\s+אחריות|מה\s+(?:ת|י)עש(?:ה|ו)|במסגרת\s+התפקיד)\b",
    re.I | re.U)
# company marketing that says nothing about the job itself
_BOILERPLATE = re.compile(r"\b(?:leading|leader|world[\s-]class|trusted\s+by|founded|backed\s+by|unicorn|we\s+are\s+(?:a|the)|"
                          r"our\s+(?:mission|customers)|join\s+(?:us|our)|about\s+us)\b|חברה\s+מובילה|מובילה\s+בתחום|הצטרפו", re.I | re.U)


# "Location: ...", "Position Type: ..." - metadata, not a description
_META_LINE = re.compile(r"^(?:location|position\s+type|employment\s+type|job\s+type|company|department|מיקום|היקף\s+משרה|סוג\s+משרה)\s*:", re.I | re.U)


def extract_summary(text: str, max_lines: int = 4, max_chars: int = 450) -> list[str]:
    """A few lines that say what the job is: the role/responsibilities section if there is one, otherwise
    the first lines of the posting that are not company marketing. Stops at the requirements section."""
    lines = [ln.strip(" \t•-–*·✔️✓▪") for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    out: list[str] = []
    for i, ln in enumerate(lines):
        if len(ln) <= 60 and _ROLE_HEADER.search(ln):
            for nxt in lines[i + 1:]:
                if (len(nxt) <= 60 and (_REQ_HEADER.search(nxt) or _OPT_HEADER.search(nxt) or _ANY_HEADER.match(nxt))) \
                        or _CTA.search(nxt) or len(out) >= max_lines:
                    break
                out.append(nxt[:180])
            break
    if not out:
        for ln in lines:
            if len(ln) <= 60 and (_REQ_HEADER.search(ln) or _OPT_HEADER.search(ln)):
                break
            if len(ln) < 25 or _BOILERPLATE.search(ln) or _CTA.search(ln) or _META_LINE.match(ln):
                continue
            out.append(ln[:180])
            if len(out) >= max_lines:
                break
    total, kept = 0, []
    for ln in out:
        total += len(ln)
        if total > max_chars:
            break
        kept.append(ln)
    return kept


def extract_requirements(text: str, max_lines: int = 6, max_chars: int = 600) -> list[str]:
    """The first lines of the job's requirements section, for the alert. Falls back to lines that
    mention experience/years when the posting has no recognizable requirements header."""
    lines = [ln.strip(" \t•-–*·✔️✓▪") for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    out: list[str] = []
    for i, ln in enumerate(lines):
        if len(ln) <= 60 and _REQ_HEADER.search(ln):
            for nxt in lines[i + 1:]:
                if ((len(nxt) <= 60 and (_OPT_HEADER.search(nxt) or _ANY_HEADER.match(nxt)))
                        or _CTA.search(nxt) or len(out) >= max_lines):
                    break
                out.append(nxt[:160])
            break
    if not out:
        out = [ln[:160] for ln in lines if (_EN_YEARS.search(ln) or _HE_YEARS.search(ln)) and _EXP_CONTEXT.search(ln)][:3]
    total, kept = 0, []
    for ln in out:
        total += len(ln)
        if total > max_chars:
            break
        kept.append(ln)
    return kept


def _num(tok: Optional[str]) -> Optional[int]:
    if tok is None:
        return None
    tok = tok.strip().lower()
    if tok.isdigit():
        return int(tok)
    return _WORDNUM.get(tok)


_MANDATORY = re.compile(r"\bmust\b|\brequired\b|mandatory|חובה", re.I | re.U)
# "At least 3 years of backend experience, or a strong graduate with serious side projects" (Flytrex)
_GRAD_ALTERNATIVE = re.compile(
    r"\bor\b[^.;]{0,50}\b(?:graduates?|students?|bootcamp|side[\s-]projects|personal\s+projects|equivalent\s+(?:academic|projects?))\b"
    r"|או\s+(?:בוגר|סטודנט|ניסיון\s+(?:אקדמי|בפרויקטים|אישי))", re.I | re.U)
# a clause that is nothing but "an advantage" / "a plus" / "יתרון"
_BARE_OPTIONAL = re.compile(
    r"^(?:(?:is|are|will\s+be|would\s+be)\s+)?(?:an?\s+)?(?:big\s+|strong\s+)?(?:advantage|plus|bonus|preferred|desirable|nice\s+to\s+have)$"
    r"|^(?:יהווה\s+)?(?:יתרון(?:\s+משמעותי)?|רצוי)$", re.I | re.U)
_CLAUSE_SPLIT = re.compile(r"[,;]|\s[-–—]\s|\s+(?:and|while|but|ו?יתרון)\s+", re.I | re.U)


def _is_optional(sent: str, pos: int, mode: str) -> bool:
    """Is the years mention at `pos` optional? Only the clause that contains it counts, and text in
    parentheses is ignored: in "4+ years of Linux (Debian preferred)" or "5 years managing switches,
    Cisco an advantage" the years are still required. An explicit must/חובה in the sentence wins,
    except over an alternative path for graduates ("3 years ..., or a strong graduate with side projects")."""
    if _GRAD_ALTERNATIVE.search(sent):
        return True
    if _MANDATORY.search(sent):
        return False
    if mode == "opt":
        return True
    splits = list(_CLAUSE_SPLIT.finditer(sent))
    start = max([0] + [m.end() for m in splits if m.end() <= pos])
    after = [m for m in splits if m.start() > pos]
    end = after[0].start() if after else len(sent)
    clause = sent[start:end]
    if after:
        # a short trailing clause that is only "an advantage" / "a plus" qualifies the clause before it
        nxt_end = after[1].start() if len(after) > 1 else len(sent)
        tail = sent[after[0].end():nxt_end].strip(" .!")
        if _BARE_OPTIONAL.match(tail):
            clause += " " + tail
    return bool(_OPTIONAL.search(re.sub(r"\([^)]*\)", " ", clause)))


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
            if not _EXP_CONTEXT.search(sent):
                continue
            found: list = []  # (years, is_optional)
            for m in _EN_YEARS.finditer(sent):
                a = _num(m.group("a"))
                if a is None:
                    continue
                if "up to" in sent[max(0, m.start() - 8):m.end()].lower():
                    # "up to 2 years" is a ceiling, not a requirement
                    continue
                found.append((a, _is_optional(sent, m.start(), mode)))
            for m in _HE_YEARS.finditer(sent):
                w = m.group("w") or m.group("w2")
                a = (2 if w == "שנתיים" else 1) if w else _num(m.group("a") or m.group("c") or m.group("e"))
                if a is not None:
                    found.append((a, _is_optional(sent, m.start(), mode)))
            # company history, not a requirement: KLA's "With over 40 years of ... experience, chipmakers ..."
            found = [(a, opt) for a, opt in found if a <= MAX_PLAUSIBLE_YEARS]
            optional.extend(a for a, opt in found if opt)
            req_here = [a for a, opt in found if not opt]
            if req_here:
                required.extend(req_here)
                if not best_snip or max(req_here) >= max(required):
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
        self.hw_desc = _compile(m["hardware_desc_signals"])
        self.hw_titles = _compile(m["hardware_check_titles"])
        self.senior_desc = _compile(m["senior_desc_signals"])
        self.experienced_intro = _compile(m["experienced_intro_signals"])
        self.freelance = _compile(m["freelance_signals"])
        self.max_years = int(m["max_years_accept"])
        self.company_exc = _compile(m.get("company_exclude", []))

    # -- stage 1: title/location only -------------------------------------------------
    def stage1(self, job: Job) -> Verdict:
        t = job.title or ""
        m = self.cfg["match"]
        if (hit := _any(self.company_exc, job.company or "")):
            return Verdict(False, reject_reason=f"company excluded: {hit}", stage=1)
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

        if _any(self.hw_titles, t) and not _any(self.role_core, t):
            hw = {rx.pattern for rx in self.hw_desc if rx.search(desc)}
            if len(hw) >= 2:
                v.accept, v.reject_reason = False, "hardware/electronics role"
                return v

        if (hit := _any(self.freelance, desc)):
            v.accept, v.reject_reason = False, f"freelance: {hit}"
            return v
        if not _any(self.entry, t) and "internship" not in v.tags and (hit := _any(self.experienced_intro, desc)):
            v.accept, v.reject_reason = False, f"asks for experienced: {hit}"[:60]
            return v

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

        # no years stated: senior wording ("expertise", "track record", "ידע נרחב"...) still gives seniority away
        senior = sorted({h.group(0) for rx in self.senior_desc for h in [rx.search(desc)] if h})
        if len(senior) >= int(m.get("senior_desc_threshold", 3)):
            v.accept = False
            v.reject_reason = f"senior wording, no years: {', '.join(senior[:3])}"[:60]
            return v

        if m["include_unspecified_experience"]:
            v.tier = "C"
            v.warnings.append("ותק לא צוין במשרה")
            return v
        v.accept = False
        v.reject_reason = "no experience signal"
        return v
