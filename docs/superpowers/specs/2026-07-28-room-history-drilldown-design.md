# Room History Drilldown — Design

**Date:** 2026-07-28
**Status:** Approved

## Goal

From the main dashboard, click an active issue (or a room tile) and land on a
per-room history view covering at least the last 30 days: when the room was
offline, for how long, and what its devices were doing.

## Background / constraints

- Zabbix history retention for room items is currently 31d (oldest data
  2026-06-27) — enough for a 30-day view but with no margin. Bump to 90d.
- Device items (`zoom.device.*`) are only collected while a room is in the
  poller's 5-room subset (offline rooms first), so per-room device history has
  gaps by design.
- The current "Active issues" panel is `alexanderzobnin-zabbix-triggers-panel`,
  which has poor per-row data-link support.

## Design

### 1. New dashboard: `zoom-room-detail`

Default time range `now-30d`. Template variable `$room` = Zabbix host from
group `Rooms/Singapore`.

Panels:

| Panel | Source | Notes |
|---|---|---|
| Online/offline state timeline | `zoom.room.online` | green=1 / red=0 bands |
| Uptime % stat | avg(`zoom.room.online`) × 100 over range | |
| Outage & issue events table | Zabbix problem events for `$room` | offline + device-disconnect triggers; start, duration, resolved/active |
| Device status timeline | `zoom.device.computer.status`, `zoom.device.controller.status` | gaps expected; panel description says why |
| Current status + versions | `zoom.room.status`, `zoom.device.*.version` | stat/text |

### 2. Click-through from main dashboard

- Replace the triggers panel with a standard **table panel** fed by a Zabbix
  problems query; add a per-row data link:
  `/d/zoom-room-detail?var-room=${__data.fields.host}&from=now-30d&to=now`
- Add the same data link to the 136-tile status grid stat panel.

### 3. Retention bump

`bridge/provision.py`: room/device/fleet trapper items get `history: 90d`.
`ensure_items` currently skips existing items entirely — extend it to update
retention on existing items so the bump applies to the live stack on
reprovision.

## Files touched

- `deploy/grafana-room-detail.json` — new dashboard
- `deploy/grafana-dashboard.json` — issues panel swap + grid data links
- `deploy/import-dashboard.sh` — import both dashboards
- `bridge/provision.py` — history 90d + retention update for existing items

## Error handling

- Missing device history renders as gaps, not errors (panel description
  explains the subset behaviour).
- `$room` with no history in range: timeline shows "No data"; events table
  empty — acceptable.
- Import script keeps its loud-failure behaviour (`GF_ADMIN_PASS` env var).

## Testing

1. Reprovision; verify item retention is 90d in Zabbix.
2. Import both dashboards.
3. Click the `SG-Galaxis-17F-Charles Yang 6284` offline issue (offline since
   June — long-outage sample): detail dashboard opens with the room
   preselected, 30d range, outage duration visible.
4. Verify device timeline shows data while the room is in the subset and gaps
   elsewhere.
5. Click a healthy room tile in the grid: uptime ~100%, empty events table.

## Out of scope

- Alerting/notifications (separate roadmap item).
- Longer-than-90d retention or trend-based views.
- Historical device coverage for rooms never in the subset.
