from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ATS_KEYS = ("ats", "token", "uid", "region", "host", "tenant", "site", "search", "max_pages")


def slugify(name: str) -> str:
    s = re.sub(r"\(.*?\)", "", name).lower()
    s = re.sub(r"[^a-z0-9֐-׿]+", "-", s).strip("-")
    return s or "company"


def load_registry(companies_path: str | Path, resolved_path: str | Path | None) -> list[dict]:
    """companies.yaml is the human-curated list (name, domain, category, tier, optional manual ATS config).
    data/resolved.json is machine output of discover.py. Manual config always wins; resolved entries are
    used only when status == 'ok' (strong evidence). 'review' entries wait for a human to copy them over."""
    raw = yaml.safe_load(Path(companies_path).read_text(encoding="utf-8")) or []
    resolved = {}
    if resolved_path and Path(resolved_path).exists():
        resolved = json.loads(Path(resolved_path).read_text(encoding="utf-8")).get("companies", {})
    out = []
    for e in raw:
        c = dict(e)
        c.setdefault("id", slugify(c["name"]))
        c.setdefault("tier", 2)
        c.setdefault("cat", "tech")
        manual = c.get("ats") not in (None, "", "auto")
        if not manual:
            r = resolved.get(c["id"])
            if r and r.get("status") == "ok":
                for k in ATS_KEYS:
                    if k in r:
                        c[k] = r[k]
                c["resolved"] = True
            else:
                c["ats"] = None
        out.append(c)
    return out
