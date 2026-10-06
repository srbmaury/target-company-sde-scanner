"""Golden questions: real questions from application forms, with the answer each must get.

A rule change that alters any of these answers fails here. `None` means "leave it to the model or
to you", which is right for questions the profile can't settle.
"""

import os
import tempfile

# Never touch your real ~/.jobbot from tests (tracker, logs, answer log, browser profile).
os.environ["JOBBOT_HOME"] = tempfile.mkdtemp(prefix="jobbot-test-")
import unittest

from jobbot.answers import Resolver
from jobbot.profile import Profile

PROFILE = {
    "personal": {"first_name": "Asha", "last_name": "Example", "email": "asha@example.com", "phone": "9876543210",
                 "phone_country": "India", "phone_device_type": "Mobile", "city": "Bengaluru", "state": "Karnataka",
                 "country": "India", "postal_code": "560001", "location_autocomplete": "Bengaluru, Karnataka, India",
                 "languages": ["Hindi"]},
    "links": {"linkedin": "https://www.linkedin.com/in/asha", "github": "https://github.com/asha", "website": "https://asha.dev"},
    "work": {"current_company": "Example Corp", "current_title": "Software Engineer", "total_experience_years": 2,
             "past_employers": ["Example Corp", "Razorpay"], "notice_period_days": 30, "current_ctc": "INR 20 LPA fixed",
             "expected_ctc": "INR 28 LPA fixed", "outside_business_activities": "No"},
    "education": {"school": "Example Institute", "degree": "Bachelor's degree", "field": "Computer Science"},
    "eligibility": {"authorized_countries": ["India"], "needs_sponsorship": False, "willing_to_relocate": True,
                    "military_service": "No", "government_employee": "No"},
    "eeo": {"gender": "Male", "hispanic_latino": "No", "race": "Asian", "veteran": "I am not a protected veteran",
            "disability": "No, I do not have a disability"},
    "preferences": {"locations": "bengaluru|bangalore|hyderabad", "how_did_you_hear": "Company website"},
}
YN = ["Yes", "No"]
INDIA_JOB = {"company": "Acme", "title": "SDE II", "location": "Bengaluru, Karnataka, India"}
US_JOB = {"company": "Acme", "title": "Software Engineer", "location": "Seattle, WA, United States"}

