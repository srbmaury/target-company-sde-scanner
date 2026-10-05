"""Optional local model via Ollama. Everything works without it.

With `--llm none` (or when Ollama is not running) jobbot falls back to keyword
ranking and asks you directly for free-text answers.
"""

import json
import os
import re
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("JOBBOT_MODEL", "qwen2.5:7b")

GROUNDING = (
    "You help a job candidate fill in applications. Use only facts from the candidate profile and "
    "resume you are given. Never invent employers, dates, skills, metrics, credentials, or work "
    "authorization. If the facts do not answer the question, say so."
)


class LLM:
    """Thin client for Ollama's /api/chat. `None` model means disabled."""

    def __init__(self, model=DEFAULT_MODEL, enabled=True):
        self.model = model
        self.enabled = enabled and self.available()

    @staticmethod
    def available():
        try:
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def has_model(self):
        try:
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as resp:
                names = [m["name"] for m in json.load(resp).get("models", [])]
        except (urllib.error.URLError, OSError):
            return False
        return any(n == self.model or n.split(":")[0] == self.model for n in names)

    def chat(self, system, user, as_json=False, temperature=0.2, timeout=180):
        if not self.enabled:
            raise RuntimeError("local model disabled")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if as_json:
            body["format"] = "json"
        req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = json.load(resp)["message"]["content"]
        if as_json:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.S)
                return json.loads(match.group(0)) if match else {}
        return content.strip()

    # --- tasks ---------------------------------------------------------------

    def rank(self, job, resumes, profile_summary):
        """Score fit 0-100 and choose the best resume key."""
        resume_block = "\n\n".join(f"### Resume `{k}`\n{v[:2500]}" for k, v in resumes.items())
        prompt = (
            f"Candidate facts: {json.dumps(profile_summary)}\n\n{resume_block}\n\n"
            f"### Job: {job['title']} at {job['company']} ({job['location']})\n"
            f"Stated experience: {job['experience']} {job['evidence']}\n{(job['description'] or '')[:3500]}\n\n"
            "Return JSON: {\"score\": 0-100 fit for this candidate, \"resume\": the best resume key from "
            f"{list(resumes)}, \"reason\": one sentence naming the strongest match and the biggest gap}}"
        )
        out = self.chat(GROUNDING, prompt, as_json=True)
        score = int(max(0, min(100, int(out.get("score", 0)))))
        resume = out.get("resume") if out.get("resume") in resumes else next(iter(resumes), None)
        return score, resume, str(out.get("reason", ""))[:300]

    def choose(self, question, options, profile_summary, resume_text):
        """Pick one option index for a multiple-choice question, or None."""
        listing = "\n".join(f"{i}: {o}" for i, o in enumerate(options))
        prompt = (
            f"Candidate facts: {json.dumps(profile_summary)}\nResume:\n{resume_text[:2500]}\n\n"
            f"Question: {question}\nOptions:\n{listing}\n\n"
            "Return JSON {\"index\": number of the truthful option, or -1 if the facts do not settle it}."
        )
        idx = self.chat(GROUNDING, prompt, as_json=True).get("index", -1)
        return idx if isinstance(idx, int) and 0 <= idx < len(options) else None

    def draft(self, question, job, profile_summary, resume_text, max_words=120):
        prompt = (
            f"Candidate facts: {json.dumps(profile_summary)}\nResume:\n{resume_text[:3500]}\n\n"
            f"Job: {job.get('title')} at {job.get('company')}\n{(job.get('description') or '')[:2500]}\n\n"
            f"Application question: {question}\n\n"
            f"Write the candidate's answer in first person, at most {max_words} words, plain text, no "
            "greeting or sign-off. Use only the facts above."
        )
        return self.chat(GROUNDING, prompt, temperature=0.4)
