from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "timezone": "Asia/Jerusalem",
    "scan": {
        "threads": 12,
        # a run is expected every ~5 minutes; tier N is scanned every K runs
        "run_interval_minutes": 5,
        "tier_every_n_runs": {1: 1, 2: 2, 3: 6},
        # on the first scan of a company, alert only for jobs whose *source* date is this fresh
        "baseline_alert_within_hours": 48,
        # new-to-us jobs whose source date is older than this are not alerted (re-listings / old boards)
        "max_age_days": 30,
    },
    "match": {
        # title must match one of these (role families: backend/systems/full-stack + security)
        "role_include": [
            r"back[\s-]?end", r"full[\s-]?stack", r"software\s+(engineer|developer|dev)\b",
            r"\bdeveloper\b", r"\bsde\b", r"\bprogrammer\b",
            r"secur", r"cyber", r"appsec", r"\bsoc\b", r"threat", r"vulnerab", r"penetration",
            r"pen[\s-]?test", r"red[\s-]?team", r"\bdfir\b", r"incident\s+response", r"malware",
            r"reverse\s+engineer", r"exploit", r"\bcrypto", r"\bdevsecops\b",
            r"systems?\s+(engineer|programmer|developer|software)", r"low[\s-]?level", r"kernel",
            r"infrastructure\s+(software\s+)?engineer", r"platform\s+engineer",
            r"front[\s-]?end", r"\breact\b", r"\bangular\b", r"\bvue(\.?js)?\b", r"web\s+(developer|engineer)",
            r"\bc\+\+", r"\bgolang\b", r"\brust\b", r"\bpython\b", r"\bjava\b", r"\.net\b", r"\bnode(\.?js)?\b",
            r"מפתח", r"מפתחת", r"אבטחת", r"סייבר", r"בק[\s-]?אנד", r"פולסטאק", r"הנדס(ת|ן)\s*תוכנה",
        ],
        "role_exclude": [
            r"\bsales\b", r"account\s+(executive|manager)", r"marketing", r"recruit", r"talent\s+acqui",
            r"\bhr\b", r"human\s+resources", r"\bpeople\b", r"finance", r"accountant", r"\blegal\b", r"counsel",
            r"customer\s+(success|support)", r"support\s+engineer", r"product\s+manager", r"product\s+design",
            r"\bux\b", r"\bui\b", r"designer", r"business\s+develop", r"\bbdr\b", r"\bsdr\b",
            r"office\s+manager", r"assistant", r"data\s+scien", r"machine\s+learning", r"\bml\b",
            r"data\s+analyst", r"developer\s+(advocate|relations)", r"evangelist", r"solutions?\s+(architect|engineer|consultant)",
            r"pre[\s-]?sales", r"technical\s+writer", r"security\s+guard", r"\bguard\b", r"\bgrc\b", r"compliance",
            r"\bios\b", r"android", r"\bmobile\b",
            r"\bqa\b", r"quality\s+assurance", r"\bdevops\b(?!.*secur)", r"\bsre\b", r"site\s+reliability",
            r"mechanical", r"electrical", r"hardware", r"\bfpga\b", r"\basic\b", r"physical\s+security",
            r"מכירות", r"שיווק", r"גיוס", r"משאבי\s+אנוש", r"שירות\s+לקוחות", r"מנהל\s+מוצר",
        ],
        "seniority_exclude": [
            r"\bsenior\b", r"\bsr\b\.?", r"\bstaff\b", r"\bprincipal\b", r"\blead\b", r"\bhead\b",
            r"\bdirector\b", r"\bvp\b", r"vice\s+president", r"\bchief\b", r"\bmanager\b", r"\barchitect\b",
            r"\bdistinguished\b", r"\bfellow\b", r"\biii\b", r"\biv\b", r"\blevel\s*[3-9]\b", r"\bl[4-9]\b",
            r"בכיר", r"בכירה", r"ראש\s+צוות", r"מנהל", r"מנהלת", r"ארכיטקט",
        ],
        "entry_signals": [
            r"\bjunior\b", r"\bjr\b\.?", r"\bgraduates?\b", r"\bgrads?\b", r"new[\s-]?grad", r"entry[\s-]?level",
            r"early[\s-]?career", r"\btrainee\b", r"\bapprentice\b", r"\bcadet\b", r"university\s+hire",
            r"ג['׳]?ו?ניור", r"בוגר", r"בוגרת", r"בוגרי", r"ללא\s+ניסיון", r"מתחיל", r"\bטרי\b",
        ],
        "internship_signals": [r"\bintern(ship)?s?\b", r"התמחות", r"מתמחה", r"מתמחים", r"\bco-?op\b"],
        "student_signals": [r"\bstudents?\b", r"סטודנט", r"סטודנטית", r"משרת\s+סטודנט"],
        "desc_entry_signals": [
            r"no\s+(prior\s+)?(professional\s+|work\s+)?experience\s+(is\s+)?(required|needed|necessary)",
            r"fresh(ly)?\s+graduates?", r"recent\s+graduates?", r"new\s+graduates?", r"0\s*[-–to]+\s*1\s+years?",
            r"entry[\s-]?level", r"ללא\s+ניסיון", r"בוגרי\s+תואר", r"בוגרים\s+טריים", r"לא\s+נדרש\s+ניסיון",
            # "Talented graduates and junior engineers are welcome to apply" (EyeContact, Oct 2026)
            r"(graduates?|juniors?|junior\s+(engineers?|developers?))\b[^.]{0,40}\b(are\s+)?(welcome|encouraged|invited)\s+to\s+apply",
            r"(welcome|encourage)s?\s+(applications\s+from\s+)?[^.]{0,30}\b(graduates?|juniors?)\b",
            r"suitable\s+for\s+(recent\s+)?(graduates?|juniors?)",
            r"מתאים\s+(גם\s+)?ל(בוגרים|ג['׳]?וניורים|מתחילים)", r"ג['׳]?וניורים\s+(מוזמנים|יתקבלו)",
        ],
        "clearance_signals": [
            r"security\s+clearance", r"\bclearance\b", r"סיווג\s*(ביטחוני|בטחוני)?", r"אישור\s+(ביטחוני|בטחוני)",
            r"מסווג", r"citizens?\s+only", r"israeli\s+citizen",
        ],
        "max_years_accept": 2,  # tier C ceiling
        "include_unspecified_experience": False,  # generic titles without any experience signal
        "include_internships": True,
        "include_student_parttime": False,
    },
    "location": {
        "israel": True,
        "remote": True,
        "relocation": True,
        # remote jobs restricted to these are rejected (the scope text, not the company's HQ)
        "remote_reject_scope": [
            r"\b(us|usa|u\.s\.|united\s+states|canada|uk|united\s+kingdom|india|brazil|mexico|australia|"
            r"poland|ukraine|philippines|argentina|colombia)\b[^|;/]*\bonly\b",
            r"remote\W+(us|usa|united\s+states|canada|india|brazil|mexico|philippines|argentina|colombia)\b",
            r"\bus[\s-]based\b", r"must\s+(be\s+)?(located|based|reside)\s+in\s+(the\s+)?(us|united\s+states|canada|uk)",
        ],
    },
    "notify": {
        "telegram": True,
        "max_alerts_per_run": 25,
        "daily_digest_hour": 8,
        "quiet_hours": None,  # e.g. [0, 6] to queue alerts overnight; None = alert any time
    },
    "leads": {
        # Public Telegram channels to read via https://t.me/s/<handle> (no login / API key).
        # Add handles you verified yourself, e.g. ["some_junior_jobs_channel"].
        "telegram_channels": [],
        "max_age_hours": 48,
        # LinkedIn public (logged-out) job search. Queries were measured against the Classifier:
        # role keyword + f_E (1 = internship, 2 = entry level) gave ~45 title matches a day in Israel.
        "linkedin": {
            "enabled": False,           # switched on in config.yaml
            "tier": 1,
            "geo_id": "101620260",      # Israel
            "time_window": "r86400",    # posted in the last 24h; sorted newest first
            "pages": 1,                 # 10 results per page
            "gap_seconds": 5,           # LinkedIn returns 429 on bursts faster than this
            "cooldown_seconds": 25,
            "queries": [
                {"keywords": "software engineer", "f_E": "1,2", "pages": 2},
                {"keywords": "backend", "f_E": "1,2"},
                {"keywords": "full stack OR fullstack", "f_E": "1,2"},
                {"keywords": "frontend OR front end OR react OR angular", "f_E": "1,2"},
                {"keywords": "developer", "f_E": "2"},
                {"keywords": 'security analyst OR SOC OR "security researcher" OR cyber', "f_E": "1,2"},
                {"keywords": "software OR security OR developer", "f_E": "1"},
                {"keywords": 'junior OR graduate OR "entry level"'},
            ],
        },
    },
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None) -> dict:
    over = {}
    if path and Path(path).exists():
        over = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cfg = deep_merge(DEFAULTS, over)
    # YAML keys for tier_every_n_runs may load as ints already; normalise
    cfg["scan"]["tier_every_n_runs"] = {int(k): int(v) for k, v in cfg["scan"]["tier_every_n_runs"].items()}
    return cfg
