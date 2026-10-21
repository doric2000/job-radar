import unittest

from radar.config import load_config
from radar.filters import Classifier, extract_experience, extract_requirements, extract_summary
from radar.models import Job


def J(title, loc="Tel Aviv, Israel", desc="", **kw):
    return Job(company_id="x", company="X", job_id="1", title=title, url="http://x", location=loc, description=desc, **kw)


class TestExperience(unittest.TestCase):
    def test_required_years(self):
        yrs, snip, opt = extract_experience("We need:\n• 3+ years of backend experience\n• BSc in CS")
        self.assertEqual(yrs, 3)
        self.assertIn("3+ years", snip)

    def test_range_uses_lower_bound(self):
        yrs, _, _ = extract_experience("1-3 years of experience in software development")
        self.assertEqual(yrs, 1)

    def test_preferred_is_not_required(self):
        txt = "Requirements:\n• BSc in CS\nNice to have:\n• 4 years of experience with Kubernetes"
        yrs, _, opt = extract_experience(txt)
        self.assertIsNone(yrs)
        self.assertEqual(opt, [4])

    def test_inline_preferred(self):
        yrs, _, opt = extract_experience("2 years of experience in Python is an advantage.")
        self.assertIsNone(yrs)
        self.assertEqual(opt, [2])

    def test_unrelated_years_ignored(self):
        yrs, _, _ = extract_experience("Founded 10 years ago, we are a leading company.")
        self.assertIsNone(yrs)

    def test_word_numbers(self):
        yrs, _, _ = extract_experience("Minimum of two years experience in security research")
        self.assertEqual(yrs, 2)

    def test_hebrew(self):
        self.assertEqual(extract_experience("נדרש ניסיון של 3 שנים בפיתוח צד שרת")[0], 3)
        self.assertEqual(extract_experience("שנתיים ניסיון בפיתוח")[0], 2)
        self.assertEqual(extract_experience("2-3 שנות ניסיון בפיתוח")[0], 2)

    def test_max_across_mandatory(self):
        yrs, _, _ = extract_experience("• 1 year of experience in Python\n• 5 years of experience in software development")
        self.assertEqual(yrs, 5)

    def test_up_to_is_ceiling(self):
        yrs, _, _ = extract_experience("Suitable for candidates with up to 2 years of experience")
        self.assertIsNone(yrs)


class TestHebrewYearsAndRequirements(unittest.TestCase):
    def test_hebrew_year_phrasings(self):
        cases = {"✔️ ניסיון של מעל 3 שנים לפחות בתפקיד DevOps בארגון גדול.": 3, "ניסיון של שנה ומעלה בפיתוח WEB – חובה.": 1,
                 "שלוש שנות ניסיון בפיתוח Java": 3, "ניסיון של כ-5 שנים בפיתוח": 5, "ניסיון של יותר מ-3 שנים בפיתוח": 3,
                 "לפחות שנה ניסיון מעשי בתחום ה-SOC": 1, "ניסיון של שנתיים לפחות ב-Python": 2, "ניסיון בעבודה עם Linux": None}
        for text, years in cases.items():
            self.assertEqual(extract_experience(text)[0], years, text)

    def test_advantage_applies_only_to_its_own_clause(self):
        cases = {"4+ years of proven experience working with Linux (Debian/Ubuntu preferred).": 4,
                 "לפחות 5 שנות ניסיון בניהול והגדרת מתגים ונתבים, יתרון ל-Cisco - חובה": 5,
                 "3 years of experience with Kubernetes - an advantage": None,
                 "ניסיון של שנתיים ב-Python יהווה יתרון": None,
                 "2+ years of experience in Python, Java is a plus": 2,
                 "5+ years of experience in backend development, an advantage for Go": 5}
        for text, years in cases.items():
            self.assertEqual(extract_experience(text)[0], years, text)

    def test_graduate_alternative_path(self):
        text = "At least 3 years of hands-on backend experience, or a strong graduate with serious side projects."
        self.assertIsNone(extract_experience(text)[0])
        v = Classifier(load_config(None)).classify(J("Software Engineer – GCS Team", desc=text))
        self.assertTrue(v.accept, v.reject_reason)
        self.assertEqual(v.tier, "A")
        self.assertEqual(extract_experience("3+ years of Python or Go experience")[0], 3)

    def test_summary_prefers_role_section_and_skips_marketing(self):
        desc = ("Acme is a leading provider of cloud security.\nAbout the role:\nBuild detection pipelines in Python\n"
                "Own services end to end\nRequirements:\n- BSc in CS")
        self.assertEqual(extract_summary(desc), ["Build detection pipelines in Python", "Own services end to end"])
        plain = "Location: Tel Aviv\nWe are a leading company in fintech.\nYou will build backend services in Go for payments."
        self.assertEqual(extract_summary(plain), ["You will build backend services in Go for payments."])

    def test_requirements_section(self):
        desc = ("חברת X מגייסת DevOps\nמה אנחנו מחפשים?\n✔️ 2+ שנות ניסיון ב-AWS\n✔️ ניסיון ב-Kubernetes\n"
                "מעוניינים? שלחו קורות חיים!")
        self.assertEqual(extract_requirements(desc), ["2+ שנות ניסיון ב-AWS", "ניסיון ב-Kubernetes"])
        en = "About\nWe build.\nRequirements:\n- BSc in CS\n- 1+ years with Go\nBenefits:\n- Food"
        self.assertEqual(extract_requirements(en), ["BSc in CS", "1+ years with Go"])


