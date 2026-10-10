"""Answers you gave once, reused for the same or a very similar question later.

They are stored in your profile.yaml under `learned_answers:` so everything jobbot
answers with lives in one file you can read and edit. Answers to questions that
name the employer (e.g. "Why do you want to join Abnormal?") are not saved, because
they would be wrong at the next company. Questions matching `always_ask` are never
saved either.
"""

import re

import threading

import yaml

from . import paths

STOP = set("""a an the and or of to in on for with at by from your you are is be do does did have has will would
can could please this that these those as it its our we us any all if""".split())
HEADER = ("# Answers you gave jobbot during applications; reused for similar questions.\n"
          "# Edit or delete entries freely. jobbot rewrites only this section.\n")


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9+#]+", (text or "").lower()) if w not in STOP}


_SAVE_LOCK = threading.Lock()


class Memory:
    def __init__(self, profile_path=None, items=None):
        self.path = profile_path or paths.PROFILE
        self.items = list(items or [])

    @classmethod
    def for_profile(cls, profile):
        return cls(profile.path, profile.get("learned_answers") or [])

    def lookup(self, question, options=None):
        """Best stored answer for this question, or None. For choices the option must still exist."""
        q = _tokens(question)
        if not q:
            return None
        best, best_score = None, 0.0
        for item in self.items:
            t = _tokens(item.get("question"))
            if t:
                score = len(q & t) / len(q | t)
                if score > best_score:
                    best, best_score = item, score
        if not best or best_score < 0.8:
            return None
        if options and not any(o.strip().lower() == str(best["answer"]).strip().lower() for o in options):
            return None
        return best["answer"]

    def remember(self, question, answer, company=None):
        if not answer or not question:
            return False
        if company and re.search(rf"\b{re.escape(company.split()[0])}\b", question, re.I):
            return False   # names the employer ("Why Acme?"): would be wrong at the next company
        key = _tokens(question)
        self.items = [i for i in self.items if _tokens(i.get("question")) != key]
        self.items.append({"question": re.sub(r"\s+", " ", question).strip()[:400], "answer": str(answer)})
        self._save()
        return True

    def _save(self):
        """Rewrite only the trailing `learned_answers:` block so comments elsewhere survive. Parallel workers
        each hold a Memory: merge what is on disk first, under a lock, so none loses another's answers."""
        with _SAVE_LOCK:
            self._merge_from_disk()
            self._write()

    def _merge_from_disk(self):
        try:
            on_disk = (yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}).get("learned_answers") or []
        except (OSError, yaml.YAMLError):
            return
        mine = {frozenset(_tokens(i.get("question"))) for i in self.items}
        self.items = [i for i in on_disk if frozenset(_tokens(i.get("question"))) not in mine] + self.items

    def _write(self):
        text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        cut = re.search(r"^(# Answers you gave jobbot.*\n(?:#.*\n)*)?learned_answers:.*", text, re.M | re.S)
        head = text[:cut.start()] if cut else text
        block = yaml.safe_dump({"learned_answers": self.items}, allow_unicode=True, sort_keys=False, width=100)
        self.path.write_text(head.rstrip("\n") + "\n\n" + HEADER + block, encoding="utf-8")
