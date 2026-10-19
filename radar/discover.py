"""Find each company's ATS board automatically and validate it.

  python -m radar.discover [--only id,id] [--refresh] [--workers 8]

Strategy (same idea that resolves ~70% of domains in public experiments):
 1. Fetch the company's careers page(s) and look for links / embeds of known ATS vendors.
 2. If nothing is found, probe likely board slugs (name / domain variants) on Greenhouse, Lever,
    Ashby, SmartRecruiters, Workable, Recruitee.
 3. Validate by actually listing the board. Because the registry is Israeli-focused, a board that has at
    least one job located in Israel is strong evidence it is the right company.
Result statuses:  ok (used by the scanner) | review (found, ambiguous: confirm by hand) | none.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .fetchers import FETCHERS
from .filters import ISRAEL_TERMS
from .http import Http
from .registry import load_registry

RESERVED = {"embed", "static", "assets", "js", "css", "img", "images", "api", "v1", "www", "jobs", "careers", "about"}

PATTERNS = [
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([\w-]+)", re.I)),
    ("lever-eu", re.compile(r"jobs\.eu\.lever\.co/([\w-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.I)),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([\w.%-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
]
WORKDAY = re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.I)
COMEET_URL = re.compile(r"comeet\.com/jobs/([\w-]+)/([0-9A-Fa-f.]+)", re.I)
COMEET_UID = re.compile(r"""["']?company-uid["']?\s*[:=]\s*["']([\w.]+)["']""", re.I)
COMEET_TOKEN = re.compile(r"""["']?token["']?\s*[:=]\s*["']([0-9A-Fa-f]{8,})["']""", re.I)

CAREER_PATHS = ["/careers", "/careers/", "/jobs", "/company/careers", "/about/careers", "/join-us", "/careers/jobs"]


