# Zoom Room Monitoring — Fleet Visibility

> **Know the moment a meeting room goes dark — across the whole fleet.**

Monitors **real Zoom Rooms** through a **Zabbix + Grafana** stack — with the poller
running **inside Zabbix itself** (a script item), so there is no extra server,
VM, or laptop to keep alive. Live today on **135 Singapore rooms** on company
infrastructure; designed to scale to the ~700-room global fleet by config.

![Zabbix 6.4+](https://img.shields.io/badge/Zabbix-6.4%2B-CC0000?logo=zabbix&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-Zabbix_plugin-F46800?logo=grafana&logoColor=white)
![Python 3](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Status](https://img.shields.io/badge/status-live_in_production-success)

![Grafana dashboard — online/offline headline stats, offline-over-time, active issues, and the fleet status grid](docs/images/dashboard.png)

---

## The problem

Meeting rooms fail **silently**. A controller drops off Wi-Fi, a room PC won't wake,
a device quietly unpairs — and nobody knows until someone walks into an important
meeting and the room is dead. At fleet scale, "wait for a ticket" isn't a strategy.

**This makes the invisible visible** — continuous, fleet-wide health for every
room, so IT sees the failure before the user does.

## What it does

- ✅ **Every room a first-class Zabbix host**, named and tagged (building / floor)
  from the **Zoom location directory** — the source of truth, immune to
  room-name spelling drift.
- ✅ **Offline detection** fleet-wide with anti-flap (2 consecutive missed polls
  → High alert, ~10 min detection at the 5-min interval).
- ✅ **Device-disconnect detection** (room PC / controller) via a rotating
  polling window — catches *partial* failures, with alerts suppressed while the
  whole room is offline (one incident, one row).
- ✅ **Self-monitoring feed** — the collector reports its own cycle summary and
  a `nodata` watchdog trigger fires if it ever stops.
- ✅ **Grafana dashboards for helpdesk**: Building/Floor filters (each team sees
  their own rooms), filtered online/offline stats, active-issues work queue,
  fleet status grid, resolved-issues history, and per-room 30-day drill-downs.
- ✅ **Everything as code** — provisioning, the collector, and the dashboards
  live in this repo; every piece is idempotent and re-runnable.

## Architecture

```mermaid
flowchart LR
    Z["Zoom Rooms / Devices /<br/>Locations API"] <-->|"poll every 300s<br/>(script item, JS)"| S["Zabbix Server<br/>collector · hosts · triggers · history"]
    S --> P[("DB")]
    S -->|Zabbix API| G["Grafana<br/>dashboards + filters"]
    B["provision.py<br/>(run on room changes)"] -->|JSON-RPC| S
    G -->|view| U["📊 Helpdesk / IT"]
```

**Why this shape:**

- **Zero custom infrastructure** — the collector (`bridge/collector.js`) runs *inside*
  the Zabbix server as a script item and feeds the same trapper items via
  `history.push`. Nothing to host, restart, or babysit.
- **Detection logic lives in Zabbix triggers, not code** — thresholds tune without redeploys.
- **The location directory drives structure** — move a room in Zoom, re-run
  provisioning, and hosts/tags/dashboard filters follow.

## Quick start (existing Zabbix + Grafana)

> **Prerequisites:** Zabbix 6.4+ whose server has outbound HTTPS to `api.zoom.us`,
> an account/API token with host+template create rights, Grafana with the Zabbix
> app plugin, and a Zoom Server-to-Server OAuth app (room/device/location read
> scopes). Full checklist + verification steps: [`docs/SETUP.md`](docs/SETUP.md).

```bash
# 1. Configure credentials
cd bridge && cp .env.example .env      # fill in Zoom + Zabbix values

# 2. Gate check (Zoom scopes, read-only)
./run_check.sh                         # must print GATE PASSED

# 3. Provision Zabbix: host group, 3 templates, one host per room
./run_provision.sh                     # idempotent — re-run on room changes

# 4. Install the in-Zabbix collector (script item + secret macros + watchdog)
./run_install_collector.sh             # data flows within one 5-min cycle

# 5. Import the dashboards into Grafana (UI: Dashboards -> New -> Import)
#    deploy/grafana-dashboard.import.json  + deploy/grafana-room-detail.import.json
#    — each prompts for your Zabbix datasource.
```

Healthy collector value (Monitoring → Latest data → `zoom.bridge.run`):

```
{"rooms":135,"offline":4,"subset":15,"items":326,"failed":0}
```

**Sizing:** keep `ceil(rooms / subset_size) × interval` under the device triggers'
stale window (`DEVICE_STALE_WINDOW`, default 1h). 135 rooms → subset 15 sweeps in
~45 min. At ~700 rooms: `PERIPHERAL_SUBSET_SIZE=30`, `DEVICE_STALE_WINDOW=3h`.

## Project layout

| Path | What's in it |
|---|---|
| [`bridge/`](bridge/) | `collector.js` (the in-Zabbix poller) + `install_collector.py`, `provision.py` (hosts/templates/triggers from the Zoom location directory), scope checker, and a standalone Python poller for local testing. |
| [`deploy/`](deploy/) | Grafana dashboard JSONs (`*.import.json` = UI-importable), plus the self-contained local demo stack (Podman) and its scripts. |
| [`docs/`](docs/) | [`SETUP.md`](docs/SETUP.md) build guide · [`LOCAL-POC.md`](docs/LOCAL-POC.md) laptop demo · design specs under `docs/superpowers/specs/`. |

## Local demo mode

The original POC ran this entire stack self-contained on one laptop — Zabbix +
Grafana in a Podman pod, polled by `run_poll.sh` (or a reboot-durable macOS
LaunchAgent). That mode still works for demos without touching shared
infrastructure: `deploy/zabbix-stack.sh up` and follow [`docs/LOCAL-POC.md`](docs/LOCAL-POC.md).

## Roadmap

| Done | Next (additive) |
|---|---|
| Offline + device-disconnect detection | Zoom webhooks (real-time events; polling stays as safety net) |
| Singapore fleet on company Zabbix/Grafana | Remaining countries (~700 rooms) — per-region provisioning + dashboards |
| Building/Floor helpdesk filters | Alerting to email / Teams / Slack |
| Location-directory-driven naming | Call-quality / QSS metrics · Logitech Sync / Yealink enrichment |

## Security

- Credentials live only in the **gitignored** `bridge/.env` and as **secret host
  macros** in Zabbix — never committed, never in dashboards.
- All Zoom scopes are read-only. Rotate the client secret / API tokens on
  exposure: update the macro and re-run the installer.

---

<sub>Built on Zabbix · Grafana OSS · Python · and one JavaScript file that replaced a server.</sub>
