#!/usr/bin/env bash
# Import (or update) the POC Grafana dashboards.
set -euo pipefail
cd "$(dirname "$0")"
GF_PORT="${GF_PORT:-3001}"
GF_ADMIN_USER="${GF_ADMIN_USER:-admin}"
GF_ADMIN_PASS="${GF_ADMIN_PASS:-admin}"   # Grafana forces a change on first login — pass the real one via env
GF="http://localhost:${GF_PORT}"

DASHBOARDS=(grafana-dashboard.json)

for f in "${DASHBOARDS[@]}"; do
  curl -s -X POST "$GF/api/dashboards/db" \
    -u "${GF_ADMIN_USER}:${GF_ADMIN_PASS}" \
    -H "Content-Type: application/json" \
    -d @"$f" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d.get('status') != 'success':
    sys.exit(f'import FAILED ($f): {d}')
print('import:', d['status'], '->', d['url'])"
done
