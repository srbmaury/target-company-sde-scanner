"""Pure and browser-locator text-length helpers for application fields."""

def fit_length(value, loc):
    """Shorten text to the field's maxlength at a sentence end (else a word end), so the site does not
    cut it mid-word and the read-back still matches."""
    try:
        limit = int(loc.evaluate("el => el.maxLength") or -1)
    except Exception:
        return value
    if limit <= 0 or len(value) <= limit:
        return value
    return _trim(value, limit)


def refit_if_cut(value, loc):
    """A site that caps length by script (no maxlength) keeps only the start of the text: retype it
    shortened to that length at a sentence end, so it reads complete and the read-back matches."""
    try:
        kept = loc.input_value()
    except Exception:
        return value
    if len(value) > 40 and 20 < len(kept) < len(value) and value.startswith(kept):
        short = _trim(value, len(kept))
        loc.fill(short)
        return short
    return value


def _trim(value, limit):
    cut = value[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind(".") if cut.endswith(".") else -1)
    return cut[:end + 1].strip() if end >= limit // 3 else cut.rsplit(" ", 1)[0].rstrip(",;:- ")

