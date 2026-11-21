"""Question intent patterns, safety boundaries, and answer normalization vocabulary."""

import re

from ..tracker import same_company

HEAR_RE = re.compile(r"how did you (hear|learn|find|come across)|where did you (hear|find|learn)|source of (application|referral)|"
                     r"how (did you|were you) (referred|introduced)", re.I)
HEAR_PREFERENCES = ["company website", "career site", "careers site", "careers website", "careers page", "company career", "careers", "carrers", "career",
                    "corporate website", "website", "job board", "online job", "internet", "other"]   # never LinkedIn: jobbot finds roles on company boards
# Bare words that are only a match as the whole option ("Carrers", "Careers"), never inside "Career Fair".
HEAR_WHOLE_ONLY = {"careers", "carrers", "career", "website", "other"}
HEAR_EVENT = re.compile(r"\b(fair|event|expo|conference|meetup|webinar|hackathon|campus)\b", re.I)
EMPLOYMENT_RE = re.compile(r"employee id|employee number|(company|corporate|work) email|email address|worked|work(ing)? (for|at)|"
                           r"employed|employee|intern|contractor|contingent|consultant|vendor|alumni|former|previous(ly)?|rehire",
                           re.I)


OTHER_PERSON_RE = re.compile(r"referr(er|al|ed by)|\breference\b|emergency|next of kin|\bmanager'?s\b|hiring manager|recruiter|"
                             r"\bspouse\b|relative|guardian|parent'?s|supervisor|family member|immediate family", re.I)


EEO_RE = re.compile(r"\s*(race|ethnicity|ethnic (background|origin)|gender|sex\b|veteran|protected veteran|"
                    r"disability|hispanic|latino|self.?identif)", re.I)
# Facts only you can state: never answered by the model, whatever the prompt says.
FACT_ONLY_RE = re.compile(r"citizen|nationality|\bvisa\b|green card|permanent resident|work permit|immigration|"
                          r"clearance|criminal|convict|felony|arrest|debar|sanction|export (control|rule)|"
                          r"\bpassport\b|date of birth|\bage\b|social security|aadhaar|\bpan\b", re.I)
# Optional catch-all boxes ("Anything else you'd like us to know?") are better left blank than filled.
OPEN_EXTRA_RE = re.compile(r"anything else|additional (information|comments|details)|other comments|cover letter|^comments?$", re.I)
SIGN_RE = re.compile(r"signature|sign here|\be-?sign|type your (full |legal )?name to (sign|confirm|acknowledge)|by typing your (full |legal )?name", re.I)


def same_employer(company, past):
    """Is `company` one of your past employers? Compares cleaned names ("Salesforce India" = "salesforce"),
    never substrings, so "Sales Hub" is not Salesforce."""
    return any(same_company(company, e) for e in past)


COUNTRIES = {"United States": r"\bunited states\b|\bU\.?S\.?A?\.?(?![a-z])|\bamerica\b",
             "United Kingdom": r"\bunited kingdom\b|\bU\.?K\.?(?![a-z])|\bbritain\b",
             "India": r"\bindia\b", "Canada": r"\bcanada\b", "Germany": r"\bgermany\b", "Singapore": r"\bsingapore\b",
             "Ireland": r"\bireland\b", "Australia": r"\baustralia\b", "Netherlands": r"\bnetherlands\b",
             "United Arab Emirates": r"\buae\b|united arab emirates", "Japan": r"\bjapan\b", "France": r"\bfrance\b",
             "Poland": r"\bpoland\b", "Israel": r"\bisrael\b", "Spain": r"\bspain\b"}
INDIA_CITIES = (r"bengaluru|bangalore|hyderabad|noida|gurugram|gurgaon|delhi|pune|chennai|mumbai|kolkata|"
                r"ahmedabad|jaipur|kochi|trivandrum|coimbatore|indore|chandigarh")
GENDER_SYNONYMS = {"male": "Man", "female": "Woman", "man": "Male", "woman": "Female"}
# Follow-ups that depend on an earlier answer ("If yes, ..."): built-in rules would answer the wrong question.
CONDITIONAL_RE = re.compile(r"^\s*(if (yes|so|no|applicable|you (answered|selected|chose|have))|please specify|"
                            r"(please )?(provide|share) (more )?details)", re.I)


MODEL_FAILED = object()




SOCIAL_RE = re.compile(r"^\s*(facebook|twitter|x|instagram|threads|tiktok|youtube|github|gitlab|linkedin|website|portfolio|"
                       r"personal website|blog|medium|stack ?overflow|stack ?exchange|hacker ?rank|codeforces|codechef|leetcode|kaggle|dribbble|behance|mastodon|bluesky)\b"
                       r"(?:\s*\(fka twitter\))?(?:\s*(?:profile|url|link|handle|page))*\s*\*?\s*$", re.I)
SOCIAL_KEYS = {"x": "twitter", "personal website": "website", "blog": "website", "portfolio": "website", "stackoverflow": "stackoverflow",
               "stack overflow": "stackoverflow", "stack exchange": "stackexchange", "hacker rank": "hackerrank"}

RESUME_FACT_RE = re.compile(
    r"\b(years?|months?)\b.{0,60}\bexperience\b|\bexperience\b.{0,80}\b(years?|months?)\b|how many (years|months)"
    r"|^(do|have|are) you (have )?(any )?(worked|work|experience|familiar|hands.?on|used|built|exposure)\b"
    r"|^(total |work |relevant |overall |professional )?(experience|exp\.?|years|months)( \(?in (years|months)\)?)?$"
    r"|^(key |technical |primary |core |relevant )?skills?( set)?$"
    r"|\b(live|based|reside|located) within \d+\s*(miles|mi|km|kilomet)"
    r"|^(please )?(share|describe|tell us about|explain|walk us through) (your )?(hands.?on |practical |professional )?(experience|work) (with|using|in|on)\b"
    r"|^(salary |ctc |compensation |preferred |expected )?currency\b|deemed export|(previously|ever|formerly) (worked|been employed|employed) (for|at|by)|former employee|worked (for|at) .{0,40} before"
    r"|legally authori[sz]ed to work|(require|need)s? .{0,20}sponsorship|(previously|ever|already) appl(y|ied)\b"
    r"|language.{0,20}\b(fluent|speak|spoken|written)|\bfluent in\b"
    r"|^(what|which) (city|town)\b.{0,30}\b(live|based|reside|located)|^where do you (currently )?(live|reside)\b|(city|place) of residence"
    r"|^(current |home )?(location|city)( \((city|city, state|city, country)\))?$|^(current|home) (city|location)\b", re.I)

