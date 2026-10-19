"""One fetcher per applicant-tracking system.

Contract:  Fetcher(http).list_jobs(company_cfg) -> list[Job]      (cheap, one or few requests)
           Fetcher(http).enrich(job, company_cfg) -> Job          (detail request, only for new jobs)
Date semantics are recorded in Job.date_kind so alerts never present a refresh as a first publication.
"""
from .ashby import Ashby
from .comeet import Comeet
from .greenhouse import Greenhouse
from .lever import Lever
from .linkedin import LinkedIn
from .recruitee import Recruitee
from .smartrecruiters import SmartRecruiters
from .workable import Workable
from .workday import Workday

FETCHERS = {
    "greenhouse": Greenhouse,
    "lever": Lever,
    "ashby": Ashby,
    "comeet": Comeet,
    "smartrecruiters": SmartRecruiters,
    "workable": Workable,
    "recruitee": Recruitee,
    "workday": Workday,
    "linkedin": LinkedIn,
}
