"""Tests for answer resolution."""

import tempfile
import unittest
import unittest.mock
from pathlib import Path

import yaml

from jobbot.answers import Resolver, bucket, pick
from jobbot.profile import Profile

from core_fixtures import PROFILE, set_up_workspace


def setUpModule():
    set_up_workspace()


class PickTest(unittest.TestCase):
    def test_male_never_matches_female(self):
        self.assertEqual(pick("Male", ["Female", "Male", "Non Binary"]), 1)

    def test_no_matches_long_option(self):
        opts = ["YES, I am currently or have been employed by PwC", "No, I have not been employed by PwC"]
        self.assertEqual(pick("No", opts), 1)

    def test_no_matches_negative_statement(self):
        opts = ["Please Select", "I have never been employed by Rubrik", "I am currently a full/part-time employee for Rubrik",
                "I was previously a contractor for Rubrik"]
        self.assertEqual(pick("No", opts), 1)
        self.assertIsNone(pick("Yes", opts))   # current or previous: not for a rule to guess

    def test_greenhouse_education_dates(self):
        r = Resolver(Profile({**PROFILE, "education": {"start_month": "2020-09", "end_month": "2024-06"}}, "x"), None, job={})
        self.assertEqual(r.resolve("Start date year", "text", quick=True).value, "2020")   # not "30 days notice"
        self.assertEqual(r.resolve("End date month", "text", quick=True).value, "June")
        self.assertEqual(r.resolve("What year did you graduate in?", "text", quick=True).value, "2024")

    def test_location_comfort_and_last_working_day(self):
        r = Resolver(Profile({**PROFILE, "preferences": {"locations": "hyderabad|bengaluru|bangalore"}}, "x"), None, job={})
        self.assertEqual(r.resolve("Comfortable working in Bangalore location?", "choice", ["Yes", "No"], quick=True).display, "Yes")
        self.assertTrue(r.resolve("If serving, when is your last working day", "text", quick=True).value.startswith("Not applicable"))

    def test_sign_up_password_rules(self):
        from jobbot.apply.auth import meets_rules
        visa = "Password Requirements: A minimum of 12 characters A lowercase character A special character A numeric character An uppercase character"
        self.assertFalse(meets_rules("Short1!aB", visa))
        self.assertTrue(meets_rules("LongerPass12!x", visa))
        self.assertFalse(meets_rules("longerpass12!x", visa))   # no uppercase
        self.assertTrue(meets_rules("Abcdef1!", "A minimum of 8 characters"))

    def test_password_candidates_order_and_dedup(self):
        from unittest.mock import patch
        from jobbot import credentials
        store = {"jobbot job sites:visa.example": "SiteOne1!", "jobbot job sites": "Main1!", "jobbot job sites#2": "Alt2!",
                 "jobbot job sites#3": "Main1!"}
        with patch.object(credentials, "available", return_value=True), \
                patch.object(credentials, "_read", side_effect=lambda service, account: store.get(service)):
            self.assertEqual(credentials.candidates("a@b.c", host="visa.example"), ["SiteOne1!", "Main1!", "Alt2!"])
            self.assertEqual(credentials.get("a@b.c"), "Main1!")

    def test_country_with_dial_code(self):
        self.assertEqual(pick("India", ["British Indian Ocean Territory +246", "India +91"]), 1)

    def test_decline(self):
        self.assertEqual(pick("Decline", ["Yes", "No", "I don't wish to answer"]), 2)

    def test_ambiguous_returns_none(self):
        self.assertIsNone(pick("Engineering", ["Electrical Engineering", "Mechanical Engineering"]))


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.asked = []
        ask = lambda q, opts, req, sug, why: self.asked.append(q) or None
        self.r = Resolver(Profile(PROFILE, "x"), job={"company": "Acme"}, ask=ask)

    def test_open_to_preferred_location(self):
        r = Resolver(Profile({**PROFILE, "preferences": {"locations": "bengaluru|bangalore|pune"}}, "x"),
                     ask=lambda *a: self.asked.append(a[0]))
        self.assertEqual(r.resolve("Are you open for Bangalore location ?", "choice", options=["Yes", "No"]).display, "Yes")
        self.assertEqual(self.asked, [])

    def test_new_profile_fields(self):
        prof = {**PROFILE, "personal": {**PROFILE["personal"], "languages": ["Hindi"], "phone_device_type": "Mobile"},
                "work": {**PROFILE["work"], "outside_business_activities": "No"},
                "eligibility": {**PROFILE["eligibility"], "military_service": "No"},
                "eeo": {**PROFILE["eeo"], "veteran": "I am not a protected veteran"},
                "preferences": {"preferred_work_locations": ["Bengaluru", "Hyderabad"]}}
        r = Resolver(Profile(prof, "x"), ask=lambda *a: self.asked.append(a[0]))
        yn = ["Yes", "No"]
        self.assertEqual(r.resolve("Have you served in the military?", "choice", options=yn).display, "No")
        self.assertEqual(r.resolve("Do you have any outside business activity(ies) (advisory, consulting, or board "
                                   "roles, or side businesses)?", "choice", options=yn).display, "No")
        self.assertEqual(r.resolve("In which language(s) are you fluent (spoken) other than English?", "text").value,
                         "Hindi")
        self.assertEqual(r.resolve("Phone Device Type", "choice", options=["Home", "Mobile"]).display, "Mobile")
        self.assertEqual(r.resolve("What is your preferred work location?", "choice",
                                   options=["New York", "Hyderabad", "London"]).display, "Hyderabad")
        self.assertEqual(r.resolve("Veteran Status", "choice", options=["I am not a protected veteran", "Decline"]).display,
                         "I am not a protected veteran")
        self.assertEqual(self.asked, [])

    def test_amazon_screening_questions(self):
        ranges = ["Less than 1 year", "1 year to less than 2 years", "2 years to less than 3 years",
                  "3 years to less than 4 years", "4 years to less than 5 years", "5 years or more"]
        prof = {**PROFILE, "work": {**PROFILE["work"], "sdlc_experience_years": 3},
                "education": {"cs_or_equivalent": True}, "eligibility": {**PROFILE["eligibility"], "government_employee": "No"}}
        r = Resolver(Profile(prof, "x"), ask=lambda *a: self.asked.append(a[0]))
        yn = ["Yes", "No"]
        q = "Which option best describes your total non-internship professional software development experience?"
        self.assertEqual(r.resolve(q, "choice", options=ranges).display, "2 years to less than 3 years")
        q = ("Which option best describes your total non-internship design or architecture (design patterns, "
             "reliability and scaling) of new and existing systems experience?")
        self.assertEqual(r.resolve(q, "choice", options=ranges).display, "2 years to less than 3 years")
        q = ("Which option best describes your total full software development life cycle, including coding standards, "
             "code reviews, source control management, build processes, testing, and operations experience?")
        self.assertEqual(r.resolve(q, "choice", options=ranges).display, "3 years to less than 4 years")
        q = "Do you have experience programming with at least one software programming language?"
        self.assertEqual(r.resolve(q, "choice", options=yn).display, "Yes")
        q = "Do you have a Bachelor's degree in computer science or equivalent?"
        self.assertEqual(r.resolve(q, "choice", options=yn).display, "Yes")
        for q in ("Are you currently or have you ever been a government employee?",
                  "Have you ever worked for the government or a state-owned entity?",
                  "Are you a current or former government official?"):
            self.assertEqual(r.resolve(q, "choice", options=yn).display, "No", q)
        self.assertEqual(self.asked, [])
        # about a relative, not you: never answered from your own status
        self.assertIsNone(r.resolve("Does any immediate family member work for the government?", "choice", options=yn))

    def test_bucket(self):
        self.assertEqual(bucket(2, ["0-1 years", "1-3 years", "3-5 years", "5+ years"]), 1)
        self.assertEqual(bucket(0.5, ["None", "Less than 1 year", "1+ years"]), 1)
        self.assertIsNone(bucket(2, ["Yes", "No"]))

    def test_eeo_description_does_not_trigger_always_ask(self):
        prof = {**PROFILE, "eeo": {"race": "Asian"}, "always_ask": [r"sanction|\bcuba\b|iran", "citizenship"]}
        r = Resolver(Profile(prof, "x"), ask=lambda *a: self.asked.append(a[0]))
        q = ("Race - A person of Cuban, Mexican, Puerto Rican, South or Central American, or other Spanish culture "
             "or origin regardless of race. - A person having origins in any of the original peoples of Europe, "
             "the Middle East, or North Africa (Iran).")
        opts = ["Hispanic or Latino", "White (Not Hispanic or Latino)", "Asian (Not Hispanic or Latino)",
                "Decline to self-identify"]
        self.assertEqual(r.resolve(q, "choice", options=opts).display, "Asian (Not Hispanic or Latino)")
        self.assertEqual(self.asked, [])
        r.resolve("Are you a resident of Cuba?", "choice", options=["Yes", "No"])
        self.assertEqual(len(self.asked), 1)   # a real sanctions question is still yours

    def test_credentials_and_fact_only_questions(self):
        prof = Profile(PROFILE, "x")
        prof.resume_text = lambda key: "Backend on AWS (Lambda, S3). Certifications: Oracle Certified Java Programmer."
        prof.resumes = lambda: {"backend": {}}

        class FakeLLM:   # would answer anything; must not be consulted for fact-only questions
            enabled, calls = True, []
            def choose(self, q, *a, **k):
                self.calls.append(q)
                return 1
        llm = FakeLLM()
        r = Resolver(prof, llm=llm, ask=lambda *a: self.asked.append(a[0]))
        yn = ["Yes", "No"]
        self.assertEqual(r.resolve("Do you hold a PMP certification?", "choice", options=yn).display, "No")
        self.assertEqual(r.resolve("Do you have a valid AWS certification?", "choice", options=yn).display, "No")
        self.assertEqual(r.resolve("Do you hold an Oracle Certified Java Programmer certification?", "choice",
                                   options=yn).display, "Yes")
        for q in ("Are you a US citizen?", "Have you ever been convicted of a felony?"):
            self.assertIsNone(r.resolve(q, "choice", options=yn, required=True))
        self.assertEqual(llm.calls, [])
        self.assertEqual(len(self.asked), 2)
        self.assertEqual(r.resolve("Are you open to working weekends occasionally?", "choice", options=yn).display, "No")
        self.assertEqual(len(llm.calls), 1)   # preference questions do reach the model

    def test_asks_once_per_application(self):
        # review rounds re-read the page; an unanswered question must not be asked again
        for _ in range(3):
            self.assertIsNone(self.r.resolve("Have you worked with Debezium, PeerDB?", "text", required=True))
        self.assertEqual(len(self.asked), 1)

    def test_basic_fields(self):
        self.assertEqual(self.r.resolve("First Name*").value, "Asha")
        self.assertEqual(self.r.resolve("Preferred Name").value, "Asha")
        self.assertEqual(self.r.resolve("Share your LinkedIn Profile site").value, "https://www.linkedin.com/in/x")

    def test_choices(self):
        ans = self.r.resolve("Will you now or in the future require employment sponsorship?", "choice", ["Yes", "No"])
        self.assertEqual(ans.display, "No")
        ans = self.r.resolve("Have you ever worked at Acme before?", "choice", ["Yes", "No"])
        self.assertEqual(ans.display, "No")
        ans = self.r.resolve("Gender", "choice", ["Select...", "Female", "Male"])
        self.assertEqual(ans.display, "Male")

    def test_custom_answer_wins(self):
        opts = ["YES, I am currently or have been employed by PwC", "No, I have not been employed by PwC"]
        self.assertEqual(self.r.resolve("Are you employed by PwC?", "choice", opts).value, 1)

    def test_always_ask(self):
        self.assertIsNone(self.r.resolve("Name (Signature Field)", required=True))
        self.assertEqual(self.asked, ["Name (Signature Field)"])

    def test_consent_checkbox_not_auto_ticked(self):
        self.assertIsNone(self.r.resolve("I agree to the privacy policy", "checkbox"))


