#!/usr/bin/env bash
#
# Idempotently configure Grafana for the POC:
#   1. enable the Zabbix app plugin
#   2. create (or update) the "Zabbix" datasource pointing at the Zabbix API
#
# Grafana reaches Zabbix over the shared pod localhost (127.0.0.1:8080).
#
set -euo pipefail

GF_PORT="${GF_PORT:-3001}"
GF_ADMIN_USER="${GF_ADMIN_USER:-admin}"
GF_ADMIN_PASS="${GF_ADMIN_PASS:-admin}"   # Grafana forces a change on first login — pass the real one via env
GF="http://${GF_ADMIN_USER}:${GF_ADMIN_PASS}@localhost:${GF_PORT}"
ZBX_API_URL="http://localhost:8080/api_jsonrpc.php"
ZBX_USER="${ZBX_USER:-Admin}"
ZBX_PASS="${ZBX_PASS:-zabbix}"

echo ">> Enabling Zabbix app plugin..."
curl -s -X POST "$GF/api/plugins/alexanderzobnin-zabbix-app/settings" \
  -H "Content-Type: application/json" \
  -d '{"enabled":true,"pinned":true}' >/dev/null

echo ">> Creating/updating Zabbix datasource..."
# delete any existing datasource named Zabbix, then recreate (keeps this idempotent)
existing_uid=$(curl -s "$GF/api/datasources/name/Zabbix" 2>/dev/null \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('uid',''))" 2>/dev/null || true)
if [ -n "${existing_uid:-}" ]; then
  curl -s -X DELETE "$GF/api/datasources/uid/${existing_uid}" >/dev/null || true
fi

curl -s -X POST "$GF/api/datasources" -H "Content-Type: application/json" -d "{
  \"name\":\"Zabbix\",
  \"uid\":\"zabbix-poc\",
  \"type\":\"alexanderzobnin-zabbix-datasource\",
  \"access\":\"proxy\",
  \"url\":\"${ZBX_API_URL}\",
  \"isDefault\":true,
  \"jsonData\":{\"username\":\"${ZBX_USER}\",\"authType\":\"userLogin\",\"trends\":true,\"trendsFrom\":\"7d\",\"trendsRange\":\"4d\",\"cacheTTL\":\"1m\"},
  \"secureJsonData\":{\"password\":\"${ZBX_PASS}\"}
}" >/dev/null

echo ">> Health check..."
uid=$(curl -s "$GF/api/datasources/name/Zabbix" | python3 -c "import sys,json;print(json.load(sys.stdin)['uid'])")
curl -s "$GF/api/datasources/uid/${uid}/health"
echo
