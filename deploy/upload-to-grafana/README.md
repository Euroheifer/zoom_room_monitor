# Upload these to Grafana

Only the UI-importable dashboard files live here (symlinks — always the
current version). Grafana → Dashboards → New → Import → upload:

| File | Dashboard |
|---|---|
| `grafana-fleet.import.json` | **Zoom Rooms — Fleet Overview** — HQ/global view: totals, offline-by-region tiles (click one to drill in), all-region issues. No variables |
| `grafana-region.import.json` | **Zoom Rooms — Region** — one region at a time (`$region` single-select, `$building` single, `$floor` multi). Share as `/d/zoom-region?var-region=BR` with a local team |
| `grafana-dashboard.import.json` | Zoom Rooms — Singapore (superseded by the two above) |
| `grafana-dashboard-cngr.import.json` | Zoom Rooms — CNGR (fleet) |
| `grafana-room-detail.import.json` | Zoom Room — Detail (shared drill-down) |

Each import prompts for the Zabbix datasource; accept "overwrite" when
re-importing. Never upload the non-`.import` JSONs from `deploy/` — those
are the repo-canonical versions with the local datasource uid baked in.
