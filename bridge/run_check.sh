#!/usr/bin/env bash
# Load .env and run the Zoom scope-verification check inside the venv.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill in your Zoom creds."
  exit 1
fi

# Load .env without echoing values.
set -a
# shellcheck disable=SC1091
. ./.env
set +a

VENV=.venv
if [ ! -d "$VENV" ]; then
  echo ">> Creating venv + installing deps..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r requirements.txt
fi

"$VENV/bin/python" check_scopes.py
