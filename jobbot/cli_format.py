"""Pure CLI input expansion and output formatting helpers."""

import re

def expand_job_keys(keys):
    """Turn "12", "12-20", "12..20", and "12,15" into individual keys; URLs pass through."""
    out = []
    for key in keys:
        for part in ([key] if key.startswith("http") else key.split(",")):
            part = part.strip()
            m = re.fullmatch(r"(\d+)\s*(?:-|\.\.)\s*(\d+)", part)
            if m:
                lo, hi = sorted((int(m.group(1)), int(m.group(2))))
                out.extend(str(n) for n in range(lo, hi + 1))
            elif part:
                out.append(part)
    return out


def _short(text, n):
    text = (text or "").replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"

