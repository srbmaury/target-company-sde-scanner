"""Mandatory semantic approval with explicit field coverage."""

REVIEW_BATCH = 8

def review_step(self, page, resolver, report, check, step, confirmed=frozenset()):
    """A mandatory semantic review; outage, incomplete coverage or rejection blocks navigation.

    `confirmed` are fields the profile check (consistency.py) proved match your profile: they count as
    reviewed, and a model complaint about one of them is a false flag, not a block."""
    fields = self.audit_fields(page, report)
    self.ui.info(f"Ollama is reviewing every field on page {step} before any Next or Submit.")
    try:
        if not self.llm or not self.llm.enabled:
            raise RuntimeError("Ollama is unavailable")
        page_text = page.inner_text("body")[:18000]
        facts = self.profile.facts()
        resume_text = self.profile.resume_text(resolver.resume_key) if resolver.resume_key else ""
        # A 7B model drops ids when asked to echo 20+ of them at once, so review in small batches
        # and give it one more pass at any it skipped; every field must still be covered.
        covered, issues, rejected = set(), [], False
        batches = [fields[i:i + REVIEW_BATCH] for i in range(0, len(fields), REVIEW_BATCH)] or [[]]

        def review(todo):
            result = self.llm.review_application_step(list(todo.values()), page_text, facts, resume_text, resolver.job)
            return todo, result

        from concurrent.futures import ThreadPoolExecutor
        for attempt in range(2):   # the batches go to Ollama at once (OLLAMA_NUM_PARALLEL); a second pass for skipped ids
            # The model sees every field; only the retry leaves out fields the profile check already decided.
            done = covered | (set(confirmed) if attempt else set())
            todos = [t for t in ({f["id"]: f for f in b if f["id"] not in done} for b in batches) if t]
            if not fields and attempt == 0:
                todos = [{}]  # Review the page itself even when there are no editable fields.
            if not todos:
                break
            with ThreadPoolExecutor(max_workers=min(2, len(todos))) as pool:
                for todo, result in pool.map(review, todos):
                    covered |= set(result.get("reviewed_field_ids", [])) & set(todo)
                    raised = [x for x in result.get("issues", []) if x.get("field_id") in todo]
                    kept = [x for x in raised if x.get("field_id") not in confirmed]
                    issues += kept
                    # A rejection stands unless every complaint was about a field the profile check confirmed.
                    rejected |= result.get("approved") is not True and (bool(kept) or not raised)
        # Every field needs review: by the model, or (if it skipped one) by the profile check.
        ids = {f["id"] for f in fields}
        covered |= set(confirmed)   # a field the model skipped but the profile check decided is reviewed
        if ids <= covered and not issues and not rejected:
            self.ui.info(f"Ollama reviewed all {len(fields)} fields on page {step}: approved.")
            return
        if not ids <= covered:
            check.errors.append("Ollama review did not cover every field.")
        if rejected:
            check.errors.append("Ollama did not approve this step.")
        by_id = {f["id"]: f for f in fields}
        for issue in issues:
            f = by_id[issue["field_id"]]
            expected = resolver._profile_fact(f["label"], "text")
            if expected is not None and str(expected.value) != f.get("actual"):
                check.mismatches.append((f["label"], str(expected.value), f.get("actual", "")))
            else:
                check.errors.append(f"Ollama: {f['label']}: {issue.get('reason', 'needs review')}")
        self.ui.warn(f"Ollama blocked page {step}: " + "; ".join(check.lines()[-4:]))
    except Exception as exc:
        check.errors.append(f"Required Ollama review failed ({type(exc).__name__}); step is blocked.")
