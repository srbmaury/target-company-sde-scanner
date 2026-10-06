#!/usr/bin/env bash
# Run jobbot from anywhere: ln -s "$PWD/jobbot.sh" /opt/homebrew/bin/jobbot
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3
# Stay in your current folder, so relative paths (track export out.csv) land where you expect.
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m jobbot "$@"
