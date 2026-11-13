#!/usr/bin/env bash
# Run jobbot from anywhere: ln -s "$PWD/jobbot.sh" /opt/homebrew/bin/jobbot
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3
# Hosted UI: use deployment settings when provided, otherwise load the repo's private shell config.
if [[ ${1:-} == ui && -z ${JOBBOT_MONGODB_URI:-} && -f "$DIR/.env" ]]; then
  set -a
  source "$DIR/.env" || exit 1
  set +a
fi
# Stay in your current folder, so relative paths (track export out.csv) land where you expect.
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m jobbot "$@"
