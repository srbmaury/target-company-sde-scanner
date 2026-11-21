"""Dashboard log discovery independent of HTTP request handling."""

from .. import paths

def log_dates():
    logdir = paths.HOME / "logs"
    if not logdir.exists():
        return []
    return sorted((p.stem for p in logdir.glob("*.log")), reverse=True)

