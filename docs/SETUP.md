# Zoom Room Monitoring POC — End-to-End Setup Guide

This guide takes you from a fresh macOS laptop to a working proof-of-concept that
monitors **real Zoom Rooms** through a **Zabbix + Grafana** stack, driven by a thin
custom **bridge** that polls the Zoom API. It is a faithful miniature of the
approved Phase-1 architecture, intended to **demonstrate the concept to
stakeholders** on live Singapore fleet data.

- **Repo:** https://github.com/Euroheifer/zoom_room_monitor
- **Design specs:** `docs/superpowers/specs/` (parent design + POC design)
- **Status:** working end-to-end — 136 Singapore rooms monitored, offline +
  device-disconnect detection, live Grafana dashboard.

> ⚠️ **Secrets:** never commit or paste your Zoom client secret or Confluence PAT.
> Credentials live only in a gitignored `bridge/.env` on your machine.

---

## 1. Architecture

```
Zoom Device/Rooms API ──► bridge (Python, poll) ──► Zabbix (Podman) ──► Grafana (Podman)
                                                       hosts   = rooms     Zabbix datasource
                                                       group   = region    live dashboard
                                                       trapper items
                                                       offline / device triggers
```

| Layer | Role | Where |
|---|---|---|
| **Bridge** | Polls Zoom, normalizes, pushes to Zabbix (the only custom software) | `bridge/` |
| **Zabbix** | The "brain": hosts, triggers, history, RBAC | Podman pod `zabbix-poc` |
| **Grafana** | The "face": dashboards | Podman pod `zabbix-poc` |

Everything runs in **one Podman pod**, so the containers reach each other on
`localhost` and the bridge (on the Mac host) pushes to the published trapper port.

---

## 2. Prerequisites

- **macOS** (Apple Silicon or Intel).
- **Podman** installed and the machine running. (See the companion doc
  *Confluence MCP Setup (Podman)* for installing native arm64 Podman.)
- **Python 3** (3.11+; tested on 3.14).
- A **Zoom Server-to-Server OAuth app** with these read scopes:
  - List Zoom Rooms + status (offline detection) — **required**
  - Room devices (peripheral/device detection) — **required**
  - Device Management, Dashboard metrics — optional (richer data later)

---

## 3. Step-by-step

### Step 1 — Start the Podman machine
The stack needs ~4 GiB. Bump memory once (while the machine is stopped), then start:
```bash
podman machine set --memory 4096      # one-time, if needed
podman machine start
podman run --rm hello-world           # sanity check
```

### Step 2 — Stand up Zabbix + Grafana
```bash
cd zoom_room_monitor/deploy
./zabbix-stack.sh up                   # pulls images, creates pod, starts all
./zabbix-stack.sh status
```
This launches `postgres + zabbix-server (7.0) + zabbix-web + grafana-oss` in the
`zabbix-poc` pod. Endpoints:

| Service | URL | Login |
|---|---|---|
| Zabbix UI | http://localhost:8080 | `Admin` / `zabbix` |
| Grafana | http://localhost:3001 | `admin` / `admin` |
| Zabbix trapper (bridge target) | `localhost:10051` | — |

> Grafana is on **3001** because a native Grafana commonly holds **3000**.
> Override ports if needed: `GF_PORT=3002 WEB_PORT=8090 ./zabbix-stack.sh up`.

### Step 3 — Wire Grafana to Zabbix
```bash
./configure-grafana.sh                 # enables the Zabbix app + adds the datasource
```
Idempotent; pins the datasource to a fixed uid (`zabbix-poc`) and disables the
host/item cache so newly provisioned rooms appear immediately.

### Step 4 — Zoom credentials + scope check (the first gate)
```bash
cd ../bridge
cp .env.example .env                   # then edit .env, fill in your 3 values
./run_check.sh                         # verifies the app's scopes (read-only)
```
`.env` (gitignored) holds:
```
ZOOM_ACCOUNT_ID=...
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...
```
The check prints a table of endpoints and ends with **GATE PASSED** / **GATE
BLOCKED** (listing any missing scopes to add in the Zoom Marketplace).