class TestClassifier(unittest.TestCase):
    def setUp(self):
        self.c = Classifier(load_config(None))

    def test_graduates_welcome_to_apply_in_description(self):
        desc = ("EyeContact is looking for a Software Engineer to join our team full-time, on-site in Rehovot. "
                "Talented graduates and junior engineers are welcome to apply and help build a meaningful product.")
        v = self.c.classify(J("Software Engineer", loc="Rehovot, Center District, Israel", desc=desc))
        self.assertTrue(v.accept, v.reject_reason)
        self.assertEqual(v.tier, "A")

    def test_mentoring_juniors_is_not_an_entry_signal(self):
        v = self.c.classify(J("Software Engineer", desc="You will mentor junior engineers and own our backend."))
        self.assertFalse(v.accept)

    def test_junior_title(self):
        v = self.c.classify(J("Junior Backend Engineer"))
        self.assertTrue(v.accept)
        self.assertEqual(v.tier, "A")
        self.assertEqual(v.region, "israel")

    def test_senior_rejected(self):
        v = self.c.classify(J("Senior Backend Engineer", desc="1 year of experience"))
        self.assertFalse(v.accept)
        self.assertIn("seniority", v.reject_reason)

    def test_generic_title_with_one_year(self):
        v = self.c.classify(J("Software Engineer", desc="Requirements:\n• 1+ years of experience in Python"))
        self.assertTrue(v.accept)
        self.assertEqual(v.tier, "B")

    def test_generic_title_two_years(self):
        v = self.c.classify(J("Security Engineer", desc="Requirements:\n• 2 years of experience in AppSec"))
        self.assertTrue(v.accept)
        self.assertEqual(v.tier, "C")

    def test_generic_title_three_years_rejected(self):
        v = self.c.classify(J("Backend Developer", desc="Requirements:\n• 3+ years of experience"))
        self.assertFalse(v.accept)
        self.assertIn("requires 3", v.reject_reason)

    def test_generic_title_no_signal_rejected_by_default(self):
        v = self.c.classify(J("Software Engineer", desc="Join our awesome team."))
        self.assertFalse(v.accept)
        self.assertEqual(v.reject_reason, "no experience signal")

    def test_unspecified_can_be_enabled(self):
        cfg = load_config(None)
        cfg["match"]["include_unspecified_experience"] = True
        v = Classifier(cfg).classify(J("Software Engineer", desc="Join our awesome team."))
        self.assertTrue(v.accept)
        self.assertTrue(v.warnings)

    def test_role_exclusions(self):
        for t in ["Junior Sales Development Rep", "Junior Product Manager", "Junior UX Designer",
                  "Junior Data Scientist", "Security Guard", "Manual QA Tester"]:
            self.assertFalse(self.c.classify(J(t)).accept, t)

    def test_experienced_and_expert_titles_are_senior(self):
        for t in ["Experienced Backend Engineer", "Expert Frontend Engineer"]:
            self.assertFalse(self.c.stage1(J(t)).accept, t)

    def test_hebrew_and_ops_titles(self):
        for t in ["בודק/ת תוכנה DIGITAL", "איש/אשת SecOps", "AI FDE", "מפתח/ת תוכנה Full Stack ג'וניור"]:
            self.assertTrue(self.c.stage1(J(t)).accept, t)
        self.assertFalse(self.c.stage1(J("מפתח/ת הדרכה ולמידה דיגיטלית")).accept)

    def test_sw_abbreviation(self):
        for t in ["Junior SW Engineer - Virtual Platforms", "SW Engineer - Enterprise Browser team"]:
            self.assertTrue(self.c.stage1(J(t)).accept, t)

    def test_adjacent_field_with_core_dev_role_passes(self):
        for t in ["Software developer and DevOps engineer", "iOS Developer", "React Native Developer"]:
            self.assertTrue(self.c.stage1(J(t)).accept, t)
        for t in ["Junior iOS Engineer", "Junior Data Scientist", "Sales Engineer"]:
            self.assertFalse(self.c.stage1(J(t)).accept, t)

    def test_integration_devops_and_qa_families(self):
        for t in ["Integration Specialist", "Integration Engineer", "AI Solutions & Implementation Specialist",
                  "API Integration Developer", "DevOps Engineer", "Cloud Engineer", "Junior QA Engineer",
                  "QA Automation Engineer", "Software Validation Engineer"]:
            self.assertTrue(self.c.stage1(J(t)).accept, t)

    def test_hardware_integrators_excluded(self):
        for t in ["System Integrator", "Network & Linux Integrator", "Field Engineering and Integration",
                  "אינטגרטור.ית בתחום האלקטרוניקה", "Embedded Integrator - Temporary", "Silicon Validation Engineer",
                  "Automation Engineer", "PCIe System Integration Engineer", "SoC Clocks Design Automation Engineer",
                  "Signal Processing & AI Engineer"]:
            self.assertFalse(self.c.stage1(J(t)).accept, t)
        self.assertTrue(self.c.stage1(J("Junior SOC Analyst")).accept)
        for t in ["מומחה/ית תקשורת ואבטחת מידע", "Network Engineer"]:
            self.assertFalse(self.c.stage1(J(t)).accept, t)
        self.assertTrue(self.c.stage1(J("Network Security Researcher")).accept)

    def test_integration_with_hardware_text_rejected(self):
        desc = "Integrate electronic boards in the lab, work with oscilloscope and wiring harness, read schematics."
        v = self.c.classify(J("Integration Engineer", desc=desc))
        self.assertEqual((v.accept, v.reject_reason), (False, "hardware/electronics role"))
        v = self.c.classify(J("Junior Integration Engineer", desc="Build REST API integrations between our SaaS platform and customer CRMs."))
        self.assertTrue(v.accept, v.reject_reason)

    def test_frontend_included(self):
        for t in ["Junior Frontend Developer", "Angular Developer", "Junior React Engineer",
                  "Junior Full Stack Developer (Frontend focus)"]:
            self.assertTrue(self.c.stage1(J(t)).accept, t)

    def test_internship_included(self):
        v = self.c.classify(J("Security Research Intern"))
        self.assertTrue(v.accept)
        self.assertIn("internship", v.tags)

    def test_student_parttime_excluded_by_default(self):
        self.assertFalse(self.c.classify(J("Backend Developer - Student Position")).accept)

    def test_clearance_tag(self):
        v = self.c.classify(J("Junior Software Engineer", desc="Candidates must hold a security clearance"))
        self.assertTrue(v.accept)
        self.assertIn("clearance", v.tags)
        v = self.c.classify(J("מפתח/ת תוכנה בוגר/ת", loc="תל אביב", desc="נדרש סיווג ביטחוני"))
        self.assertIn("clearance", v.tags)

    def test_hebrew_title(self):
        v = self.c.classify(J("מפתח/ת Backend - בוגרי תואר", loc="פתח תקווה"))
        self.assertTrue(v.accept)

    def test_location_scope(self):
        self.assertFalse(self.c.classify(J("Junior Backend Engineer", loc="New York, NY")).accept)
        self.assertFalse(self.c.classify(J("Junior Backend Engineer", loc="Remote - US")).accept)
        v = self.c.classify(J("Junior Backend Engineer", loc="Remote (EMEA)"))
        self.assertTrue(v.accept)
        self.assertEqual(v.region, "remote")
        v = self.c.classify(J("Junior Backend Engineer", loc="Berlin, Germany", desc="Relocation support provided"))
        self.assertTrue(v.accept)
        self.assertEqual(v.region, "relocation")

    def test_title_junior_but_desc_requires_years_gets_warning(self):
        v = self.c.classify(J("Junior Backend Engineer", desc="Requirements:\n• 4 years of experience in backend"))
        self.assertTrue(v.accept)
        self.assertTrue(any("4" in w for w in v.warnings))

    def test_desc_entry_phrase(self):
        v = self.c.classify(J("Software Engineer", desc="No prior experience required. Fresh graduates welcome."))
        self.assertTrue(v.accept)
        self.assertEqual(v.tier, "A")

    def test_source_level_senior_rejected(self):
        v = self.c.classify(J("Software Engineer", level="Mid-Senior level", desc="1 year"))
        self.assertFalse(v.accept)


if __name__ == "__main__":
    unittest.main()
