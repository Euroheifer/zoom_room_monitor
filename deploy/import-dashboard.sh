#!/usr/bin/env bash
# Import (or update) the POC Grafana dashboard.
set -euo pipefail
cd "$(dirname "$0")"
GF_PORT="${GF_PORT:-3001}"
GF_ADMIN_USER="${GF_ADMIN_USER:-admin}"
GF_ADMIN_PASS="${GF_ADMIN_PASS:-admin}"   # Grafana forces a change on first login — pass the real one via env
GF="http://${GF_ADMIN_USER}:${GF_ADMIN_PASS}@localhost:${GF_PORT}"
curl -s -X POST "$GF/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -d @grafana-dashboard.json \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d.get('status') != 'success':
    sys.exit(f'import FAILED: {d}')
print('import:', d['status'], '->', d['url'])"
