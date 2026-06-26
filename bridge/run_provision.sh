#!/usr/bin/env bash
# Load .env and run Zabbix provisioning inside the venv.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "No .env (copy .env.example)"; exit 1; }
set -a; . ./.env; set +a
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
exec .venv/bin/python provision.py "$@"
