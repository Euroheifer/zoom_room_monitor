# Zoom Room Monitoring — Build Guide (existing Zabbix + Grafana)

A step-by-step guide to stand up Zoom Room fleet monitoring on an existing
Zabbix + Grafana. Follow it top to bottom and you end with: every room a Zabbix
host, offline + device-disconnect alerting, and Grafana dashboards with
Building/Floor filters — with **the poller running inside Zabbix itself**
(no laptop, VM, or extra server).

For the self-contained laptop demo (Podman stack), see
[`LOCAL-POC.md`](LOCAL-POC.md) instead.

> ⚠️ **Secrets:** never commit or paste the Zoom client secret / Zabbix API
> tokens. They belong only in the gitignored `bridge/.env` and in Zabbix
> **secret macros**.

---

## 0. Prerequisites

| # | Prerequisite | How to check / get it |
| --- | --- | --- |
| 1 | **Zabbix 6.4+** (7.x recommended) | `curl -sk <ZABBIX_URL>/api_jsonrpc.php -H 'Content-Type: application/json-rpc' -d '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}'` — needs 6.4+ for `history.push` and script items |
| 2 | Zabbix account with **create rights** for host groups, templates, hosts, items, triggers | Zabbix UI → Data collection → Hosts: you must see a **Create host** button |
| 3 | A **Zabbix API token** | Zabbix UI → User settings → API tokens → Create |
| 4 | Zabbix **server** has outbound HTTPS to `zoom.us` + `api.zoom.us` | Ask the Zabbix admins — the collector runs *on the server* |
| 5 | **Grafana** with the Zabbix app plugin + a datasource for your Zabbix | Grafana → new panel → datasource picker shows "Zabbix". If not: admin installs `alexanderzobnin-zabbix-app`, adds a datasource (URL = `<ZABBIX_URL>/api_jsonrpc.php`, an API token, *Skip TLS verify* if self-signed) |
| 6 | A **Zoom Server-to-Server OAuth app** with read scopes: List Zoom Rooms + status, Room devices, Room locations (all **required**); **Dashboard** (`dashboard_zr:read:admin`) for mic/speaker/camera/battery health (strongly recommended — collector degrades gracefully without it) | Zoom Marketplace → Develop → Build App. Note the **Account ID / Client ID / Client Secret** |
| 7 | Any machine with **Python 3.11+** and `git` for the one-time setup | Nothing keeps running on it afterwards |
| 8 | Zoom **location directory** populated: every room on a floor, floors under buildings/campuses | Zoom admin portal → Rooms → Location directory. "Unassigned Rooms" should be 0 — this drives the Building/Floor filters |

## Step 1 — Clone and configure

```bash
git clone https://github.com/Euroheifer/zoom_room_monitor.git
cd zoom_room_monitor/bridge
cp .env.example .env    # then edit:
```

```
ZOOM_ACCOUNT_ID=...                                   # from the S2S OAuth app
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...
ZBX_API_URL=https://<your-zabbix>/api_jsonrpc.php
ZBX_API_TOKEN=<your Zabbix API token>
ZBX_TRAPPER_HOST=<your-zabbix-host>                   # only for optional manual testing
ZBX_SSL_VERIFY=false                                  # only if the cert chain is self-signed
REGION_PREFIX=SG                                      # region code: name prefix + host/dashboard naming
# When rooms DON'T share a name prefix, select them by location-directory
# subtree instead (this is how CNGR runs):
#LOCATION_ROOT=CNGR                                   # directory node name
#HOST_GROUP=Rooms/CNGR                                # Zabbix host group (default Rooms/Singapore)
#STRIP_CAMPUS_PREFIX=0                                # keep city-prefixed campus names (BJ-JinHui)
```

## Step 2 — Gate check: Zoom scopes

```bash
./run_check.sh          # must print GATE PASSED
```

If **GATE BLOCKED**, it lists the missing scopes — add them to the S2S app in
the Zoom Marketplace and re-run. (This also builds the Python venv.)

## Step 3 — Gate check: Zabbix API

```bash
curl -sk $ZBX_API_URL -H 'Content-Type: application/json-rpc' \
  -H "Authorization: Bearer $ZBX_API_TOKEN" \
  -d '{"jsonrpc":"2.0","method":"host.get","params":{"countOutput":true},"id":1}'
```

A number back = URL, token, and permissions all work.

## Step 4 — Provision Zabbix

```bash
./run_provision.sh
```

Creates (idempotent — re-run any time):

