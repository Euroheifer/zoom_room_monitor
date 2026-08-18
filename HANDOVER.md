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

Live regions: **SG (140 rooms)**, **CNGR (24)** and **BR (71)** of ~760 in the
Zoom account. The **Zoom location directory is the single source of truth** for
region membership — room naming conventions are NOT trusted (test/VIP rooms
break them deliberately).

## Live inventory (zabbix.cit.insea.io, Zabbix 7.2.12)

| Object | ID / name |
|---|---|
| Collector script item (carrier, ALL regions) | `zoom.bridge.run` itemid **6528238** on `SG-Fleet-Summary`, 300s, 60s timeout |
| Non-carrier cycle-summary trappers | `zoom.bridge.run` — CNGR **6595415**, BR **6627736** (on their fleet hosts) |
| Watchdogs | `nodata(zoom.bridge.run,10m)` High trigger per fleet host |
| Host groups | `Rooms/Singapore` = **507**, `Rooms/CNGR` = **512**, `Rooms/BR` = **513** |
| Templates | room **40602**, devices **40603**, fleet **40604** |
| SeaTalk media type | `Seatalk-ZoomRooms` = **153**, shared by every scope; posts to the URL in `{ALERT.SENDTO}`, so the message format lives in ONE place (per-destination clones 151/152 deleted 2026-08-18) |
| Trigger actions (one per scope) | CNGR **280**, SG **281**, SG-GLX **282**, SG-RC **283**, SG-5SPD **284** — host group + severity ≥ Average (+ `building` tag for building scopes), problem + recovery |
| Alert identity | usergroup **88** `Zoom Rooms Alerts` (read on all `Rooms/*`); one user per scope: `svc-zoom-sg` **147**, `-cngr` **148**, `-sg-glx` **149**, `-sg-rc` **150**, `-sg-5spd` **151** — each holds exactly ONE media row whose `sendto` IS its group's webhook URL. One user per scope is mandatory: an action sends to ALL of a user's media rows of that type |
| Grafana dashboards | company Grafana: fleet SG (`zoom-sg-poc`), fleet CNGR (`zoom-cngr-poc`), room detail (`zoom-room-detail`, region-agnostic) — import via `deploy/upload-to-grafana/` symlinks (UI upload, overwrite) |

Secrets live in `bridge/.env` (gitignored): `ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID /
ZOOM_CLIENT_SECRET` (S2S OAuth), `ZBX_API_URL / ZBX_API_TOKEN` (super-admin),
`ZBX_SSL_VERIFY=false` (self-signed cert), `SEATALK_WEBHOOK_URL` (CNGR),
`SEATALK_WEBHOOK_URL_SG`, `SEATALK_WEBHOOK_URL_SG_GLX`, `..._SG_RC`,
`..._SG_5SPD`. SeaTalk webhook URLs are post-to-group credentials —
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
- **setup_seatalk.py [scope...]**: idempotent, no args = every scope whose
  webhook env var is set. A scope is a region or a building inside one
  (`SCOPES` table: host group + optional host tags). Building routing works
  because Zabbix copies host tags (`region`/`building`/`floor`, set by
  provisioning from the directory) onto events — condition type 26, tag name
  in `value2`. Region and building scopes overlap on purpose (regional IT
  keeps the full view); to stop that, add negative tag conditions to the
  region action.
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
| New SeaTalk destination (region or building) | group + System Account webhook (SeaTalk desktop, manual) → `.env` var → `SCOPES` entry in `setup_seatalk.py` → run. Building tag values come from the host `building` tag (see Zabbix host tags, e.g. GLX/RC/5SPD/LCS/Cogent/Pandan) |
| Health check | `zoom.bridge.run` lastvalue on the carrier fleet host — `{"regions":{"SG":{...,"failed":0},...}}`. `failed:N` in multiples of 4 ≈ N/4 rooms whose 4 trapper items reject pushes: either the room has no Zabbix host (run provision) or the host was **just** provisioned and Zabbix's configuration cache has not picked it up yet — that clears itself within a few cycles, so re-check before digging |
| Force a test alert | push `zoom.room.issues` = `TEST ALERT please ignore - ...` then `none` (the issue trigger flips on one value; offline needs two). **Pick a room whose issues are currently `none`** — a room already in problem state just changes the value, so no new event and no alert. Recovery messages only fire for problems that *started* after the action existed. |
| Alert format change | edit `MT_SCRIPT`/`MT_TEMPLATES` in `setup_seatalk.py` and re-run (converges media type 153 — one place, all scopes); preview by POSTing to a webhook directly |

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
6. **`failed:N` right after provisioning is a red herring** (2026-08-18): new
   hosts' items are rejected by `history.push` until the server's
   configuration syncer picks them up; the same pushes replayed by hand
   succeed, and the next cycles report `failed:0`. Wait two cycles before
   investigating.
7. **Device rotation is a GLOBAL budget** (`subset_size`, default 30), not
   per region: 30 sequential Zoom calls fit the 60s script timeout no matter
   how many regions exist. Adding regions lengthens the sweep instead
   (`ceil(total_rooms/subset)*interval` must stay under `DEVICE_STALE_WINDOW`,
   1h today, raise to 3h near ~700 rooms). A slice may sit entirely in one
   region for a cycle — the window walks the name-sorted fleet, so that is
   expected, not a bug. Check: `node bridge/test_collector_subset.js`.

## Where things are documented

- Confluence (space `~luhl@sea.com`, under "Zoom Room Monitoring — Build
  Guide"): SeaTalk Alert Setup Guide (pageId **270650478**, scopes model), Roadmap &
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
