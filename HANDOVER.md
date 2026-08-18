# HANDOVER — Zoom Room Monitor

Continuation notes for the next working session (human or Claude). Last
updated **2026-08-18**. Open work: see [`TODO.md`](TODO.md). Setup recipes:
[`docs/SETUP.md`](docs/SETUP.md).

## What this is

Fleet monitoring + alerting for the company's Zoom Rooms, running entirely on
company infrastructure (nothing on any laptop):

```
Zoom APIs ──(collector.js, script item INSIDE Zabbix, 5-min cycle)──► Zabbix items/triggers
                                                                        │
                       Grafana dashboards ◄──(Zabbix datasource)────────┤
                       SeaTalk group alerts ◄──(webhook media types)────┘
```

Live regions: **SG (139 rooms)** and **CNGR (24 rooms)** of ~760 in the Zoom
account. The **Zoom location directory is the single source of truth** for
region membership — room naming conventions are NOT trusted (test/VIP rooms
break them deliberately).

## Live inventory (zabbix.cit.insea.io, Zabbix 7.2.12)

| Object | ID / name |
|---|---|
| Collector script item (carrier, ALL regions) | `zoom.bridge.run` itemid **6528238** on `SG-Fleet-Summary`, 300s, 60s timeout |
| CNGR cycle-summary trapper | `zoom.bridge.run` itemid **6595415** on `CNGR-Fleet-Summary` |
| Watchdogs | `nodata(zoom.bridge.run,10m)` High trigger per fleet host |
| Host groups | `Rooms/Singapore` = **507**, `Rooms/CNGR` = **512** |
| Templates | room **40602**, devices **40603**, fleet **40604** |
| SeaTalk media types | `Seatalk-ZoomRooms-CNGR` = **151**, `-SG` = **152** (webhook URL baked into each script) |
| Trigger actions | `Zoom Rooms CNGR - SeaTalk alerts` = **280**, `... SG ...` = **281** (host group + severity ≥ Average, problem + recovery) |
| Alert identity | usergroup **88** `Zoom Rooms Alerts`, user **146** `svc-zoomrooms-seatalk` (Viewer, one media per destination, sendto `-`) |
| Grafana dashboards | company Grafana: fleet SG (`zoom-sg-poc`), fleet CNGR (`zoom-cngr-poc`), room detail (`zoom-room-detail`, region-agnostic) — import via `deploy/upload-to-grafana/` symlinks (UI upload, overwrite) |

Secrets live in `bridge/.env` (gitignored): `ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID /
ZOOM_CLIENT_SECRET` (S2S OAuth), `ZBX_API_URL / ZBX_API_TOKEN` (super-admin),
`ZBX_SSL_VERIFY=false` (self-signed cert), `SEATALK_WEBHOOK_URL` (CNGR group),
`SEATALK_WEBHOOK_URL_SG`. SeaTalk webhook URLs are post-to-group credentials —
never commit or publish them.

## How the pieces work