- Host group **`Rooms/<Region>`**, template group **`Templates/Zoom`**.
- **Template Zoom Room** — `zoom.room.status` (text) + `zoom.room.online` (1/0,
  90d history) + `zoom.room.health` / `zoom.room.issues` (dashboard-metrics
  peripheral state); trigger *"Room {HOST.NAME} is offline"* fires after **2
  consecutive** offline polls (anti-flap), severity High; a device/peripheral
  trigger **named by the live issue text** (`{ITEM.LASTVALUE1}`, e.g. *"Selected
  microphone has disconnected"*, *"Controller disconnected"*), severity Average
  (shown as **Medium**), **dependent on the room-offline trigger** (a dead room
  raises one alert, not several).
- **Template Zoom Room Devices** — computer/controller status + version items,
  **history only, no triggers**: the devices API's status field is unreliable
  (rooms Zoom itself reports healthy can carry a permanently-Offline computer
  record), so disconnect alerting runs on the dashboard-metrics issues feed —
  the same source as Zoom's own Room Health page.
- **Template Zoom Fleet** — `zoom.fleet.{total,online,offline,inmeeting}`.
- **One host per room** (both templates linked). Technical name = sanitized
  Zoom room name (data lands by it; never changes). **Visible name =
  `{REGION}-{building}-{floor}-{room}` derived from the Zoom location
  directory** — the canonical form the dashboard filters parse; re-runs
  re-sync it. Cosmetic exceptions go in `LOCATION_OVERRIDES` in `provision.py`.
- Fleet summary host **`<REGION>-Fleet-Summary`**.

**Verify:** Zabbix UI → Data collection → Hosts → filter the group — one host
per room, correctly named.

## Step 5 — Install the in-Zabbix collector

```bash
./run_install_collector.sh
```

Creates on the fleet-summary host:

- **Script item `zoom.bridge.run`** (`bridge/collector.js`, interval **300s**,
  timeout 60s). Each cycle: Zoom OAuth → `GET /rooms` → `GET /rooms/{id}/devices`
  for a rotating **15-room window** over the online fleet → `GET
  /metrics/zoomrooms` (fleet-wide peripheral health, best-effort if the
  Dashboard scope is missing) → fleet rollups → one `history.push` call
  feeding the trapper items.
- **Credential macros** `{$ZOOM.*}` / `{$ZOOM.ZBX.*}` (secrets as secret macros).
- **Watchdog trigger** *"Zoom collector stopped reporting"* (`nodata 10m`, High).

**Verify (within ~5 min):** Monitoring → Latest data → `zoom.bridge.run`:

```
{"rooms":135,"offline":4,"subset":15,"items":326,"failed":0}
```

`failed: 0` is the health signal; then spot-check a room host's `zoom.room.online`.

**Sizing:** all alerting runs on per-cycle fleet-wide feeds (room list +
metrics), so detection latency is ~one cycle for peripherals and ~2 cycles for
offline, at any fleet size. The rotating device sweep (`ceil(rooms /
subset_size) × interval`) only sets how fresh the per-room device
version/timeline data is — at ~700 rooms use `PERIPHERAL_SUBSET_SIZE=30` (~2h sweep).

## Step 6 — Import the Grafana dashboards

Grafana → **Dashboards → New → Import → Upload JSON file**, once per file
(accept "overwrite" on re-imports); each prompts for your Zabbix datasource.
**Upload from `deploy/upload-to-grafana/`** — that folder contains only the
importable files (symlinks, always current), so there is no wrong file to pick:

1. `grafana-dashboard.import.json` — SG fleet dashboard: Building/Floor
   filters, filtered Online/Offline stats, fleet offline trend, **Active
   issues** (rows disappear on recovery; peripheral rows named by the issue
   text), status grid (red = offline, click-through), **Resolved issues**
   within the time range.
2. `grafana-dashboard-cngr.import.json` — same layout for the CNGR fleet.
3. `grafana-room-detail.import.json` — per-room 30-day drill-down (region-agnostic,
   shared by all fleet dashboards; shows last-known status/health/issues/versions).

**Verify:** Online + Offline = your room count; picking one building shrinks
all panels; clicking a room tile opens its 30-day detail.

## Step 7 — Updating dashboards later

Dashboards live in git, not Grafana. Edit the JSON in `deploy/`, regenerate the
`.import.json`, re-import. If you edit in the Grafana UI, **export back to the
repo** (Share → Export) so git stays the source of truth.

---

## Setting up another country

CNGR is the live example:

1. Provisioning (per region, env-driven): in `.env` set `REGION_PREFIX=TH` and
   `HOST_GROUP=Rooms/TH`. If the region's rooms share a name prefix, that's
   enough; if not, add `LOCATION_ROOT=<directory node name>` to select by
   location subtree, and `STRIP_CAMPUS_PREFIX=0` if campus names carry
   meaningful prefixes (cities). Run the provisioning step.
2. Collector (one item serves ALL regions): add the region to the `REGIONS`
   table in `install_collector.py` — `{"name": "TH"}`, plus
   `"location_root": "..."` if it selects by subtree — and re-run
   `./run_install_collector.sh` once. The account-wide Zoom sweep is shared;
   the region's fleet host gets a `zoom.bridge.run` trapper + nodata watchdog.
3. Copy the fleet dashboard JSON: swap group filter, region regex prefixes,
   title, and `uid`; import (see `deploy/grafana-dashboard-cngr.json` for a
   worked example). The room-detail dashboard needs no copy.

## Routine operations

| Situation | Action |
| --- | --- |
| Rooms added / renamed in Zoom | `./run_provision.sh`. Renames create a new host — delete the old one if history isn't needed |
| Room moved building/floor | Fix the Zoom **location directory**, re-run provisioning |
| Zoom secret / Zabbix token rotated | Update `.env`, re-run `./run_install_collector.sh` |
| Collector health | Latest value of `zoom.bridge.run`; the watchdog fires on silence |
| Tune thresholds | Edit `provision.py` / env vars, re-run — triggers update in place |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Collector value shows `failed: N` | Rooms exist in Zoom that Zabbix doesn't know — re-run provisioning |
| "Zoom collector stopped reporting" | Open the `zoom.bridge.run` item — its error names the failing call. Usually rotated credentials |
| GATE BLOCKED | Add the listed scopes to the S2S app, re-run |
| SSL errors from the Python scripts | `ZBX_SSL_VERIFY=false` in `.env` |
| A building shows twice in the filter | Name drift — the location directory wins; re-run provisioning |
| Room missing from filtered views | No location assigned in Zoom — assign it, re-run provisioning |
| Panels intermittently error with an HTML "521" page | The Zabbix web frontend blipped — refresh; report to the Zabbix admins if frequent |
