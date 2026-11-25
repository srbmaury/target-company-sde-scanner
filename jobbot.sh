#!/usr/bin/env bash
set -e
# Run jobbot from anywhere: ln -s "$PWD/jobbot.sh" /opt/homebrew/bin/jobbot
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PY="$DIR/.venv/bin/python"
if ! "$PY" -c 'import sys' >/dev/null 2>&1; then
  PY="$DIR/.venv/bin/python3"
fi
REQ="$DIR/requirements.txt"
STAMP="$DIR/.venv/.jobbot-requirements"

# Never use an activated (possibly broken) virtualenv to rebuild itself.
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  echo "Jobbot: repairing virtual environment..." >&2
  BASE=""
  while IFS= read -r candidate; do
    [ -x "$candidate" ] || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) and sys.prefix == sys.base_prefix else 1)' >/dev/null 2>&1; then
      BASE="$candidate"
      break
    fi
  done < <(type -aP python3.13 python3.14 python3.12 python3.11 python3 2>/dev/null || true)
  if [ -z "$BASE" ]; then
    echo "Jobbot: install Python 3.11 or newer (macOS: brew install python@3.13)." >&2
    exit 1
  fi
  # Preserve the old environment rather than deleting it.
  if [ -e "$DIR/.venv" ] || [ -L "$DIR/.venv" ]; then
    BACKUP="$(mktemp -d "$DIR/.venv-backup.XXXXXX")"
    mv "$DIR/.venv" "$BACKUP/venv"
    echo "Jobbot: previous environment saved in $BACKUP/venv" >&2
  fi
  "$BASE" -m venv "$DIR/.venv"
  PY="$DIR/.venv/bin/python"
  if ! "$PY" -c 'import sys' >/dev/null 2>&1; then
    PY="$DIR/.venv/bin/python3"
  fi
  if ! "$PY" -c 'import sys' >/dev/null 2>&1; then
    echo "Jobbot: virtual environment creation failed; no runnable Python found." >&2
    exit 1
  fi
fi

# Refresh dependencies when requirements change or the environment is incomplete.
if [ ! -f "$STAMP" ] || ! cmp -s "$REQ" "$STAMP" || ! "$PY" -c 'import yaml, playwright, pypdf, pymongo, cryptography, ruamel.yaml' >/dev/null 2>&1 || ! "$PY" -m pip check >/dev/null 2>&1; then
  echo "Jobbot: installing dependencies..." >&2
  "$PY" -m pip install -r "$REQ"
  "$PY" -m pip check
  cp "$REQ" "$STAMP"
fi

# Load the repository's private shell config for the dashboard.
if [[ ${1:-} == ui && -f "$DIR/.env" ]]; then
  set -a
  source "$DIR/.env" || exit 1
  set +a
fi
# Stay in your current folder, so relative paths (track export out.csv) land where you expect.
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m jobbot "$@"
