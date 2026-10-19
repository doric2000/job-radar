from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Job:
    company_id: str
    company: str
    job_id: str
    title: str
    url: str
    location: str = ""
    description: str = ""
    posted_at: Optional[datetime] = None  # timezone-aware, UTC
    # published | created | updated | relative | unknown
    date_kind: str = "unknown"
    date_source: str = ""
    remote: Optional[bool] = None
    employment: str = ""  # e.g. "Full-time", "Intern" as reported by the source
    level: str = ""  # experience level label reported by the source, if any
    source: str = ""  # ats name

    @property
    def key(self) -> str:
        return f"{self.company_id}:{self.job_id}"


@dataclass
class Verdict:
    accept: bool
    tier: str = ""  # A = explicit entry-level, B = up to 1y, C = up to 2y
    region: str = ""  # israel | remote | relocation
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    tags: list = field(default_factory=list)  # clearance, internship
    reject_reason: str = ""
    req_years: Optional[int] = None
    exp_snippet: str = ""
    stage: int = 2  # 1 = title/location only, 2 = full (with description)
