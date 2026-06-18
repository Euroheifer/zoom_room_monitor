# Zoom Room Issue Monitoring — Design

**Date:** 2026-06-18
**Status:** Approved design, pre-implementation
**Author:** luhl@sea.com (with Claude Code)

## 1. Purpose

Build a long-term monitoring system for Zoom Rooms that provides:

1. **Live view** of all current issues affecting any Zoom Rooms.
2. **Historical review** of issues for any room, for incident investigation and long-term reliability analysis.

The system is greenfield, built on **Zabbix + Grafana**, and designed for a fleet of **300+ rooms across multiple regions** with **local IT teams** per region.

## 2. Scope

### In scope — issue types to detect
1. **Device/room offline** — controller or compute unreachable.
2. **Peripheral disconnected** — camera, mic, speaker, display, or controller not detected.
3. **Call-quality degradation** — packet loss, jitter, latency, audio/video drops during meetings.
4. **Display / signal issues** — TV off, no HDMI, content-share failures.
5. **Software / health** — failed updates, app crashes, high CPU/temperature.

### Explicitly out of scope (for now)
- **Calendar / scheduling sync** monitoring (deprioritized by stakeholder).

### Fleet characteristics
- 300+ rooms, multiple regions, local IT teams per region.
- Hardware: predominantly **Logitech** and **Yealink**, with **iPad** controllers.

## 3. Architecture

Four layers:

```
Zoom APIs / webhooks / QSS ─┐
                            ├─► Bridge service ─► Zabbix ─► Grafana
(later) Logitech / Yealink ─┘     (poll + push)   (brain)   (dashboards)
                                                     │
                                              alerting → email/Teams/Slack
```

1. **Sources** — Zoom (Device Management API, Dashboard/Metrics API, QSS quality stream, webhooks). Later: Logitech Sync + Yealink Management Cloud (YMCS) for enrichment.
2. **Bridge** — a thin, stateless custom service. The only significant software we build. It *polls* Zoom on a schedule (source of truth for state) and *receives* webhooks/QSS (real-time accelerators), normalizes the data, and writes it into Zabbix.
3. **Zabbix** — the brain. Rooms are hosts; issues are triggers; regions are host groups. Handles detection, alerting/escalation, RBAC, and tiered retention.
4. **Grafana** — the face. Team-scoped dashboards for live fleet view and historical drill-down, reading from Zabbix.

**Guiding principle:** keep the bridge thin and stateless. All logic about *what counts as an issue*, *who gets alerted*, and *how long to keep data* lives in Zabbix configuration, not in code — so the team can tune thresholds without redeploying.

## 4. The Bridge & Data Sources

The bridge is the only real piece of software built for this system.

### Data sources

| Source | Type | Provides | Catches |
|---|---|---|---|
| **Device Management API** | Poll (1–5 min) | Room/device online state, inventory, peripheral connection status, app/firmware versions | Offline (1), peripheral (2), display (4), health (6) |
| **Dashboard / Metrics API** | Poll (1–5 min) | Per-room call-quality metrics (loss, jitter, latency, A/V) during meetings | Call quality (3) |
| **Webhooks** | Push (real-time) | Event-driven alerts: online/offline transitions, sensor/health alerts | Fast detection of 1, 2, 6 |
| **QSS (Quality of Service Subscription)** | Push stream (real-time) | Live in-meeting quality telemetry | Real-time call quality (3) |

### Poll *and* push, deliberately
Webhooks/QSS are fast but can be missed (network blips, Zoom-side gaps). Polling is the safety net that guarantees state is eventually correct. **Polling is the source of truth for state; webhooks/QSS are accelerators.** This avoids "dashboard says online but it's been dead for an hour."

### Writing to Zabbix
Each room maps to a Zabbix host. Values are sent via the **trapper** item type (push ingestion). Polled metrics and pushed events land in the same per-room items, so triggers are agnostic to which path delivered the data.

### Known dependency
QSS and richer Dashboard metrics generally require a **Zoom paid add-on / specific license tier and API scopes**. This must be verified — but Phase 1 needs only standard Device Management + Dashboard APIs, so it is not a blocker to start.

## 5. Data Model & RBAC

### Rooms as hosts, organized by region
- Each Zoom Room = one **Zabbix host** with a consistent name (e.g. `SG-L12-Boardroom`).
- Each region = one **host group** (e.g. `Rooms/Singapore`, `Rooms/London`). Each room belongs to its region's group.
- **Host metadata** (inventory/tags) per room: region, site/building, floor, hardware vendor (Logitech/Yealink), controller type (iPad), room capacity. Tags enable filtered views (e.g. "all Yealink rooms in SG with peripheral issues").

