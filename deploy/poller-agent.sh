#!/usr/bin/env bash
#
# Reboot-durable launcher for the Zoom Room monitoring poller.
#
# Invoked by the LaunchAgent `com.zoomroom.poller`. Brings the whole chain up
# in order, then runs the poller loop in the FOREGROUND so launchd's KeepAlive
# supervises it (if the poller ever dies, launchd respawns this script):
#
#   1. ensure the Podman machine is running
#   2. ensure the zabbix-poc stack pod is up   (reuse if present; full `up` only if missing)
#   3. exec the poller loop
#
# Deliberately does NOT use `set -e` — Podman "already running" style errors are
# expected and tolerated.
set -uo pipefail

PODMAN=/opt/homebrew/bin/podman
POD=zabbix-poc
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] poller-agent: $*"; }

# 1. Podman machine -------------------------------------------------------
if ! "$PODMAN" info >/dev/null 2>&1; then
  log "Podman machine not reachable -> starting it"
  "$PODMAN" machine start || log "machine start returned nonzero (may already be starting)"
  for _ in $(seq 1 30); do
    "$PODMAN" info >/dev/null 2>&1 && break
    sleep 2
  done
fi
if ! "$PODMAN" info >/dev/null 2>&1; then
  log "ERROR: Podman still unreachable after wait; aborting (launchd will retry)"
  exit 1
fi
log "Podman machine is up"

# 2. Stack pod ------------------------------------------------------------
# Reuse the existing pod whenever possible: a full `zabbix-stack.sh up` recreates
# the pod (rm -f) and forces a schema re-import + data gap. We only do that when
# the pod genuinely doesn't exist.
state="$("$PODMAN" pod inspect "$POD" --format '{{.State}}' 2>/dev/null || true)"
if [ -z "$state" ]; then
  log "pod '$POD' not found -> full stack up (first run / after destroy)"
  "$ROOT/deploy/zabbix-stack.sh" up
elif echo "$state" | grep -qiE 'running|degraded'; then
  log "pod '$POD' already running ($state)"
else
  log "pod '$POD' exists but stopped ($state) -> starting it"
  "$PODMAN" pod start "$POD" || {
    log "pod start failed -> falling back to full stack up"
    "$ROOT/deploy/zabbix-stack.sh" up
  }
fi

# Give the Zabbix trapper a moment to accept connections before the first push.
sleep 5

# 3. Poller loop (foreground; launchd KeepAlive supervises) ---------------
log "starting poller loop (run_poll.sh --loop)"
exec "$ROOT/bridge/run_poll.sh" --loop