# (question, kind, options, job, expected)
GOLDEN = [
    ("First Name", "text", None, INDIA_JOB, "Asha"),
    ("Preferred First Name", "text", None, INDIA_JOB, "Asha"),
    ("Local Given Name(s)", "text", None, INDIA_JOB, "Asha"),
    ("Last Name", "text", None, INDIA_JOB, "Example"),
    ("Local Family Name", "text", None, INDIA_JOB, "Example"),
    ("Please enter your preferred Last Name/Surname (only enter your preferred Last Name/Surname)", "text", None, INDIA_JOB, "Example"),
    ("Legal Name", "text", None, INDIA_JOB, "Asha Example"),
    ("Full name ✱", "text", None, INDIA_JOB, "Asha Example"),
    ("Email ✱", "text", None, INDIA_JOB, "asha@example.com"),
    ("Phone Number", "text", None, INDIA_JOB, "9876543210"),
    ("Phone Extension", "text", None, INDIA_JOB, None),
    ("Phone Device Type", "choice", ["Home", "Mobile", "Work"], INDIA_JOB, "Mobile"),
    ("Country Phone Code", "choice", ["Indonesia (+62)", "India (+91)"], INDIA_JOB, "India (+91)"),
    ("LinkedIn Profile", "text", None, INDIA_JOB, "https://www.linkedin.com/in/asha"),
    ("GitHub URL", "text", None, INDIA_JOB, "https://github.com/asha"),
    ("Other website", "text", None, INDIA_JOB, "https://asha.dev"),
    ("What is your home zip code?", "text", None, INDIA_JOB, "560001"),
    ("State", "text", None, INDIA_JOB, "Karnataka"),
    ("Who is your current (or most recent) employer?", "text", None, INDIA_JOB, "Example Corp"),
    ("What is your current (or most recent) title?", "text", None, INDIA_JOB, "Software Engineer"),
    ("Most Recent Job Title", "text", None, INDIA_JOB, "Software Engineer"),
    ("Years of Work Experience", "text", None, INDIA_JOB, "2"),
    ("Please indicate your experiece in number of years ✱", "text", None, INDIA_JOB, "2"),
    ("What is your official notice period ?", "text", None, INDIA_JOB, "30 days notice"),
    ("How soon can you join us? ✱", "text", None, INDIA_JOB, "30 days notice"),
    ("What’s your current fixed CTC? ✱", "text", None, INDIA_JOB, "INR 20 LPA fixed"),
    ("Current total compensation (Fixed + Variables)", "text", None, INDIA_JOB, "INR 20 LPA fixed"),
    ("Salary Expectation", "text", None, INDIA_JOB, "INR 28 LPA fixed"),
    # work authorization and sponsorship depend on the country
    ("Are you legally authorized to work in the country you reside?", "choice", YN, INDIA_JOB, "Yes"),
    ("Are you currently eligible to work in the country in which this job is posted?", "choice", YN, INDIA_JOB, "Yes"),
    ("Are you legally authorized to work in the United States?", "choice", YN, INDIA_JOB, "No"),
    ("Are you authorized to work in the country you are applying to work in?", "choice", YN, US_JOB, "No"),
    ("Will you now or in the future require Visa Sponsorship?", "choice", YN, INDIA_JOB, "No"),
    ("Would you require visa sponsorship to work in the country in which this position is based?", "choice", YN, US_JOB, "Yes"),
    ("Will you now or in the future require sponsorship for employment visa status (e.g. H1B visa status)?", "choice", YN, US_JOB, "Yes"),
    ("Are you open to relocation?", "choice", YN, INDIA_JOB, "Yes"),
    ("Are you open for Bangalore location ?", "choice", YN, INDIA_JOB, "Yes"),
    ("What is your preferred work location?", "choice", ["Mumbai", "Bengaluru", "Pune"], INDIA_JOB, "Bengaluru"),
    # employer history
    ("Have you been employed by Acme in the past?", "choice", YN, INDIA_JOB, "No"),
    ("Have you previously worked for Razorpay?", "choice", YN, {**INDIA_JOB, "company": "Razorpay"}, "Yes"),
    ("Are you currently an employee or contractor at Acme? (if Yes, please add your Acme email)", "choice", YN, INDIA_JOB, "No"),
    ("If you answered Acme Employee, Acme Event, or Other, please specify here:", "text", None, INDIA_JOB, None),
    ("If yes, please select your previous employment type?", "choice", ["Full-time", "Intern", "Contractor"], INDIA_JOB, None),
    # EEO and other personal facts
    ("Gender", "choice", ["Male", "Female", "Decline to self-identify"], INDIA_JOB, "Male"),
    ("Gender Identity (Select one)", "choice", ["Man", "Woman", "Non-binary", "Prefer not to say"], INDIA_JOB, "Man"),
    ("Are you Hispanic/Latinx?", "choice", YN, INDIA_JOB, "No"),
    ("Ethnicity/Race", "choice", ["White", "Asian", "Black or African American"], INDIA_JOB, "Asian"),
    ("Veteran Status", "choice", ["I am not a protected veteran", "I am a protected veteran"], INDIA_JOB, "I am not a protected veteran"),
    ("Have you served in the military?", "choice", YN, INDIA_JOB, "No"),
    ("In which language(s) are you fluent (spoken) other than English?", "text", None, INDIA_JOB, "Hindi"),
    ("Do you have any outside business activity(ies) (advisory, consulting, or board roles, or side businesses)?", "choice", YN, INDIA_JOB, "No"),
    ("How did you hear about this job?", "choice", ["Employee Referral", "LinkedIn", "Company Website"], INDIA_JOB, "Company Website"),
    # left to the model or to you
    ("Does the deemed export rule affect your employment by Acme?", "choice", YN, INDIA_JOB, None),
    ("Are you a US citizen?", "choice", YN, INDIA_JOB, None),
    ("Have you previously applied to work at Acme?", "choice", YN, INDIA_JOB, None),
    ("What excites you about Acme? ✱", "textarea", None, INDIA_JOB, None),
    ("search job by location", "text", None, INDIA_JOB, None),
]


class GoldenQuestions(unittest.TestCase):
    def test_golden(self):
        wrong = []
        for question, kind, options, job, expected in GOLDEN:
            r = Resolver(Profile(PROFILE, "x"), job=job, ask=lambda *a: None)
            ans = r.resolve(question, kind, options=options)
            got = None if ans is None else (ans.display or str(ans.value))
            if got != expected:
                wrong.append(f"{question[:70]!r}: got {got!r}, want {expected!r}")
        self.assertEqual(wrong, [], "\n" + "\n".join(wrong))


if __name__ == "__main__":
    unittest.main()
