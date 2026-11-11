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
            r"back[\s-]?end", r"full[\s-]?stack", r"\b(software|sw)\s+(engineer|developer|dev)\b",
            r"\bdeveloper\b", r"\bsde\b", r"\bprogrammer\b",
            r"secur", r"cyber", r"appsec", r"\bapp\s+sec\b", r"\bx?soar\b", r"חדירות", r"\bsoc\b", r"threat", r"vulnerab", r"penetration",
            r"pen[\s-]?test", r"red[\s-]?team", r"\bdfir\b", r"incident\s+response", r"malware",
            r"reverse\s+engineer", r"exploit", r"\bcrypto", r"\bdevsecops\b",
            # malware / detection / forensics research (Nov 2026: the user asked for malware analyst/researcher and similar)
            r"נוזק", r"\bdetection\b", r"incident\s+respond", r"forensic", r"פורנזי",
            r"\bcti\b", r"threat\s+(intel|hunt)", r"\bioc\b", r"sandbox\s+(researcher|engineer)", r"\bedr\b", r"\bxdr\b",
            r"חוקר[./]?ת?\s+(סייבר|נוזקות|איומים|חולשות|אבטחה)", r"מחקר\s+(סייבר|איומים|נוזקות)",
            # not bare "System(s) Engineer": IT/infrastructure or hardware systems engineering, 👎 on all 6 sent
            # (Bynet, Elbit, Flex, Triarii, QualityAI HMS); Intel's liked "System Validation and Integration
            # Engineer" still passes as an integration engineer
            r"systems?\s+(programmer|developer|software)", r"low[\s-]?level", r"kernel",
            r"infrastructure\s+(software\s+)?engineer", r"platform\s+engineer",
            r"front[\s-]?end", r"\breact\b", r"\bangular\b", r"\bvue(\.?js)?\b", r"web\s+(developer|engineer)",
            r"\bc\+\+", r"\bgolang\b", r"\brust\b", r"\bpython\b", r"\bjava\b", r"\.net\b", r"\bnode(\.?js)?\b",
            # software integration / implementation (incl. AI solutions); hardware integrators are excluded below
            r"integration\s+(engineer|specialist|developer|consultant)",
            # customer-facing technical delivery at software/cyber companies (deploy, configure, integrate)
            r"professional\s+services\s+(engineer|consultant|specialist)", r"(deployment|onboarding|technical\s+services)\s+engineer",
            r"\b(software|api|saas|data|cloud|platform|backend|crm|erp)\s+integration", r"implementation",
            r"\bai\s+(solutions?|engineer|developer|specialist|implementation)",
            # any AI/LLM/agent role title: "AI Productivity Engineer", "AI Automation Developer", "LLM Agents Engineer"
            r"\b(?:ai|llm|genai|gen[\s-]?ai|agentic)\b[\w\s&/,.-]{0,30}\b(?:engineer|developer|specialist)\b",
            # DevOps / cloud (also misspelled "Devope" / "Dev Ops": LSports, Nov 2026)
            r"\bdev[\s-]?op(e|p)?s?\b", r"\bcloud\s+(engineer|developer|specialist)", r"\bsre\b", r"site\s+reliability",
            # QA / test automation (software only: industrial "automation engineer" and silicon validation are not)
            r"\bqa\b", r"quality\s+assurance", r"\b(software|sw)\s+(test|testing|validation|verification)",
            r"\btest(ing)?\s+(engineer|automation|developer)", r"(qa|test)\s+automation", r"automation\s+developer", r"\bsdet\b",
            # "Software Automation Engineer" is test automation (Medtronic, Cognyte); bare "Automation Engineer" stays out
            r"\b(software|sw)\s+automation",
            # "Software Development Engineer" (SDE), "Software Quality Engineer", "Offensive Researcher", "Development Operations"
            r"\b(software|sw)\s+development\s+engineer", r"\b(software|sw)\s+quality\s+(engineer|assurance)",
            r"\boffensive\b", r"development\s+operations",
            r"מפתח", r"מפתחת", r"אבטחת", r"סייבר", r"בק[\s-]?אנד", r"פולסטאק", r"הנדס(ת|ן|[/.]ת)?\s*תוכנה",
            r"בודק[./]?ת?\s+(תוכנה|אוטומציה)", r"אינטגרציי?ת\s+תוכנה", r"אוטומציה\s+(qa|בדיקות)", r"\bsecops\b", r"\bfde\b", r"forward[\s-]deployed",
        ],
        "role_exclude": [
            r"\bsales\b", r"account\s+(executive|manager)", r"marketing", r"recruit", r"talent\s+acqui",
            r"\bhr\b", r"human\s+resources", r"\bpeople\b", r"finance", r"accountant", r"\blegal\b", r"counsel",
            r"customer\s+(success|support)", r"support\s+engineer", r"product\s+manager", r"product\s+design",
            r"\bux\b", r"\bui\b", r"designer", r"business\s+develop", r"\bbdr\b", r"\bsdr\b",
            r"office\s+manager", r"assistant", r"developer\s+(advocate|relations)", r"evangelist",
            r"pre[\s-]?sales", r"technical\s+writer", r"security\s+guard", r"\bguard\b", r"\bgrc\b", r"compliance",
            r"mechanical", r"electrical", r"hardware", r"\bfpga\b", r"\basic\b", r"physical\s+security",
            # hardware / electronics (the user is after computer-science roles only)
            r"\bintegrator\b", r"electronic", r"\bpcb\b", r"\brf\b", r"avionic", r"silicon", r"physical\s+design",
            r"field\s+(service\s+)?engineer", r"\bplc\b", r"\bpcie\b", r"\bddr\b", r"\bclocks?\b", r"design\s+automation",
            r"\bradar\b", r"lidar", r"camera\s+system", r"\bgtm\b", r"go[\s-]to[\s-]market", r"strategist",
            r"flight\s+test", r"\besm\b",
            r"\bsoc\s+(design|verification|validation|architect)", r"signal\s+processing", r"\bdsp\b",
            r"מכירות", r"שיווק", r"גיוס", r"משאבי\s+אנוש", r"שירות\s+לקוחות", r"מנהל\s+מוצר",
            r"אינטגרטור", r"אלקטרוניקה", r"חשמל", r"הדרכה",
            # platform-specific enterprise roles (not general software engineering; Dynamics/COBOL got 👎)
            r"salesforce", r"\bsap\b", r"\babap\b", r"\berp\b", r"dynamics", r"copilot\s+studio", r"power\s+(apps|platform|automate|bi)",
            r"servicenow", r"\bpriority\b", r"sharepoint", r"outsystems", r"\brpg\b", r"cobol", r"magento", r"oracle\s+forms",
            r"wordpress",
            # 👎 Oct 2026: lecturer at Shenkar, CNC programmer, BI developer (data), propulsion (aerospace hardware)
            r"lectur", r"מרצה", r"\bcnc\b", r"numerical\s+control", r"propulsion",
            # BI in any wording (Nogamy "Business Intelligence Developer Qlik Sense" 👎 slipped past "BI Developer")
            r"\bbi\b", r"business\s+intelligence", r"qlik",
            # out of scope: teaching gigs (CYBERLABS "מדריכ/ה סייבר לבני נוער"), IT / help desk / NOC (Nexxen "IT Systems Engineer")
            # (not "NOC" / "IT Operations" alone: "SOC / NOC Analyst" and "NOC Engineer / SRE" are in scope)
            r"מדריכ", r"\binstructor", r"\bit\s+(systems?\s+(engineer|administrator)|support|technician|administrator)",
            r"help\s*desk",
            # Nov 2026 review of 126 alerts (user: "many jobs unrelated to CS"): security officers (Elbit/Rafael
            # "ממונה ביטחון"), GIS training, AI content, chip design, MRI protocols, production test, power-plant
            # I&C, railway commissioning, food-QA technologist, pharmacovigilance
            r"ממונה\s+ביטחון", r"קצין\s+ביטחון", r"security\s+officer", r"content\s+specialist",
            r"chip\s+design", r"\bmri\b", r"production\s+test", r"\bi&c\b", r"commissioning", r"technologist",
            r"pharmacovigilance", r"employee\s+experience",
            # Wix "Full stack organic growth marketer", Howden "Cyber Claims Executive", CYBERLABS office admin,
            # IAI "מפתח/ת מערכות אופטיות"
            r"\bmarketer", r"אדמין", r"ניהול\s+משרד", r"אופטי", r"\boptical\b",
            # "Full Stack Developer - Mid Level" (👎); "Junior - Mid Level ..." still passes
            r"^(?!.*junior).*\bmid[\s-]?level",
        ],
        # Companies the user asked never to see (InfinityLabs career-path programs: "תוכנית זבל", Oct 2026)
        "company_exclude": [r"infinity\s*labs"],
        # Integration / QA titles whose text is about hardware are electronics roles, not software:
        # rejected when at least two of these appear in the description.
        "hardware_desc_signals": [
            r"oscilloscope", r"solder", r"\bpcb\b", r"electronic\s+(boards?|lab|components|systems|circuits?)",
            r"electrical\s+engineering", r"\bharness", r"wiring", r"multimeter", r"signal\s+generator",
            r"\brf\b", r"avionics", r"lab\s+equipment", r"schematics?", r"אלקטרוניקה", r"כרטיסים", r"חיווט", r"הנדסת\s+חשמל",
            r"antenna", r"electronic\s+warfare", r"\bew\b", r"electro[\s-]?optic", r"mechanical", r"payload", r"\bsonar\b",
            r"airborne", r"\bsensors?\b",
            # KLA "Spare Parts Integration Engineer": practical engineer, opto-mechanical, clean room
            r"clean[\s-]?room", r"spare[\s-]?parts?", r"practical\s+engineer", r"הנדסאי",
            # KLA "System Engineer" (mechanics, motion, robotics), NVIDIA lab infrastructure (racking, cabling,
            # liquid cooling) and "IC Test Engineer" (IC test). Not "HW": Intel's liked "System Validation and
            # Integration Engineer" debugs "across HW/SW/FW boundaries"
            r"\bmechanics\b", r"\brobotics\b", r"\bcabling\b", r"\bracking\b", r"liquid\s+cooling",
            r"\b(ic|asic|fpga)\b",
            r"communications?\s+systems",
            r"טילים", r"כלי\s+טיס", r"מוטס", r"תעופתי", r"אוויוניקה", r"מכ\"?ם",
            # QA of medical devices, drugs and food is product quality, not software (Medinol, SK Pharma 👎)
            r"medical\s+devices?", r"\bfda\b", r"iso[\s-]?13485", r"\bgmp\b", r"\bcapa\b", r"pharma", r"clinical",
            r"\bfood\b", r"raw\s+materials?", r"production\s+line", r"\bmanufacturing\s+(process|floor|line)",
        ],
        # A bare "Research Analyst" is usually market/finance research; it passes the title stage and is
        # kept only when the description is about security (Upwind's entry-level Research Analyst)
        "ambiguous_titles": [r"\bresearch\s+analyst\b"],
        # Bare "Automation Engineer": the user wants it at software companies (2026-11-06), but the title also means
        # industrial automation, so the description decides
        "automation_titles": [r"\bautomation\s+engineer"],
        "automation_desc_signals": [
            r"selenium", r"playwright", r"cypress", r"appium", r"pytest", r"\bpython\b", r"\bjava\b", r"javascript", r"typescript",
            r"\bc#", r"\bgolang\b", r"ci/cd", r"jenkins", r"terraform", r"ansible", r"rest\s+api", r"\bqa\b",
            r"test\s+(automation|framework|script|plan|case)", r"automated\s+test", r"automation\s+(framework|test)",
        ],
        # A junior title that names no field ("Junior-Mid Engineer" at Backslash Security, Nov 2026): the description
        # decides, so it passes only when it reads as software work and not hardware/electronics. Only fully bare
        # titles: "Junior Verification/DFT/RTL Engineer" name a (chip) field and stay out
        "junior_generic_titles": [r"^\W*(junior|jr\.?|graduates?|new[\s-]?grads?|entry[\s-]?level)(\s*[-/–]\s*mid(\s*level)?)?\s+(engineer|developer)\b\W*$"],
        "junior_generic_desc_signals": [
            r"back[\s-]?end", r"front[\s-]?end", r"full[\s-]?stack", r"micro[\s-]?services?", r"\bapis?\b", r"software\s+(engineer|develop)",
            r"\bpython\b", r"\bjava\b", r"typescript", r"javascript", r"\bnode(\.?js)?\b", r"\bgolang\b", r"\bc#", r"\breact\b",
            r"kubernetes", r"\bdocker\b", r"ci/cd", r"\bcloud\b", r"\bsaas\b",
        ],
        "automation_desc_exclude": [r"\bplcs?\b", r"\bscada\b", r"\bhmi\b", r"industrial\s+automation", r"\bmanufacturing\b", r"production\s+line"],
        "ambiguous_desc_signals": [r"\bsecurity\b", r"\bcyber", r"\bthreats?\b", r"vulnerabilit", r"\bsoc\b", r"malware",
                                   r"סייבר", r"אבטחת\s+מידע"],
        # defense "System Engineer" is usually multidisciplinary hardware systems engineering
        "hardware_check_titles": [r"integrat", r"implementation", r"\bqa\b", r"quality\s+assurance", r"test", r"validation", r"verification",
                                  r"\bsystems?\s+engineer"],
        # When a posting states no years, senior wording still gives it away (Clover Security's "Security
        # Researcher": "strong ... expertise", "a track record of owning research end-to-end"). At least
        # `senior_desc_threshold` distinct phrases reject the job; measured on 38 alerts, no 👍 job scored 3+.
        "senior_desc_signals": [
            r"\bexpertise\b", r"track\s+record", r"proven\s+(\w+\s+){0,2}(experience|ability|track|record)",
            r"extensive\s+(experience|knowledge|background)",
            r"deep\s+(\w+\s+){0,2}(knowledge|expertise|understanding|experience)", r"in[\s-]depth\s+(knowledge|experience|understanding)",
            # "Deep production experience", "Strong professional experience", "production-grade" (Nisha Pro full stack, 4+ yrs Java)
            r"strong\s+professional\s+experience", r"production[\s-]grade",
            r"strong\s+(background|expertise)", r"\bseasoned\b", r"senior[\s-]level",
            r"end[\s-]to[\s-]end\s+ownership|owning\s+[^.]{0,30}end[\s-]to[\s-]end", r"\bmentor", r"lead\s+(the\s+)?(design|architecture|research|projects?)",
            r"ניסיון\s+מוכח", r"ניסיון\s+(רב|נרחב|עשיר)", r"ידע\s+(נרחב|מעמיק|רחב)", r"היכרות\s+מעמיקה", r"מומחיות", r"שליטה\s+מלאה",
        ],
        "senior_desc_threshold": 3,
        # "CodeValue is looking for an experienced Cybersecurity Consultant": an opening that asks for an experienced /
        # senior person rejects the job (6 past alerts matched: 2 marked 👎, none 👍)
        "experienced_intro_signals": [
            # "You're a fit if: You're a senior React engineer who has shipped..." (Robotic Imaging full stack, 👎)
            r"\byou(?:'|’)?re\s+(?:a|an)\s+(?:senior|staff|principal)\b", r"\byou\s+are\s+(?:a|an)\s+(?:senior|staff|principal)\b",
            r"(looking\s+for|seeking|hiring|searching\s+for|in\s+search\s+of)\s+(an?\s+)?(highly\s+|very\s+)?(experienced|senior|seasoned)\b",
            r"(דרוש|מחפשים|מגייסים|מחפשת|מגייסת)[^.\n]{0,25}(מנוסה|מנוסים|בכיר|בכירה)",
        ],
        # freelance / hourly consulting is not a job; "contract role" stays (two liked Alignerr roles were contracts)
        "freelance_signals": [r"\bfreelance(r)?\b", r"פרילנס"],  # checked in the title and the description
        # Adjacent fields: excluded only when the title names no core development role, so
        # "Software developer and DevOps engineer" passes while "DevOps Engineer" does not.
        "role_exclude_soft": [
            r"data\s+scien", r"machine\s+learning", r"\bml\b", r"data\s+analyst",
            r"solutions?\s+(architect|engineer|consultant)", r"\bios\b", r"android", r"\bmobile\b",
            r"manual\s+(qa|test)",
            # network administration (switches/routers) is IT, not software
            r"\bnetwork(ing)?\s+(engineer|administrator|admin|specialist|technician)", r"תקשורת",
            # 👎 on every one so far: "Network Security Engineer" (firewall administration, 2/2), consultants
            # (security / implementation / offensive consultant, 6/6), administrators (Kyndryl network & security)
            r"network\s+security\s+(engineer|administrator|specialist)", r"\bconsultant\b", r"administrator",
            # "GIS Training & Implementation Specialist"; "Software Engineer (AI Training)" still passes (liked Alignerr roles)
            r"\btraining\b",
            # Howden "Cyber Claims Executive" (insurance); "Claims Automation Developer" still passes
            r"\bclaims?\b",
            # Viz.ai "Clinical AI Specialist" 👎 (medical annotation); "Clinical Software Engineer" still passes
            r"\bclinical\b",
            # EY "מתמחה לתחום הביקורת החקירתית ... Forensics" 👎 (accounting degree required; matched "Forensic")
            r"ביקורת\s+ה?חקירתית|forensic\s+(accounting|audit)|financial\s+forensic",
        ],
        "role_core": [
            r"\b(software|sw)\s+(engineer|developer|dev)\b", r"\bdeveloper\b", r"\bprogrammer\b", r"back[\s-]?end",
            r"full[\s-]?stack", r"front[\s-]?end", r"מפתח", r"מפתחת", r"הנדס(ת|ן|[/.]ת)?\s*תוכנה",
            r"\b(software|sw)\s+development\s+engineer",
            # security research on a platform: "Mobile Security Researcher", "Android Vulnerability Researcher"
            r"\b(security|vulnerability|malware|threat)\s+research",
        ],
        "seniority_exclude": [
            r"\bsenior\b", r"\bsr\b\.?", r"\bstaff\b", r"\bprincipal\b", r"\blead\b", r"\bhead\b",
            r"\bdirector\b", r"\bvp\b", r"vice\s+president", r"\bchief\b", r"\bmanager\b", r"\barchitect\b",
            r"\bdistinguished\b", r"\bfellow\b", r"\bexperienced\b", r"\bexpert\b", r"\bfounding\b", r"\biii\b", r"\biv\b", r"\blevel\s*[3-9]\b", r"\bl[4-9]\b",
            r"בכיר", r"בכירה", r"ראש\s+צוות", r"מנהל", r"מנהלת", r"ארכיטקט", r"מנוס(ה|ים|ות)",
            # Hebrew for "Expert": 4 👎 and no 👍; Elbit's asks for a year as a cyber architect
            r"מומח(ה|ית|ים)",
            # SOC above Tier 1 (the user wants T1); "Tier 1/2" and "L1/L2" stay
            r"\bsoc\b.*(?<!/)\b(tier|t|l)[\s-]?[23]\b", r"(?<!/)\b(tier|t|l)[\s-]?[23]\b.*\bsoc\b",
        ],
        "entry_signals": [
            r"\bjunior\b", r"\bjr\b\.?", r"\bgraduates?\b", r"\bgrads?\b", r"new[\s-]?grad", r"entry[\s-]?level",
            r"early[\s-]?career", r"\btrainee\b", r"\bapprentice\b", r"\bcadet\b", r"university\s+hire",
            r"ג['׳’‘]?ו?ניור", r"בוגר", r"בוגרת", r"בוגרי", r"ללא\s+ניסיון", r"מתחיל", r"\bטרי\b",
        ],
        "internship_signals": [r"\bintern(ship)?s?\b", r"(?<!עם\s)(?<!ב)התמחות(?!\s*ב)", r"מתמחה", r"מתמחים", r"\bco-?op\b"],
        "student_signals": [r"\bstudents?\b", r"סטודנט", r"סטודנטית", r"משרת\s+סטודנט"],
        # internships open only to people still studying: the user has graduated (Microsoft Security Research 👎, Nov 2026)
        "current_student_signals": [
            r"currently\s+(?:pursuing|enrolled|studying)(?![^.\n]{0,60}\b(?:recent(?:ly)?|completed|graduated)\b)",
            r"\bcurrent\s+(?:university\s+|college\s+)?students?\b", r"\bstudent\s+position\b",
            r"must\s+be\s+(?:a\s+|an\s+)?(?:\w+\s+)?student\b", r"upon\s+completion\s+of\s+the\s+academic\s+degree",
            r"סטודנט\S*\s+(?:פעיל|לתואר|בשנה|בשנת)",
        ],
        "desc_entry_signals": [
            r"no\s+(prior\s+)?(professional\s+|work\s+)?experience\s+(is\s+)?(required|needed|necessary)",
            r"fresh(ly)?\s+graduates?", r"recent\s+graduates?", r"new\s+graduates?", r"0\s*[-–to]+\s*1\s+years?",
            r"entry[\s-]?level", r"ללא\s+ניסיון", r"בוגרי\s+תואר", r"בוגרים\s+טריים", r"לא\s+נדרש\s+ניסיון",
            # "Talented graduates and junior engineers are welcome to apply" (EyeContact, Oct 2026)
            r"(graduates?|juniors?|junior\s+(engineers?|developers?))\b[^.]{0,40}\b(are\s+)?(welcome|encouraged|invited)\s+to\s+apply",
            # "Junior & Early-Career Candidates Welcome" (a heading, no "to apply")
            r"\b(junior|early[\s-]career|entry[\s-]level|graduates?)\b[^.\n]{0,30}\b(candidates?|applicants?)\s+(are\s+)?welcome\b",
            r"(welcome|encourage)s?\s+(applications\s+from\s+)?[^.]{0,30}\b(graduates?|juniors?)\b",
            r"suitable\s+for\s+(recent\s+)?(graduates?|juniors?)",
            r"\bor\s+an?\s+(?:strong\s+|recent\s+|talented\s+|exceptional\s+)?(?:graduate|student)",
            r"מתאים\s+(גם\s+)?ל(בוגרים|ג['׳’‘]?וניורים|מתחילים)", r"ג['׳’‘]?וניורים\s+(מוזמנים|יתקבלו)",
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
        # LinkedIn public (logged-out) job search. A 24h study (Oct 2026) of 373 Israeli tech postings found
        # that queries narrowed with f_E (LinkedIn's entry/internship label) reached only 21 of 65 jobs whose
        # titles fit: posters often label junior roles "Not Applicable" or "Mid-Senior". So queries are broad
        # and unfiltered, newest first, and the Classifier decides seniority from the title and text.
        "linkedin": {
            "enabled": False,           # switched on in config.yaml
            "tier": 1,
            "geo_id": "101620260",      # Israel
            # The guest search ignores sortBy=DD: with a 24h window page 1 held 21h-old postings and a job
            # posted 30 minutes earlier was not on it. So each run reads the whole last-hour window
            # (typically 6-25 results per query), page by page until a short page.
            "time_window": "r3600",
            "pages": 4,                 # 10 results per page; stops early at the first short page
            "gap_seconds": 5,           # LinkedIn returns 429 on bursts faster than this
            "cooldown_seconds": 25,
            "queries": [
                # explicit junior wording first: each query's alerts are sent as soon as it is read
                {"keywords": 'junior OR graduate OR "entry level" OR student OR intern'},
                {"keywords": "software engineer OR software developer"},
                {"keywords": "backend OR back end"},
                {"keywords": "full stack OR fullstack OR frontend OR front end"},
                {"keywords": "developer"},
                {"keywords": "security OR cyber OR SOC OR penetration"},
                {"keywords": "malware OR appsec OR \"application security\" OR \"reverse engineering\" OR SOAR"},
                {"keywords": "embedded OR firmware OR C++ OR Linux"},
                {"keywords": "python OR java OR node OR golang"},
                {"keywords": "react OR angular OR mobile OR iOS"},
                {"keywords": "ג'וניור OR מפתח OR מפתחת OR סטודנט"},
                {"keywords": "\"integration engineer\" OR \"integration specialist\" OR implementation"},
                {"keywords": "devops OR cloud OR QA OR automation"},
                # employers whose own career sites are behind bot challenges (Reblaze / Cloudflare): every new post
                {"keywords": '"Rafael Advanced Defense Systems"'},
                {"keywords": '"Israel Aerospace Industries" OR Elta'},
                {"keywords": '"Malam Team" OR MalamTeam'},
            ],
            # Catch-up: a job missed in its first hour (a 429 block, or LinkedIn indexing it late) never comes
            # back in the last-hour window. Once an hour the junior-relevant queries also read the last 6 hours;
            # jobs already in state are skipped, so only missed ones alert. A Junior Full Stack job (Nov 2026)
            # was never seen by the hourly searches. 6h: a 24h window held 190-475 results per query.
            "catchup": {
                "every_n_runs": 12,     # runs are 5 minutes apart: hourly
                "time_window": "r21600",
                "pages": 10,
                "queries": [
                    {"keywords": 'junior OR graduate OR "entry level" OR student OR intern'},
                    {"keywords": "full stack OR fullstack OR frontend OR front end"},
                    {"keywords": "backend OR back end"},
                    {"keywords": "software engineer OR software developer"},
                ],
            },
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
