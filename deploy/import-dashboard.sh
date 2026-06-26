#!/usr/bin/env bash
# Import (or update) the POC Grafana dashboard.
set -euo pipefail
cd "$(dirname "$0")"
GF_PORT="${GF_PORT:-3001}"
GF="http://admin:admin@localhost:${GF_PORT}"
curl -s -X POST "$GF/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -d @grafana-dashboard.json \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('import:',d.get('status'),'->',d.get('url'))"