- **collector.js** (`bridge/`): one account-wide sweep per cycle — OAuth token
  → `/rooms` → `/rooms/locations` → `/metrics/zoomrooms` → per-region rotating
  15-room `/rooms/{id}/devices` subset — bucketed per the `REGIONS` table in
  `install_collector.py`, pushed via `history.push`. Rooms with Zoom status
  `UnderConstruction` report `issues=none` (alert suppression). Non-carrier
  regions get their cycle summary pushed to their fleet host's trapper.
  Zabbix JS is Duktape (ES5) — no `let/const/=>/`template literals`.
- **provision.py**: creates/updates hosts, host groups, templates, triggers
  from the directory (env-driven per region: `LOCATION_ROOT`, `REGION_PREFIX`,
  `HOST_GROUP`, `STRIP_CAMPUS_PREFIX`). Hosts are tagged
  `region`/`building`/`floor` from the directory — tags ride into trigger
  events (usable for per-building alert routing, see TODO §2). Renames create
  new hosts (old one keeps history until deleted). `LOCATION_OVERRIDES` pins
  "SG-Office" (private VIP room) to GLX/17F so its real location stays off
  helpdesk dashboards.
- **setup_seatalk.py CNGR|SG**: idempotent — clones house media type 42 with
  the region webhook + chat-friendly templates, ensures usergroup/user/action.
- **SeaTalk message format** (iterated with the user; lives in media type JS +
  message templates, and in `setup_seatalk.py` for fresh installs): payload
  `{"tag":"text","text":{"format":1,"content":...}}` — **format:1 renders
  markdown** (format:2 does not). Severity-colored circle (🟡 Medium / 🔴 High+
  / 🟢 resolved, chosen in JS from `{EVENT.NSEVERITY}`/`{EVENT.VALUE}`), bold
  room name, bold labels, one issue per bullet (JS splits `{EVENT.NAME}` on
  `"; "`), "Average"→"Medium" to match dashboards, **no timestamp** (the chat
  bubble's own time is within one poll and viewer-local). Rate limit 60/min
  per System Account.
- **Grafana**: datasource must have Trends=on, **trendsFrom=6h**, cacheTTL=5m
  — keeps every panel query under the gateway's ~10s timeout (see gotchas).
  Stat panels use 15m windows; tables limit 200.

## Runbooks

All commands from `bridge/`, with `.env` loaded
(`set -a && . ./.env && set +a`). **Zabbix-mutating scripts must be run by the
user** (Claude's permission layer blocks them) — in a Claude session, hand the
user a `! cd ... && ...` one-liner.

| Task | Command |
|---|---|
| Rooms added/renamed in Zoom | `LOCATION_ROOT=SG ./run_provision.sh` (per region; CNGR: `LOCATION_ROOT=CNGR REGION_PREFIX=CNGR HOST_GROUP=Rooms/CNGR STRIP_CAMPUS_PREFIX=0`) |
| Collector code change | edit `collector.js` → `./run_install_collector.sh` (once — serves all regions) |
| New region | TODO.md has the recipe + efficiency plan; docs/SETUP.md "Setting up another country" |
| New SeaTalk destination | group + System Account webhook (SeaTalk desktop, manual) → `.env` var → `setup_seatalk.py` entry → run |
| Health check | `zoom.bridge.run` lastvalue on both fleet hosts — `{"regions":{"SG":{"rooms":139,...,"failed":0},...}}`; `failed:4` ≈ one unprovisioned room (4 items) → run provision |
| Alert format change | `mediatype.update` on 151/152 (templates and/or script) AND mirror in `setup_seatalk.py`; preview by POSTing to the webhook directly |

## Gotchas (each cost us a debugging session)

1. **Gateway 521s**: the gateway in front of zabbix.cit.insea.io serves an
   HTML "521 Web server is down" page when the API takes ≳10s. During the
   2026-08-11 server overload (housekeeper 100%, 40k LLD backlog — CIT
   admins' problem, not ours) heavy Grafana queries died while light ones
   worked. Keep panel queries light; diagnose with `.env` creds by timing
   `apiinfo.version` vs `history.get`.
2. **Env-var regression class (fixed, stay dead)**: region selection once
   depended on install-time env vars; a reinstall without `LOCATION_ROOT`
   silently zeroed CNGR for ~3.5h (2026-08-14 gap on charts). Region config
   now lives ONLY in the installer's REGIONS table.
3. **Confluence quirks** (confluence.garenanow.com): rejects 4-byte emoji in
   page bodies (write `(red circle)` etc.); the MCP page-update endpoint
   fails against this server — **delete + recreate** is the workaround (page
   ID/URL changes; update links + memory). Literal `<placeholders>` in prose
   break the markdown→XHTML conversion — backtick them.
4. **SG-Fleet-Summary reinstalls overwrite macros** with `.env` values — fine
   today (one Zoom account), but revisit if a region ever gets its own creds.
5. Zabbix's default "User" role doesn't exist on this server — use "Viewer".

## Where things are documented

- Confluence (space `~luhl@sea.com`, under "Zoom Room Monitoring — Build
  Guide"): SeaTalk Alert Setup Guide (pageId **270649541**), Roadmap &
  Pending Work (pageId **270649652**), Add a New Region step-by-step
  (pageId **270650415**, newbie-friendly, MY as worked example).
- SeaTalk groups: "CNGR Zoom Room Alerts", "SG Zoom Room Alerts" (user owns
  them; webhooks in `.env`).
- Claude memory mirrors the headlines; this file and TODO.md are canonical.

## Immediate next steps (agreed with the user)

1. Global device-rotation budget in collector.js (gates mass onboarding).
2. Single region manifest + `onboard.py`.
3. Templated `$region` fleet dashboard.
4. Per-building SeaTalk scopes (design in TODO §2) — pilot SH-CaoHeJing once
   the user creates its SeaTalk group and provides the webhook.
