"""Registry loading, name resolution, and previously-seen URL helpers."""

import json
import os
import re

REGISTRY = os.path.join(os.path.dirname(__file__), "..", "references", "ats-registry.json")

def load_history(path):
    if not path or not os.path.exists(path):
        return set()
    return set(re.findall(r"https?://[^\s|)>\]]+", open(path, encoding="utf-8").read()))


def load_registry():
    with open(REGISTRY, encoding="utf-8") as fh:
        return json.load(fh)["companies"]


def resolve_names(registry, companies=None):
    """Map user-supplied names to registry keys. Returns (names, missing)."""
    if not companies:
        return list(registry), []
    lookup = {k.lower(): k for k in registry}
    names, missing = [], []
    for raw in companies:
        if not raw.strip():
            continue
        key = lookup.get(raw.strip().lower())
        (names.append(key) if key else missing.append(raw.strip()))
    return names, missing