class MemoryTest(unittest.TestCase):
    def test_remember_and_reuse(self):
        from pathlib import Path
        from jobbot.memory import Memory
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.yaml"
            path.write_text("# my profile\npersonal:\n  first_name: Asha  # keep this comment\n")
            m = Memory(path)
            self.assertTrue(m.remember("Are you comfortable working from our Bangalore office 3 days a week?", "Yes"))
            self.assertFalse(m.remember("Why do you want to join Acme?", "x", company="Acme"))
            text = path.read_text()
            self.assertIn("keep this comment", text)
            self.assertIn("learned_answers:", text)
            m.remember("Are you comfortable working from our Bangalore office 3 days a week?", "No")
            self.assertEqual(path.read_text().count("Bangalore office"), 1)   # replaced, not duplicated
            m2 = Memory(path, __import__("yaml").safe_load(path.read_text())["learned_answers"])
            self.assertEqual(m2.lookup("Are you comfortable working from the Bangalore office 3 days a week?"), "No")
            self.assertIsNone(m2.lookup("What is your expected CTC?"))

    def test_resolver_uses_memory_and_hybrid_rule(self):
        from jobbot.memory import Memory
        prof = Profile({**PROFILE, "eligibility": {**PROFILE["eligibility"], "willing_to_relocate": True}}, "x")
        mem = Memory(items=[{"question": "Do you have experience with Kafka in production?", "answer": "Yes"}])
        r = Resolver(prof, job={"company": "Acme"}, memory=mem)
        self.assertEqual(r.resolve("Do you have experience with Kafka in production?", "choice", ["Yes", "No"]).source,
                         "remembered")
        q = "Abnormal AI operates a hybrid working model. This role is based in our Bangalore office. Are you okay with that?"
        self.assertEqual(r.resolve(q, "choice", ["Yes", "No"]).display, "Yes")


