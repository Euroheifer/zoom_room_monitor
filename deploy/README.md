# POC stack — Zabbix + Grafana on Podman

Local proof-of-concept infrastructure for the Zoom Room monitoring demo.
See [../docs/superpowers/specs/2026-06-26-zoom-room-monitoring-poc-design.md](../docs/superpowers/specs/2026-06-26-zoom-room-monitoring-poc-design.md).

## Prerequisites
- Podman installed and the machine running (`podman machine start`).
  The stack needs ~4 GiB; bump with `podman machine set --memory 4096` while stopped.

## Start / stop
```bash
./zabbix-stack.sh up        # pull images, create pod, start everything
./zabbix-stack.sh status    # pod / container / volume status
./zabbix-stack.sh logs server   # logs for db|server|web|grafana
./zabbix-stack.sh down      # remove pod, keep DB volume
./zabbix-stack.sh destroy   # remove pod AND volumes (full reset)
```

## Endpoints
| Service   | URL                     | Login          |
|-----------|-------------------------|----------------|
| Zabbix UI | http://localhost:8080   | `Admin` / `zabbix` |
| Grafana   | http://localhost:3001   | `admin` / `admin`  |
| Zabbix trapper (for the bridge) | `localhost:10051` | — |

> Grafana is on **3001** because a native Grafana already holds **3000** on this
> machine. Override any port: `GF_PORT=3002 WEB_PORT=8090 ./zabbix-stack.sh up`.

## Grafana → Zabbix wiring
After `up`, enable the Zabbix app plugin and add the datasource:
```bash
./configure-grafana.sh
```
This is idempotent and points Grafana at the Zabbix API over the pod's localhost.

## Notes
- Single Podman **pod**: all containers share `localhost`, so the bridge sends to
  `localhost:10051` and Grafana reaches Zabbix at `localhost:8080`.
- DB persists in the `zabbix-pgdata` volume; Grafana state in `zabbix-grafana`.
- POC-only credentials (simple passwords). Not for production.
