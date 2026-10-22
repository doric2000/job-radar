"""One fetcher per applicant-tracking system.

Contract:  Fetcher(http).list_jobs(company_cfg) -> list[Job]      (cheap, one or few requests)
           Fetcher(http).enrich(job, company_cfg) -> Job          (detail request, only for new jobs)
Date semantics are recorded in Job.date_kind so alerts never present a refresh as a first publication.
"""
from .amazon import Amazon
from .ashby import Ashby
from .checkpoint import CheckPoint
from .comeet import Comeet
from .eightfold import Eightfold
from .elad import Elad
from .greenhouse import Greenhouse
from .htmllinks import HtmlLinks
from .lever import Lever
from .linkedin import LinkedIn
from .manatal import Manatal
from .radancy import Radancy
from .recruitee import Recruitee
from .smartrecruiters import SmartRecruiters
from .topmatch import TopMatch
from .workable import Workable
from .wordpress import WordPress
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
    "amazon": Amazon,
    "eightfold": Eightfold,
    "checkpoint": CheckPoint,
    "elad": Elad,
    "wordpress": WordPress,
    "manatal": Manatal,
    "htmllinks": HtmlLinks,
    "topmatch": TopMatch,
    "radancy": Radancy,
}
