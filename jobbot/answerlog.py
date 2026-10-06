"""A record of every answer the local model gave, with its reasoning, so you can check its accuracy.

Stored in ~/.jobbot/answers.jsonl (private). `jobbot answers` lists them; `answers ok N` marks one
right and `answers fix N "text"` corrects one (the correction is saved as a learned answer, so the
same question gets your answer from then on).
"""

import datetime as dt
import json

from . import paths


def _path():
    return paths.HOME / "answers.jsonl"


def record(question, answer, company="", reasoning="", kind=""):
    try:
        paths.ensure_home()
        with open(_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "company": company,
                                 "question": question[:400], "answer": str(answer)[:600], "kind": kind,
                                 "reasoning": reasoning[:300], "verdict": None}) + "\n")
    except OSError:
        pass   # never let bookkeeping break an application


def load():
    if not _path().exists():
        return []
    rows = []
    for line in _path().read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def save(rows):
    _path().write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def accuracy(rows):
    """(right, fixed): answers you reviewed."""
    return sum(r.get("verdict") == "ok" for r in rows), sum(r.get("verdict") == "fixed" for r in rows)
