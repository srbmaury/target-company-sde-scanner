"""Where jobbot keeps its files.

Your profile is `profile.yaml` in the repository folder. It is git-ignored, so it
never gets committed. The tracker database and browser profile live in ~/.jobbot.
"""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("JOBBOT_HOME", Path.home() / ".jobbot"))
DB = HOME / "applications.db"
PROFILE = Path(os.environ.get("JOBBOT_PROFILE", REPO / "profile.yaml"))
LEGACY_PROFILE = HOME / "profile.yaml"   # where profiles lived before they moved into the repo folder
BROWSER_PROFILE = HOME / "browser-profile"
CACHE = HOME / "cache"
EXAMPLE_PROFILE = REPO / "profile.example.yaml"


def ensure_home():
    """~/.jobbot holds your tracker, logs (with the values filled into forms), Gmail token and
    browser profile: readable by you only."""
    HOME.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    try:
        os.chmod(HOME, 0o700)
    except OSError:
        pass
    return HOME
