"""Application-flow limits and page intent patterns."""

import re

MAX_ROUNDS = 5           # review rounds per page before asking you
TRUSTED = ("profile", "rule", "remembered")   # sources allowed to overwrite a value the site pre-filled

MAX_PAGES = 15
MAX_ATTEMPTS = 3           # unattended: tries at the same page before moving on to the next application
MAX_APPLY_SECONDS = 600    # unattended: time limit for one application

SUBMIT_RE = r"^(submit( (my )?application)?|send application|apply|finish|complete application)$"
WORKDAY_SUBMIT_RE = r"^submit$"   # Workday keeps "Apply" buttons around; only Review has "Submit"
APPLY_RE = r"^(apply( now| online| here)?|apply (for|to) (this|the) (job|position|role)|start (your )?application|i.?m interested|submit (your )?(resume|cv))$"
NEXT_RE = r"^(next|continue|save and continue|save & continue|proceed)$"
CONFIRM_RE = re.compile(
    r"thank(s| you) for (applying|your (application|interest))|application (has been |was )?(submitted|received)|"
    r"successfully (submitted|applied)|we.ve received your application", re.I)
# Honeypot fields exist to catch bots; filling one gets the application flagged.
TRAP_RE = re.compile(r"robots? only|for robots|do not (fill|enter)|leave (this )?(field )?(blank|empty)|honeypot", re.I)
CONSENT_RE = re.compile(r"consent|privacy|acknowledge|agree|terms|certify|^i confirm|confirm the statement|declare|"
                        r"^i understand\b|^i have (read|reviewed|marked)\b", re.I)