class WorkdayQuestionsTest(unittest.TestCase):
    def setUp(self):
        self.r = Resolver(Profile({**PROFILE, "preferences": {"how_did_you_hear": "Company website"}}, "x"),
                          job={"company": "Cisco"}, ask=lambda *a: (_ for _ in ()).throw(AssertionError("asked")))

    def test_how_did_you_hear_never_asks(self):
        self.assertEqual(self.r.resolve("How Did You Hear About Us?*", "choice",
                                        ["Job Board", "Cisco Careers Website", "Referral"]).display, "Cisco Careers Website")
        self.assertEqual(self.r.resolve("How did you hear about us?", "choice", ["Event", "Agency"]).display, "Event")

    def test_employer_history(self):
        q = "Have you ever been issued a Cisco Employee ID or Cisco email address? This includes interns and contractors."
        self.assertEqual(self.r.resolve(q, "choice", ["Yes", "No"]).display, "No")
        r = Resolver(Profile({**PROFILE, "work": {"past_employers": ["Cisco Systems"]}}, "x"), job={"company": "Cisco"})
        self.assertEqual(r.resolve(q, "choice", ["Yes", "No"]).display, "Yes")

    def test_phone_code_answer(self):
        self.assertEqual(self.r.resolve("Country Phone Code*", "choice", ["Indonesia (+62)", "India (+91)"]).display,
                         "India (+91)")


