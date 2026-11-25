#!/usr/bin/env bash
set -e
# Run jobbot from anywhere: ln -s "$PWD/jobbot.sh" /opt/homebrew/bin/jobbot
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PY="$DIR/.venv/bin/python"
REQ="$DIR/requirements.txt"
STAMP="$DIR/.venv/.jobbot-requirements"

if [ ! -x "$PY" ]; then
  echo "Jobbot: creating virtual environment..." >&2
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Jobbot requires Python 3.11+")'
  python3 -m venv "$DIR/.venv"
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
