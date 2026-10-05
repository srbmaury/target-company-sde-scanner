"""Where jobbot keeps its files. Personal data lives outside the repository."""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("JOBBOT_HOME", Path.home() / ".jobbot"))
DB = HOME / "applications.db"
PROFILE = HOME / "profile.yaml"
BROWSER_PROFILE = HOME / "browser-profile"
CACHE = HOME / "cache"
EXAMPLE_PROFILE = REPO / "profile.example.yaml"


def ensure_home():
    HOME.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    return HOME