class AnswerResolutionRegressionTests(unittest.TestCase):
    def test_confirmed_facts_ignore_model_and_bad_memory(self):
        from unittest.mock import Mock
        data = {**PROFILE, "personal": {**PROFILE["personal"], "pronouns": "he/him/his"},
                "work": {"expected_ctc": "INR 30 LPA fixed, negotiable based on role and bonus/equity"},
                "education": {"start_month": "2020-09", "end_month": "2024-06", "school_name": "IIT (BHU), Varanasi"},
                "eligibility": {"military_service": "No"}, "eeo": {"veteran": "I am not a protected veteran"}}
        model = Mock(enabled=True)
        memory = Mock()
        memory.lookup.return_value = "Bengaluru"
        resolver = Resolver(Profile(data, "x"), llm=model, memory=memory)
        for question, expected in [("Salary and benefit expectations", data["work"]["expected_ctc"]),
                                   ("Pronouns", "he/him/his"), ("College start date", "2020-09"),
                                   ("College graduation date", "2024-06"), ("University/ College", "IIT (BHU), Varanasi"),
                                   ("Phone Number", "9876543210")]:
            self.assertEqual(resolver.resolve(question).value, expected)
        self.assertEqual(resolver.resolve("Are you a veteran?", "choice", options=["Yes", "No"]).display, "No")
        model.answer.assert_not_called()
        memory.lookup.assert_not_called()

    def test_salary_in_lpa_text_box_gets_the_number(self):
        from jobbot.apply.values import format_value
        prof = Profile({**PROFILE, "work": {**PROFILE["work"], "current_ctc_lpa": 21.1, "expected_ctc_lpa": 30}}, "x")
        self.assertEqual(format_value(prof, {"type": "text"}, "Current CTC in LPA *", "INR 21.1 LPA fixed + bonus"), "21.1")
        self.assertEqual(format_value(prof, {"type": "text"}, "Expected salary (in INR)", "INR 30 LPA"), "3000000")
        self.assertEqual(format_value(prof, {"type": "text"}, "Current salary", "INR 21.1 LPA fixed"), "INR 21.1 LPA fixed")

    def test_not_applicable_follow_up_skips_past_employers(self):
        prof = Profile({**PROFILE, "work": {**PROFILE["work"], "past_employers": ["Salesforce"]}}, "x")
        q = "If so, when were you employed by us and in which team?"
        self.assertIsNone(Resolver(prof, None, job={"company": "Salesforce"}).resolve(q, "text", required=True, quick=True))
        self.assertEqual(Resolver(prof, None, job={"company": "Kong"}).resolve(q, "text", required=True, quick=True).value,
                         "Not applicable")

    def test_remembered_answer_needs_same_meaning(self):
        from jobbot.memory import Memory
        long_q = "Are you willing to relocate to {} for this full time onsite role at our office?"
        m = Memory(items=[{"question": long_q.format("Bangalore"), "answer": "Yes"},
                          {"question": "How Did You Hear About Us?", "answer": "Company website"}])
        self.assertEqual(m.lookup(long_q.format("Bangalore")), "Yes")
        self.assertIsNone(m.lookup(long_q.format("Pune")))                              # another place
        self.assertIsNone(m.lookup(long_q.format("Bangalore").replace("you willing", "you not willing")))  # negation
        self.assertEqual(m.lookup("How did you hear about us?"), "Company website")     # Title Case is not a name

    def test_resume_terms_match_singular_and_plural(self):
        from jobbot.resumes import number_forms
        self.assertEqual(number_forms("distributed system"), {"distributed system", "distributed systems"})
        self.assertEqual(number_forms("distributed systems"), {"distributed system", "distributed systems"})
        self.assertEqual(number_forms("aws"), {"aws"})          # not a plural: never "aw"
        self.assertEqual(number_forms("ios"), {"ios"})
        self.assertIn("api", number_forms("apis"))
        self.assertIn("policy", number_forms("policies"))

    def test_applied_before_closes_its_connection(self):
        from unittest.mock import MagicMock, patch
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [{"company": "Acme"}]
        with patch("jobbot.tracker.connect", return_value=conn):
            ans = Resolver(Profile(PROFILE, "x"), None, job={"company": "Acme"}).resolve(
                "Have you previously applied to Acme?", "choice", ["Yes", "No"], quick=True)
        self.assertEqual(ans.display, "Yes")
        conn.close.assert_called_once()

    def test_yes_to_a_place_uses_this_question_only(self):
        r = Resolver(Profile({**PROFILE, "answers": [{"match": "office", "answer": "Yes"}]}, "x"), None, job={})
        r.resolve("Are you comfortable working from our Bengaluru office?", "choice", ["Bengaluru", "Others"], quick=True)
        # a later question naming no place: its "Yes" must not pick "Bengaluru" from the question before
        self.assertIsNone(r.resolve("Can you work from the office three days a week?", "choice", ["Bengaluru", "Others"], quick=True))

    def test_hear_about_never_claims_an_event_or_linkedin(self):
        r = Resolver(Profile({**PROFILE, "preferences": {"how_did_you_hear": "Company website"}}, "x"), None, job={})
        q = "How did you hear about this job?"
        self.assertEqual(r.resolve(q, "choice", ["Career Fair", "LinkedIn", "Other"], quick=False).display, "Other")
        self.assertEqual(r.resolve(q, "choice", ["--Select--", "Linkedin", "Carrers"], quick=False).display, "Carrers")
        self.assertEqual(r.resolve(q, "choice", ["Campus Career Fair", "Careers Page"], quick=False).display, "Careers Page")

    def test_go_needs_a_skills_listing(self):
        from unittest.mock import patch
        from jobbot import resumes
        info = {"r": {"text": "led the go-live of a payments service; java and python", "skills": ["java", "python"]}}
        with patch.object(resumes, "parse_all", return_value=info):
            self.assertFalse(resumes.mentions(None, "Golang"))   # "go-live" is not Go
            self.assertFalse(resumes.mentions(None, "go"))
            info["r"]["skills"].append("go")
            self.assertTrue(resumes.mentions(None, "Golang"))

    def test_yes_no_against_sentence_options(self):
        from jobbot.apply.consistency import yes_no_sentence
        self.assertIs(yes_no_sentence("No", "I have never been employed by Rubrik"), True)
        self.assertIs(yes_no_sentence("No", "I am currently a full-time employee for Rubrik"), False)
        self.assertEqual(yes_no_sentence("Yes", "Citizen"), "unclear")
        self.assertIsNone(yes_no_sentence("No", "No"))

    def test_learned_answers_merge_across_workers(self):
        from jobbot.memory import Memory
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "profile.yaml"
            path.write_text("personal: {}\n", encoding="utf-8")
            a, b = Memory(path, []), Memory(path, [])
            a.remember("Notice period buy-out possible?", "Yes")
            b.remember("Open to relocation within India?", "Yes")
            self.assertEqual(len(Memory(path, yaml.safe_load(path.read_text())["learned_answers"]).items), 2)

    def test_tool_experience_answer_claims_only_resume_tools(self):
        from jobbot.answers import Resolver
        prof = Profile({**PROFILE, "links": {"website": "https://asha.dev"}}, "x")
        prof.resumes = lambda: {"cloud": {"path": ""}}
        prof.resume_text = lambda key, limit=None: "Docker, AWS (EC2, S3, RDS), Python, Java"
        r = Resolver(prof, None, job={"company": "Fampay"})
        self.assertIsNone(r.resolve("Share your hands-on experience with AWS services like S3, EKS, or MSK. What was the use case?",
                                    "textarea", quick=True))
        self.assertEqual(r.resolve("Portfolio URL", "text", quick=True).value, "https://asha.dev")   # portfolio = your website

    def test_free_text_passes_exact_checks_and_hear_groups_tick_one_box(self):
        from jobbot.answers import Resolver
        from jobbot.apply.consistency import free_text_ok
        from jobbot.apply.engine import HEAR_MINE_RE, HEAR_OPTION_RE
        prof = Profile({**PROFILE, "work": {**PROFILE.get("work", {}), "total_experience_years": 2, "past_employers": ["Salesforce"]}}, "x")
        r = Resolver(prof, None, job={"company": "Anyscale"})
        self.assertTrue(free_text_ok("I am excited to contribute to Anyscale's Ray platform with my backend work.", r))
        self.assertTrue(free_text_ok("At Salesforce I built backend services for 2 years.", r))
        self.assertFalse(free_text_ok("I have always wanted to work at Google because of its scale.", r))
        self.assertFalse(free_text_ok("I bring 8 years of experience leading platform teams.", r))
        self.assertFalse(free_text_ok("asdf", r))
        group = ["LinkedIn", "Company Website", "Recruiter Outreach", "Podcast/Blog", "Other Job Boards"]
        self.assertTrue(all(HEAR_OPTION_RE.fullmatch(x) for x in group))
        self.assertEqual([x for x in group if HEAR_MINE_RE.fullmatch(x)], ["Company Website"])

    def test_skip_is_never_consent(self):
        from jobbot.ui.bridge import WebUI, ApplyRun
        from jobbot.apply.engine import NeedsYou
        from unittest.mock import patch
        ui = WebUI(ApplyRun())
        with patch.object(ui, "_wait", return_value="skip"):
            with self.assertRaises(NeedsYou):
                ui.confirm("Accept terms?")
        with patch.object(ui, "_wait", return_value="false"):
            self.assertFalse(ui.confirm("Accept terms?"))

    def test_current_field_correction_and_protected_fields(self):
        from jobbot.apply.engine import Session
        from unittest.mock import Mock
        session = Session.__new__(Session)
        session._fields = Mock(return_value=[{"id": "email", "kind": "text", "label": "Email"}])
        session.ui = Mock()
        session._manual_records, session._mine, session._broken = {}, set(), set()
        page = Mock()
        session._correct_field(page, {"field": "email", "value": "asha@example.com"})
        page.locator.return_value.fill.assert_called_once_with("asha@example.com")
        self.assertEqual(session._manual_records["email"]["expected"], "asha@example.com")
        page.reset_mock()
        session._fields.return_value = [{"id": "sex", "kind": "select", "label": "Gender"}]
        session._correct_field(page, {"field": "sex", "value": "Female"})
        page.locator.assert_not_called()
