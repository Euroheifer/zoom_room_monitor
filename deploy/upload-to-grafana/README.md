# Upload these to Grafana

Only the UI-importable dashboard files live here (symlinks — always the
current version). Grafana → Dashboards → New → Import → upload:

| File | Dashboard |
|---|---|
| `grafana-dashboard.import.json` | Zoom Rooms — Singapore (fleet) |
| `grafana-dashboard-cngr.import.json` | Zoom Rooms — CNGR (fleet) |
| `grafana-room-detail.import.json` | Zoom Room — Detail (shared drill-down) |

Each import prompts for the Zabbix datasource; accept "overwrite" when
re-importing. Never upload the non-`.import` JSONs from `deploy/` — those
are the repo-canonical versions with the local datasource uid baked in.
