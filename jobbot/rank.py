"""Score stored jobs against the candidate's resumes."""

import re

STOP = set("""a an and are as at be by for from has have in is it of on or our that the this to we will with you your
team work working role experience years year strong ability skills using use build building across""".split())


def _terms(text):
    return {w for w in re.findall(r"[a-z][a-z0-9+#.]{1,}", (text or "").lower()) if w not in STOP}


def keyword_rank(job, resumes):
    """Fallback ranking without a model: term overlap plus an experience bonus."""
    jd = _terms(f"{job['title']} {job['description']}")
    best_key, best = None, -1.0
    for key, text in resumes.items():
        overlap = len(jd & _terms(text)) / max(1, min(len(jd), 120))
        if overlap > best:
            best_key, best = key, overlap
    score = min(100, int(best * 140))
    if job["experience"].startswith(("1+", "2+", "0+")):
        score = min(100, score + 10)
    shared = sorted(jd & _terms(resumes.get(best_key, "")))[:8] if best_key else []
    return score, best_key, f"keyword overlap: {', '.join(shared)}" if shared else "low keyword overlap"


def rank_jobs(conn, profile, llm, limit=None, rerank=False, on_progress=None):
    from . import tracker

    resumes = {k: profile.resume_text(k) for k in profile.resumes()}
    if not resumes:
        raise RuntimeError("No resume files found; check `resumes:` in your profile.")
    jobs = tracker.list_jobs(conn, unranked=not rerank, limit=limit)
    summary = profile.summary()
    done = []
    for i, job in enumerate(jobs, 1):
        job = dict(job)
        try:
            score, resume, reason = llm.rank(job, resumes, summary) if llm.enabled else keyword_rank(job, resumes)
        except Exception as e:  # model hiccup: fall back rather than abort the batch
            score, resume, reason = keyword_rank(job, resumes)
            reason = f"{reason} (model error: {type(e).__name__})"
        tracker.set_fit(conn, job["url"], score, resume, reason)
        done.append((job, score, resume, reason))
        if on_progress:
            on_progress(i, len(jobs), job, score)
    return done
