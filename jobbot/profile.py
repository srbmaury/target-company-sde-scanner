"""Load the candidate profile and the text of each resume variant."""

import hashlib
import os
import shutil
from pathlib import Path

import yaml

from . import paths


class ProfileError(Exception):
    pass


class Profile:
    def __init__(self, data, path):
        self.data = data or {}
        self.path = path

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def full_name(self):
        return f"{self.get('personal.first_name', '')} {self.get('personal.last_name', '')}".strip()

    def resumes(self):
        """{key: {"path": Path, "focus": str}} for every resume that exists on disk."""
        out = {}
        for key, spec in (self.get("resumes") or {}).items():
            spec = spec if isinstance(spec, dict) else {"path": spec}
            p = Path(os.path.expanduser(str(spec.get("path", ""))))
            if p.is_file():
                out[key] = {"path": p, "focus": spec.get("focus", "")}
        return out

    def resume_text(self, key, limit=6000):
        spec = self.resumes().get(key)
        if not spec:
            return ""
        return pdf_text(spec["path"])[:limit]

    def summary(self):
        """Non-sensitive facts handed to the local model for drafting answers."""
        keep = {
            "name": self.full_name,
            "location": f"{self.get('personal.city')}, {self.get('personal.country')}",
            "current_role": f"{self.get('work.current_title')} at {self.get('work.current_company')} since {self.get('work.start_month')}",
            "experience_years": self.get("work.total_experience_years"),
            "past_employers": self.get("work.past_employers"),
            "notice_period_days": self.get("work.notice_period_days"),
            "education": f"{self.get('education.degree_short') or self.get('education.degree')} {self.get('education.field')}, "
                         f"{self.get('education.school')} ({self.get('education.end_year')}), GPA {self.get('education.gpa')}",
            "work_authorization": f"Authorized in {', '.join(self.get('eligibility.authorized_countries') or [])}; "
                                  f"sponsorship needed: {'yes' if self.get('eligibility.needs_sponsorship') else 'no'}",
            "reason_for_change": self.get("work.reason_for_change"),
        }
        return {k: v for k, v in keep.items() if v}


def load(path=None):
    path = Path(path or paths.PROFILE)
    if not path.exists() and path == paths.PROFILE and paths.LEGACY_PROFILE.exists():
        path = paths.LEGACY_PROFILE
    if not path.exists():
        raise ProfileError(f"No profile at {path}. Run `jobbot init` and edit it.")
    with open(path, encoding="utf-8") as fh:
        return Profile(yaml.safe_load(fh), path)


def init(force=False):
    paths.ensure_home()
    if paths.PROFILE.exists() and not force:
        return False
    shutil.copy(paths.EXAMPLE_PROFILE, paths.PROFILE)
    os.chmod(paths.PROFILE, 0o600)
    return True


def pdf_text(path):
    """Extract and cache a PDF's text, keyed by file content."""
    data = Path(path).read_bytes()
    digest = hashlib.sha1(data).hexdigest()[:16]
    cached = paths.CACHE / f"resume-{digest}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    from pypdf import PdfReader

    text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    paths.ensure_home()
    cached.write_text(text, encoding="utf-8")
    return text
