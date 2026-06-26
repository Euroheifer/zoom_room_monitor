# Zoom Room Monitoring — Laptop POC Demo Design

**Date:** 2026-06-26
**Status:** Approved design, pre-implementation
**Author:** luhl@sea.com (with Claude Code)
**Parent design:** [2026-06-18-zoom-room-monitoring-design.md](2026-06-18-zoom-room-monitoring-design.md)

## 1. Purpose

A laptop-hosted proof-of-concept whose single goal is to **sell the Zoom Room
monitoring concept to stakeholders**. It runs a real, working slice of the
approved Zabbix + Grafana architecture and shows a Grafana dashboard with the
**live status and recent real history** of a handful of real Zoom Rooms.

Success criterion: in a meeting, you can open the dashboard and credibly say
*"this is the real architecture, running on real fleet data."*

Because the POC is a faithful miniature of Phase 1 (not a throwaway mock), it
also **de-risks the real build** — every component here carries forward.

## 2. Scope

### In scope
- **Issue types:** room **offline (1)** and **peripheral / device disconnected
  (2)** only.
  - Offline comes from the Zoom **`/rooms` list** `status` field — one API call
    returns every room's status, so offline detection is cheap fleet-wide.
  - Peripheral/device comes from **`/rooms/{id}/devices`** per-device `status`
    (Zoom Rooms Computer + Controller) — one call *per room*, so it is limited to
    a small subset to respect rate limits.
- **Fleet:** the **full Singapore fleet (~136 rooms)** for offline/status
  detection, in one region host group (`Rooms/Singapore`); **peripheral/device
  detection on a subset (~5 rooms)**. (Scope decision 2026-06-26: expanded from
  the original 3–5 rooms because fleet-wide offline detection is a single API
  call and a real 136-room board is far more convincing for the pitch.)
- Region/building/floor are derived from the **room naming convention**
  (`SG-{building}-{floor}-{room} | {number}`), since the location-hierarchy API
  scope is not granted (confirmed by the scope check).
- **Bridge:** the real thin Python bridge, polling every 1–5 minutes. Run
  continuously for a few days before the demo to accumulate real history.
- **Dashboard:** one Grafana dashboard — status grid + active-issue list,
  auto-refreshing.

### Out of scope (deferred; mention verbally in the pitch)
- Call-quality / QSS metrics (need paid Zoom scopes — Phase 2).
- Webhooks / real-time push (Phase 2).
- Multi-region RBAC (single region only here; the host-group structure is shown,
  full user-group scoping is described, not built).
- Alerting to email / Teams / Slack — **dashboard-only** for this POC.
- Logitech Sync / Yealink YMCS enrichment (Phase 3).

### Demo narrative
Show real rooms' **current status plus their real recent history** (rooms
naturally go offline overnight). No live unplugging of rooms on cue. History is
accumulated by running the poller for several days ahead of the demo.

## 3. Architecture

A small but real instance of the approved architecture:

```
Zoom Device Management API ─► bridge (Python, poll) ─► Zabbix (Podman) ─► Grafana (Podman)
                                                          hosts   = rooms     Zabbix datasource
                                                          group   = region    live dashboard
                                                          trapper items
                                                          offline / peripheral triggers
```

Layers:

1. **Bridge** — the only real software built. Small, stateless, testable units:
   - `auth` — Zoom Server-to-Server OAuth token acquisition.
   - `poller` — calls the Device Management API on a schedule.
   - `mapper` — normalizes Zoom payloads into per-room Zabbix values
     (online state, per-peripheral connection status).
   - `sender` — pushes values to Zabbix via **trapper** items.
2. **Zabbix** (Podman: server + Postgres + web) — the brain. Each room is a
   host; the region is a host group; each room has trapper items; two triggers
   (offline, peripheral disconnected) with confirmation windows to avoid
   flapping.
3. **Grafana** (Podman) — the face. Zabbix datasource; one dashboard.
4. **Provisioning script** — uses the Zabbix API to create hosts/items/triggers
   reproducibly (not hand-clicked), so the environment can be rebuilt cleanly
   before the demo.

**Guiding principle (inherited):** keep the bridge thin and stateless. What
counts as an issue lives in Zabbix configuration, not in code.

## 4. Data Model

- Each Zoom Room → one Zabbix host. Visible name = full room name (e.g.
  `SG-5SPD-2F-Eric Bui | 6898`); technical name = the same, sanitized of
  characters Zabbix disallows (e.g. `|`). Host tags `region`, `building`,
  `floor` parsed from the name.
- Region → one host group: `Rooms/Singapore`.
- **Templates** carry the items/triggers (linked to hosts, so we don't create
  136 × N items by hand):
  - **`Template Zoom Room`** (all SG hosts) — trapper items
    `zoom.room.status` (text) and `zoom.room.online` (0/1, derived: Offline→0,
    else 1); plus the offline trigger.
  - **`Template Zoom Room Devices`** (subset only) — trapper items per device
    role `zoom.device.computer.status`, `zoom.device.controller.status` (0/1),
    plus app/firmware text items; plus the device-disconnected trigger.
- Triggers:
  - **Room offline** — High severity; fires when the last 2 polls are offline
    (`min(/host/zoom.room.online,#2)=0`) to avoid flapping.
  - **Device disconnected** — Average severity; fires when a tracked device’s
    status is 0 (subset hosts only).

## 5. Build Order

Sequenced to hit the riskiest unknown first.

1. **Verify Zoom scopes (first gate).** Make the smallest possible Device
   Management API call with the existing app and confirm it returns Zoom Room /
   device status. If scopes are missing, request them before building further.
2. **Stand up Zabbix + Grafana** as Podman containers on the laptop.
3. **Bridge happy path** — auth → poll → map → push one real room's status into
   Zabbix.
4. **Provisioning script** — create the 3–5 rooms + triggers via the Zabbix API.
5. **Grafana dashboard** — status grid + active-issue list, reading from Zabbix.
6. **Accumulate + polish** — run the poller continuously to build real history;
   refine the dashboard for presentation.

## 6. Error Handling

- **Scope/auth failures** are surfaced at the first gate; the build does not
  proceed past step 1 without confirmed API access.
- The poller handles Zoom auth token refresh and API rate limits.
- **Polling is the source of truth for state** — a missed poll self-corrects on
  the next cycle; no stale "online" left on the dashboard.

## 7. Testing

- **Mapper:** unit-tested against a saved sample Zoom Device Management payload —
  no live rooms required for parsing.
- **Ingestion:** confirm end-to-end trapper ingestion with one real room.
- **Triggers:** fire each trigger once by injecting a synthetic value into a
  throwaway test host. Build-time validation only — the live demo uses real data.

## 8. Prerequisites

- Confirm the existing Zoom app's Device Management read scopes (step 1 above).
- Podman machine running locally (already set up on this laptop).
- Network access to the Zoom API (corporate network / VPN as required).

## 9. Relationship to the Parent Design

This POC is a single-region, dashboard-only, offline+peripheral slice of
**Phase 1 — Foundation** from the parent design. The bridge, Zabbix data model,
and Grafana dashboard built here are the seeds of the real Phase 1 system;
extending to the full fleet means adding regions, the remaining issue types
(call quality, display, health), alerting/RBAC, and the Phase 2/3 real-time and
enrichment sources.
