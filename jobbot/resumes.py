"""Your resumes, read once: full text plus the skills they name, cached in ~/.jobbot/resumes.json.

Answers use this to decide what you have worked with. A technology no resume names gets "0" years
or "No"; jobbot never claims experience your resumes do not show. The cache is rebuilt when a resume
file changes, or with `jobbot resumes` / the dashboard's Parse resumes button.
"""

import json
import re

from . import paths

# Different spellings of the same thing, so "k8s" matches a resume that says "Kubernetes".
ALIASES = {
    "golang": "go", "js": "javascript", "ts": "typescript", "k8s": "kubernetes", "postgres": "postgresql",
    "node": "node.js", "nodejs": "node.js", "reactjs": "react", "react.js": "react", "nextjs": "next.js",
    "vuejs": "vue", "vue.js": "vue", "angularjs": "angular", "dotnet": ".net", "asp.net core": "asp.net",
    "amazon web services": "aws", "google cloud": "gcp", "microsoft azure": "azure", "ci/cd": "ci/cd",
    "py": "python", "c sharp": "c#", "mongo": "mongodb", "tf": "terraform", "llms": "llm",
}
# Words that describe the question, not a technology.
NOT_TECH = {"experience", "years", "year", "hands", "on", "professional", "production", "development", "developing",
            "programming", "working", "work", "with", "using", "and", "or", "the", "of", "in", "a", "an", "tools",
            "technologies", "frameworks", "framework", "languages", "language", "applications", "application",
            "services", "platforms", "systems", "building", "deploying", "supporting", "end", "to", "related",
            "relational", "database", "databases", "pipelines", "pull", "requests", "skills", "knowledge", "etc"}


def cache_path():
    return paths.HOME / "resumes.json"


def _stamp(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def parse_all(profile, force=False):
    """Read every resume in the profile (full text, no truncation). Returns {key: {"path", "chars", "skills"}}."""
    try:
        cache = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    out, changed, cacheable = {}, force, True
    for key, spec in profile.resumes().items():
        path = spec.get("path")
        if not path:   # a resume known only by its text (tests, or a profile without files)
            text = re.sub(r"\s+", " ", _full_text(profile, key))
            out[key], cacheable = {"path": "", "mtime": 0, "text": text, "skills": skills_in(text)}, False
            continue
        entry = cache.get(key)
        if force or not entry or entry.get("path") != str(path) or entry.get("mtime") != _stamp(path):
            text = re.sub(r"\s+", " ", _full_text(profile, key))
            entry = {"path": str(path), "mtime": _stamp(path), "text": text, "skills": skills_in(text)}
            changed = True
        out[key] = entry
    if cacheable and (changed or set(out) != set(cache)):
        cache_path().parent.mkdir(parents=True, exist_ok=True)
        cache_path().write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def _full_text(profile, key):
    return profile.resume_text(key, limit=None) if _takes_limit(profile) else profile.resume_text(key)


def _takes_limit(profile):
    import inspect
    try:
        return "limit" in inspect.signature(profile.resume_text).parameters
    except (TypeError, ValueError):
        return False


def skills_in(text):
    """The technology-like terms a resume names: its Skills lines plus capitalised tools (React, AWS, C#)."""
    found = set()
    for line in re.findall(r"(?:skills|technologies|tools|languages|frameworks)[^:]{0,40}:\s*([^\n]{3,400})", text, re.I):
        for item in re.split(r"[,;|•·]", line):
            item = item.strip(" .()").lower()
            if 1 < len(item) <= 30 and len(item.split()) <= 3:
                found.add(ALIASES.get(item, item))
    for tok in re.findall(r"\b(?:[A-Z][A-Za-z0-9+#.]*[A-Z0-9+#][A-Za-z0-9+#.]*|[A-Z][a-z]+(?:\.js|JS))\b", text):
        found.add(ALIASES.get(tok.lower(), tok.lower()))
    return sorted(found)


def corpus(profile):
    """All resume text, lower-cased, for whole-word checks."""
    return " ".join(e["text"] for e in parse_all(profile).values()).lower()


def mentions(profile, term):
    """True when a resume names `term` (or one of its spellings) as a whole word."""
    text = corpus(profile)
    term = term.strip().lower()
    for t in {term, ALIASES.get(term, term)} | {k for k, v in ALIASES.items() if v == term}:
        if t and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9+#])", text):
            return True
    return False


def has_all(profile, phrase):
    """'C#/ASP.NET Core and Angular/TypeScript': every "and" part needs at least one of its "/" choices
    on a resume. Returns (all_found, missing_parts)."""
    phrase = re.sub(r"\(.*?\)|\betc\.?", " ", phrase)
    missing = []
    for part in re.split(r"\s*(?:,|\band\b|&|\+)\s*", phrase):
        options = [o.strip() for o in re.split(r"\s*(?:/|\bor\b)\s*", part) if o.strip()]
        # drop generic words ("pull requests", "relational database development"); a part left empty is not a technology
        options = [" ".join(w for w in o.split() if w.lower() not in NOT_TECH) for o in options]
        options = [o for o in options if re.search(r"[a-z0-9]", o, re.I)]
        if options and not any(mentions(profile, o) for o in options):
            missing.append(part.strip())
    return not missing, missing


# Terms worth listing in a "Skills" box, in the order they are listed.
KNOWN = ["Java", "Python", "JavaScript", "TypeScript", "Kotlin", "Go", "C++", "C#", "SQL", "React", "Next.js", "Node.js",
         "Express.js", "Flask", "FastAPI", "Spring Boot", "GraphQL", "REST", "Android", "Jetpack Compose", "AWS", "GCP",
         "Azure", "Docker", "Kubernetes", "Terraform", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "Git",
         "GitHub Actions", "CI/CD", "Grafana", "LLM", "RAG", "MCP", "LightGBM", "PyTorch", "TensorFlow", "Bazel", "Jest"]


def top_skills(profile, resume_key=None, limit=15):
    """The known technologies your resume (or all resumes) names, as a comma-separated list."""
    info = parse_all(profile)
    text = (info[resume_key]["text"] if resume_key in info else " ".join(e["text"] for e in info.values())).lower()
    hits = [k for k in KNOWN if re.search(rf"(?<![a-z0-9]){re.escape(k.lower())}(?![a-z0-9+#])", text)]
    return ", ".join(hits[:limit])