### Per-room items
Online state; each peripheral's connection status (camera/mic/speaker/display/controller); call-quality metrics (loss/jitter/latency); app & firmware version; CPU/temperature where available.

### Region determination
The bridge derives a room's region from **Zoom's location hierarchy** (Country → City → Building → Floor) as the primary source, falling back to a **naming convention** where the hierarchy is incomplete. New rooms added in Zoom are scoped automatically.

### RBAC
- **User groups ↔ host groups.** A "Singapore IT" user group has read permission on `Rooms/Singapore` only; "Admin" has all groups.
- This single mapping enforces scoping **everywhere automatically** — Zabbix views, alerts, and Grafana dashboards (via the Zabbix datasource honoring permissions) all respect it.
- Grafana team-scoped folders mirror the regions; each team lands on its own home dashboard.

**Design principle:** region is a **first-class grouping**, not a per-dashboard filter — making "Singapore sees only Singapore, admin sees all" a structural guarantee.

## 6. Alerting

**Goal:** the right local team hears about *their* broken room fast, with minimal noise.

### Detection — Zabbix triggers (not in the bridge)
Each issue type becomes a trigger with a severity:

| Issue | Severity | Notes |
|---|---|---|
| Room offline | High | Confirmation window (e.g. unreachable 2 consecutive polls) to avoid flapping |
| Peripheral disconnected | Average/High | Severity depends on peripheral |
| Call-quality degraded | Warning/Average | Threshold on loss/jitter/latency during a live meeting |
| Display/signal issue | Average | |
| Software/health | Warning | Failed update, high CPU/temp |

### Routing
- Alerts route by **host group → user group**: a Singapore room's alert goes to the **Singapore IT** action only. Admins have a catch-all action.
- **Channels:** email + a per-region chat channel (Teams or Slack). For highest severity (offline during business hours), optional escalation/re-notify if unacknowledged.

### Noise control (built in from day one)
- **Confirmation windows** so a single missed poll doesn't fire.
- **Dependencies:** if a room is offline, suppress its peripheral/quality alerts.
- **Business-hours awareness:** quality alerts matter during meetings; offline alerts lower urgency overnight (Zabbix time periods).
- **Maintenance windows:** planned work suppresses alerts.

**Design principle:** one issue = one actionable alert to one team. Tuning for signal protects trust in the system.

## 7. Retention

Native Zabbix history/trends split:
- **History (full-resolution)** → **30 days**. Powers incident investigation and the live view.
- **Trends (hourly min/avg/max roll-ups)** → **2 years**. Powers reliability reporting, per-room/per-region trend analysis, and vendor accountability.
- Configured per-item, so high-volume metrics (call quality) and slow state metrics (online/offline) get appropriate settings. Disk sizing is predictable from item counts × poll frequency.

## 8. Dashboards (Grafana)

- **Live fleet board** — current issues across all rooms (admin) or the user's region (local team): status grid + active-issue list, auto-refreshing.
- **Room drill-down** — any room's full history (30-day detail + long-term trends) for incident review.
- **Reliability / reporting board** — issues by region, vendor, and issue type over time.

## 9. Rollout Phases

1. **Phase 1 — Foundation:** stand up Zabbix + Grafana; build the polling bridge (Device Management + Metrics); model rooms/regions/RBAC; basic triggers + alerting; live + drill-down dashboards. *Complete, useful system on its own.*
2. **Phase 2 — Real-time:** add webhooks + QSS for faster detection; verify Zoom license/scopes.
3. **Phase 3 — Enrichment:** integrate Logitech Sync + Yealink YMCS for deeper peripheral/firmware data the Zoom API does not expose.

## 10. Testing Strategy

- **Bridge:** unit-test the Zoom→Zabbix mapping against recorded/sample Zoom API payloads (no live rooms required for parsing tests); integration-test against a Zabbix sandbox.
- **Triggers/alerts:** inject synthetic values into a test room host to fire each trigger; confirm region-only routing and dependency suppression.
- **RBAC:** log in as a regional test user; confirm only their rooms appear in both Zabbix and Grafana.
- **Pilot:** run Phase 1 against one region before fleet-wide rollout to validate thresholds against real-world noise.

**Design principle:** every phase ends in something usable; validate with synthetic data + a single-region pilot before trusting it fleet-wide.

## 11. Open Items / Prerequisites

- **Access:** obtain Zabbix and Grafana access/environments (stakeholder action).
- **Zoom licensing:** verify which APIs/scopes the current Zoom plan exposes, especially QSS and richer Dashboard metrics (needed for Phase 2).
- **Zoom location hierarchy:** confirm it is populated consistently enough to drive region mapping; document the naming-convention fallback.
- **Chat channel choice:** Teams vs Slack for per-region alert routing.
