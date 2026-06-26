#!/usr/bin/env bash
#
# Zoom Room Monitoring POC — Zabbix + Grafana stack (Podman)
#
# Stands up a single Podman pod containing:
#   - postgres            (Zabbix database)
#   - zabbix-server       (the "brain": triggers, history)
#   - zabbix-web          (nginx UI on :8080)
#   - grafana             (dashboards on :3000, with the Zabbix plugin)
#
# All containers share the pod's network namespace, so they reach each other
# on 127.0.0.1. Published host ports:
#   8080  -> Zabbix web UI
#   3001  -> Grafana   (3000 is often taken by a native Grafana; override with GF_PORT)
#   10051 -> Zabbix trapper (so the bridge on the Mac host can push values)
#
# Usage:
#   ./zabbix-stack.sh up        # pull images, create pod, start everything
#   ./zabbix-stack.sh down      # stop & remove the pod (keeps the DB volume)
#   ./zabbix-stack.sh destroy   # down + delete the DB volume (full reset)
#   ./zabbix-stack.sh status    # show pod/container/volume status
#   ./zabbix-stack.sh logs [name]
#
set -euo pipefail

POD=zabbix-poc
PGVOL=zabbix-pgdata
GFVOL=zabbix-grafana

# --- versions (Zabbix 7.0 LTS to mirror a production deployment) ---
PG_IMAGE=docker.io/library/postgres:16-alpine
ZBX_SERVER_IMAGE=docker.io/zabbix/zabbix-server-pgsql:alpine-7.0-latest
ZBX_WEB_IMAGE=docker.io/zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest
GRAFANA_IMAGE=docker.io/grafana/grafana-oss:latest

# --- credentials (POC-only; fine to keep simple) ---
DB_USER=zabbix
DB_PASS=zabbix_pwd
DB_NAME=zabbix
PHP_TZ=Asia/Singapore

# --- host ports (override if something already holds them) ---
WEB_PORT="${WEB_PORT:-8080}"
GF_PORT="${GF_PORT:-3001}"
TRAP_PORT="${TRAP_PORT:-10051}"

up() {
  echo ">> Pulling images (first run only; this is the slow part)..."
  for img in "$PG_IMAGE" "$ZBX_SERVER_IMAGE" "$ZBX_WEB_IMAGE" "$GRAFANA_IMAGE"; do
    podman pull "$img"
  done

  echo ">> Creating volumes..."
  podman volume inspect "$PGVOL" >/dev/null 2>&1 || podman volume create "$PGVOL"
  podman volume inspect "$GFVOL" >/dev/null 2>&1 || podman volume create "$GFVOL"

  echo ">> (Re)creating pod $POD..."
  podman pod rm -f "$POD" >/dev/null 2>&1 || true
  podman pod create --name "$POD" \
    -p "${WEB_PORT}:8080" \
    -p "${GF_PORT}:3000" \
    -p "${TRAP_PORT}:10051"

  echo ">> Starting postgres..."
  podman run -d --pod "$POD" --name "${POD}-db" \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASS" \
    -e POSTGRES_DB="$DB_NAME" \
    -v "${PGVOL}:/var/lib/postgresql/data" \
    "$PG_IMAGE"

  echo ">> Starting zabbix-server..."
  podman run -d --pod "$POD" --name "${POD}-server" \
    -e DB_SERVER_HOST=127.0.0.1 \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASS" \
    -e POSTGRES_DB="$DB_NAME" \
    "$ZBX_SERVER_IMAGE"

  echo ">> Starting zabbix-web (UI on :8080)..."
  podman run -d --pod "$POD" --name "${POD}-web" \
    -e ZBX_SERVER_HOST=127.0.0.1 \
    -e DB_SERVER_HOST=127.0.0.1 \
    -e POSTGRES_USER="$DB_USER" \
    -e POSTGRES_PASSWORD="$DB_PASS" \
    -e POSTGRES_DB="$DB_NAME" \
    -e PHP_TZ="$PHP_TZ" \
    -e ZBX_SERVER_NAME="Zoom Room POC" \
    "$ZBX_WEB_IMAGE"

  echo ">> Starting grafana (UI on :3000) with the Zabbix plugin..."
  podman run -d --pod "$POD" --name "${POD}-grafana" \
    -e GF_INSTALL_PLUGINS=alexanderzobnin-zabbix-app \
    -e GF_SECURITY_ADMIN_PASSWORD=admin \
    -v "${GFVOL}:/var/lib/grafana" \
    "$GRAFANA_IMAGE"

  echo
  echo ">> Stack starting. Give it ~1-2 min for the DB schema to import on first run."
  echo "   Zabbix UI : http://localhost:${WEB_PORT}   (login: Admin / zabbix)"
  echo "   Grafana   : http://localhost:${GF_PORT}   (login: admin / admin)"
}

down()    { podman pod rm -f "$POD" 2>&1 || true; }
destroy() { down; podman volume rm -f "$PGVOL" "$GFVOL" 2>&1 || true; }
status()  {
  echo "=== pod ==="; podman pod ps --filter name="$POD"
  echo "=== containers ==="; podman ps -a --pod --filter pod="$POD" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  echo "=== volumes ==="; podman volume ls --filter name=zabbix
}
logs()    { podman logs "${POD}-${1:-server}"; }

cmd="${1:-}"; shift || true
case "$cmd" in
  up) up ;;
  down) down ;;
  destroy) destroy ;;
  status) status ;;
  logs) logs "$@" ;;
  *) echo "Usage: $0 {up|down|destroy|status|logs [db|server|web|grafana]}"; exit 1 ;;
esac