def candidates_from_html(html: str) -> list[dict]:
    out, seen = [], set()

    def add(c):
        k = json.dumps(c, sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(c)

    for ats, rx in PATTERNS:
        for m in rx.finditer(html):
            tok = m.group(1)
            if tok.lower() in RESERVED:
                continue
            if ats == "lever-eu":
                add({"ats": "lever", "token": tok, "region": "eu"})
            else:
                add({"ats": ats, "token": tok})
    for m in WORKDAY.finditer(html):
        tenant, wd, site = m.groups()
        add({"ats": "workday", "host": f"{tenant}.{wd}.myworkdayjobs.com", "tenant": tenant, "site": site})
    for m in COMEET_URL.finditer(html):
        add({"ats": "comeet", "uid": m.group(2), "slug": m.group(1)})
    uid, tok = COMEET_UID.search(html), COMEET_TOKEN.search(html)
    if uid and tok and "comeet" in html.lower():
        add({"ats": "comeet", "uid": uid.group(1), "token": tok.group(1)})
    return out


def slug_variants(name: str, domain: str, hints: list[str] | None, limit: int = 7) -> list[str]:
    base = re.sub(r"\(.*?\)", "", name).lower()
    full = re.findall(r"[a-z0-9]+", base)
    trimmed = [w for w in full if w not in {"ltd", "inc", "corp", "technologies", "technology", "group", "israel", "systems"}]
    c = list(hints or [])
    for words in (trimmed or full, full):
        if words:
            c += ["".join(words), "-".join(words)]
    if trimmed:
        c.append(trimmed[0])
    if domain:
        c.append(domain.split(".")[0])
    c += [s + "inc" for s in list(c)[:2]]
    seen, out = set(), []
    for s in c:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out[:limit + len(hints or [])]


def israel_count(jobs) -> int:
    return sum(1 for j in jobs if ISRAEL_TERMS.search(j.location or ""))


class Discoverer:
    def __init__(self, http: Http):
        self.http = http
        self.fetchers = {k: cls(http) for k, cls in FETCHERS.items()}

    def evaluate(self, c: dict, cand: dict):
        """-> (jobs or None, error)"""
        cfg = {"id": c["id"], "name": c["name"], **{k: v for k, v in cand.items() if k != "slug"}}
        try:
            return self.fetchers[cand["ats"]].list_jobs(cfg), ""
        except Exception as e:  # noqa: BLE001
            return None, f"{e.__class__.__name__}: {e}"[:100]

    def page_candidates(self, c: dict) -> tuple[list[dict], str]:
        domain = c.get("domain")
        urls = []
        if c.get("careers_url"):
            urls.append(c["careers_url"])
        if domain:
            urls += [f"https://careers.{domain}", f"https://jobs.{domain}"]
            urls += [f"https://{domain}{p}" for p in CAREER_PATHS] + [f"https://www.{domain}{p}" for p in CAREER_PATHS[:3]]
        found, hit_url = [], ""
        tried = 0
        for u in urls:
            if tried >= 6:
                break
            try:
                html = self.http.get_text(u)
            except Exception:  # noqa: BLE001
                continue
            tried += 1
            cands = candidates_from_html(html)
            # Comeet needs the token: look for it on the same page, then on the hosted page
            for cand in cands:
                if cand["ats"] == "comeet" and not cand.get("token"):
                    tok = COMEET_TOKEN.search(html)
                    if tok:
                        cand["token"] = tok.group(1)
                    elif cand.get("slug"):
                        try:
                            h2 = self.http.get_text(f"https://www.comeet.com/jobs/{cand['slug']}/{cand['uid']}")
                            t2 = COMEET_TOKEN.search(h2)
                            if t2:
                                cand["token"] = t2.group(1)
                        except Exception:  # noqa: BLE001
                            pass
            if cands:
                found, hit_url = cands, u
                break
        return found, hit_url

    def resolve(self, c: dict) -> dict:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        base = {"name": c["name"], "checked_at": now}
        # 1. evidence from the company's own pages
        cands, url = self.page_candidates(c)
        notes = []
        for cand in cands:
            if cand["ats"] == "comeet" and not cand.get("token"):
                notes.append(f"comeet uid={cand['uid']} found but token not found - add manually")
                continue
            jobs, err = self.evaluate(c, cand)
            if jobs is not None:
                keep = {k: v for k, v in cand.items() if k != "slug"}
                return {**base, **keep, "status": "ok", "evidence": f"link on {url}", "jobs": len(jobs),
                        "israel_jobs": israel_count(jobs)}
            notes.append(f"{cand['ats']}:{cand.get('token') or cand.get('tenant')} -> {err}")
        # 2. blind probing
        best = None
        for slug in slug_variants(c["name"], c.get("domain", ""), c.get("slugs")):
            for ats in ("greenhouse", "lever", "ashby", "smartrecruiters"):
                cand = {"ats": ats, "token": slug}
                jobs, err = self.evaluate(c, cand)
                if jobs is None or not jobs:
                    continue
                il = israel_count(jobs)
                score = (il, len(jobs))
                if best is None or score > best[0]:
                    best = (score, cand, len(jobs), il)
            if best and best[3] >= 1:
                break
        if best:
            _, cand, n, il = best
            status = "ok" if il >= 1 else "review"
            return {**base, **cand, "status": status, "evidence": "slug probe", "jobs": n, "israel_jobs": il,
                    **({"note": "board has no job located in Israel - confirm it is the right company"} if il == 0 else {})}
        return {**base, "status": "none", "evidence": "", "note": "; ".join(notes)[:300] or "no ATS found (custom careers site?)"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--companies", default="companies.yaml")
    ap.add_argument("--out", default="data/resolved.json")
    ap.add_argument("--report", default="data/discovery_report.md")
    ap.add_argument("--only", default="")
    ap.add_argument("--refresh", action="store_true", help="re-resolve companies already marked ok")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)

    reg = load_registry(a.companies, None)
    out_path = Path(a.out)
    prev = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {"companies": {}}
    prev_c = prev.get("companies", {})
    only = {x for x in a.only.split(",") if x}
    disc = Discoverer(Http())

    todo, kept = [], {}
    for c in reg:
        if c.get("ats") not in (None, "", "auto"):
            continue  # manual config wins
        if only and c["id"] not in only:
            kept[c["id"]] = prev_c.get(c["id"])
            continue
        p = prev_c.get(c["id"])
        if p and p.get("status") == "ok" and not a.refresh:
            # cheap revalidation: one list call
            cand = {k: p[k] for k in ("ats", "token", "uid", "region", "host", "tenant", "site") if k in p}
            jobs, err = disc.evaluate(c, cand)
            if jobs is not None:
                p = {**p, "jobs": len(jobs), "israel_jobs": israel_count(jobs), "fail_count": 0,
                     "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
                kept[c["id"]] = p
                continue
            p["fail_count"] = p.get("fail_count", 0) + 1
            if p["fail_count"] < 3:
                kept[c["id"]] = p
                continue
        todo.append(c)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for c, r in zip(todo, ex.map(disc.resolve, todo)):
            kept[c["id"]] = r
            print(f"{r['status']:6s} {c['name']:32s} {r.get('ats', '-'):16s} {r.get('token') or r.get('tenant') or ''} "
                  f"jobs={r.get('jobs', '-')} il={r.get('israel_jobs', '-')}")

    kept = {k: v for k, v in kept.items() if v}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "companies": kept},
                                   ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    by = {"ok": [], "review": [], "none": []}
    for cid, r in kept.items():
        by.setdefault(r["status"], []).append((cid, r))
    lines = [f"# Discovery report\n", f"- ok: {len(by['ok'])}\n- review: {len(by['review'])}\n- none: {len(by['none'])}\n"]
    for title, key in (("Needs review (found but ambiguous)", "review"), ("Not found (custom site / unknown ATS)", "none")):
        lines.append(f"\n## {title}\n")
        for cid, r in sorted(by[key]):
            lines.append(f"- **{r['name']}** (`{cid}`) {r.get('ats', '')} {r.get('token', '')} {r.get('note', '')}")
    lines.append("\n## Resolved\n")
    for cid, r in sorted(by["ok"]):
        lines.append(f"- {r['name']}: {r['ats']} `{r.get('token') or r.get('tenant')}` jobs={r.get('jobs')} israel={r.get('israel_jobs')}")
    Path(a.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"done: ok={len(by['ok'])} review={len(by['review'])} none={len(by['none'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