### Step 5 — Provision Zabbix (hosts, templates, triggers)
```bash
./run_provision.sh
```
Creates the `Rooms/Singapore` host group, two templates, and **one Zabbix host
per Singapore room** (region/building/floor tags parsed from the room name), plus
a fleet-summary host. Idempotent.

### Step 6 — Run the bridge (poll → map → push)
```bash
./run_poll.sh                          # one cycle (verify it works)
./run_poll.sh --loop                   # continuous, every POLL_INTERVAL (120s)
```
Each cycle pulls all room statuses (one API call), device status for a small
subset, computes fleet rollups, and pushes everything to the Zabbix trapper.
Expected output: `rooms=136 offline=N ... processed: N; failed: 0`.

### Step 7 — Import the dashboard
```bash
cd ../deploy
./import-dashboard.sh                  # creates /d/zoom-sg-poc
```
Open **http://localhost:3001/d/zoom-sg-poc**.

---

## 4. What the demo shows

- **136 real Singapore rooms** as Zabbix hosts, tagged by region/building/floor.
- **Offline detection** fleet-wide (anti-flap: must be offline two polls running).
- **Device-disconnect detection** (computer / controller) on a 5-room subset —
  including real partial failures (e.g. computer offline while the controller is up).
- **Grafana dashboard:** headline stats (total / online / offline / in-meeting),
  offline-rooms-over-time, an active-issues list, and a 136-tile status grid
  (red = offline).
- Run the poller for a few days before the demo so the history graphs are populated.

---

## 5. Data model

| Object | Zabbix mapping |
|---|---|
| Region | Host group `Rooms/Singapore` |
| Room | Host (visible name = full room name; tags region/building/floor) |
| Room status | Item `zoom.room.status` (text) + `zoom.room.online` (1/0) |
| Devices (subset) | `zoom.device.computer.status`, `zoom.device.controller.status` |
| Fleet rollups | Host `SG Fleet Summary`: `zoom.fleet.{total,online,offline,inmeeting}` |
| Offline trigger | `min(/Template Zoom Room/zoom.room.online,#2)=0` — High |
| Device trigger | `last(.../zoom.device.*.status)=0` — Average |

Detection logic lives in **Zabbix triggers**, not in the bridge — so thresholds
can be tuned without redeploying code.

---

## 6. Operating notes

```bash
deploy/zabbix-stack.sh status          # pod / container / volume status
deploy/zabbix-stack.sh logs server     # logs: db | server | web | grafana
deploy/zabbix-stack.sh down            # stop pod, keep DB volume
deploy/zabbix-stack.sh destroy         # stop + delete volumes (full reset)
```
- **Podman must be running** for the stack: `podman machine start` (it does not
  auto-start after reboot). To keep the poller alive across reboots, run it as a
  macOS LaunchAgent rather than a foreground process.
- DB persists in volume `zabbix-pgdata`; Grafana in `zabbix-grafana`.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `address already in use` on stack up | Another service holds 8080/3000/10051. Override `WEB_PORT`/`GF_PORT`/`TRAP_PORT`. |
| Grafana shows no new rooms after provisioning | Datasource cache. `podman restart zabbix-poc-grafana` or set cacheTTL=0 (already done by `configure-grafana.sh`). |
| Scope check says GATE BLOCKED | Add the listed scopes to the Server-to-Server OAuth app in the Zoom Marketplace, then re-run. |
| Trapper `failed: N` | The host/item doesn't exist yet — run `run_provision.sh` before `run_poll.sh`. |
| `vfkit exited unexpectedly` | Intel Podman on Apple Silicon — install native arm64 Podman, recreate the machine. |

---

## 8. Security

- `bridge/.env` is gitignored — never commit it. `.env.example` holds placeholders only.
- POC uses simple Zabbix/Grafana passwords; change them for any shared/long-lived use.
- Rotate the Zoom client secret if it is ever exposed.

---

## 9. Scope & next phases

**In this POC:** offline + device-disconnect, Singapore fleet, dashboard-only.

**Deferred (per the design):** call-quality / QSS metrics, webhooks (real-time),
multi-region RBAC, alerting to email/Teams/Slack, and Logitech Sync / Yealink
enrichment. Each is an additive step on the same architecture — nothing built
here is thrown away.
