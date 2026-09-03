# TODO / Roadmap

Pending work as of 2026-08-28. Context: SG (143 rooms), CNGR (24) and BR (71)
live on company Zabbix/Grafana with SeaTalk alerting; location directory is the
single source of truth for region membership, and `bridge/regions.py` is the one
place a region is defined.

## 1. Scale-out prerequisites (do before mass region onboarding)

- [x] **Global device-rotation budget** — DONE 2026-08-18: one shared budget
  (`subset_size`, default 30) across all regions, so Zoom calls per cycle stay
  flat as regions are added. Verified live with 3 regions (235 rooms, ~40min
  sweep, under the 1h `DEVICE_STALE_WINDOW`). Check:
  `node bridge/test_collector_subset.js`.
- [x] **Single region manifest** — DONE 2026-08-28: `bridge/regions.py` is the
  one place a region is defined (fields derived from the key; only SG's legacy
  host group and CNGR's legacy webhook var + kept city prefixes are overrides).
  `provision.py <REGION>`, `install_collector.py` and `setup_seatalk.py` all
  read it; the name-prefix fallback in `select_rooms` is gone, so an unknown
  region or an empty directory subtree fails loudly. `./run_onboard.sh <REGION>`
  chains provisioning + collector reinstall; SeaTalk and dashboards stay manual.
  Check: `python3 bridge/regions.py`.
- [x] **Templated fleet dashboard** — DONE 2026-08-28:
  `deploy/grafana-fleet.import.json` (uid `zoom-fleet`), `$region`/`$building`/
  `$floor`. Always-visible section reads the per-region fleet-summary items
  (cheap at any scope) plus a fleet-wide issues table that includes the
  collector watchdogs; per-region detail lives in a collapsed row repeated by
  `$region`, so no room-level query runs until you expand one. Host group
  `Rooms/Singapore` was renamed `Rooms/SG` (groupid 507 kept) so `$region`
  serves as both group and host-name prefix.
  - Split 2026-09-03 into `zoom-fleet` (HQ overview, no variables) +
    `zoom-region` (one region at a time), because Grafana cannot hide panels
    based on a variable value — an overview that stayed visible duplicated the
    selected region's own panels. Two dashboards serve all 12+ regions.
  - [ ] Delete `zoom-sg-poc` / `zoom-cngr-poc` once the two new dashboards have
    been used for a few days; update the Confluence links then.
  - [ ] If per-region access ever has to be *enforced* (not just a landing
    view), it needs a dashboard per region with the region hard-coded plus
    per-folder view permissions — someone with folder-admin rights, and back to
    N copies. Deliberately not done.

## 2. Per-building SeaTalk groups — DONE for SG (2026-08-18)

Shipped: one shared media type (**153** `Seatalk-ZoomRooms`, webhook from
`{ALERT.SENDTO}`) + one user and one action per scope, driven by the `SCOPES`
table in `setup_seatalk.py`. SG buildings live: **GLX 282**, **RC 283**,
**5SPD 284**; region scopes SG **281** / CNGR **280** migrated onto the shared
media type; old clones 151/152 and user 146 deleted. Region and building groups
overlap by design (regional IT keeps the full view).

- [x] **BR coverage gap — closed 2026-08-28 without a new SeaTalk group.**
  The `BR-B32` scope now matches `building` in (B32, HYP, FBSSP9, SFB) plus
  `role=summary`, so BR's small sites and the BR collector watchdog land in the
  existing B32 group. Tag conditions are all type 26 and therefore OR'd by
  evaltype 0, so one action covers all five cases; FLP keeps its own group and
  stays out. A dedicated BR region scope + group is no longer needed — if one is
  ever wanted, set `SEATALK_WEBHOOK_URL_BR` and run `setup_seatalk.py BR`.
- [ ] CNGR buildings when wanted — add `BUILDING_SCOPES` rows with
  `{"building": "SH-CaoHeJing"}` etc. (tag values: see CNGR host tags), one
  SeaTalk group + webhook each, re-run the script. No code change needed.
- [ ] If the SG region group gets noisy from the duplication, add negative tag
  conditions (`building <> GLX/RC/5SPD`) to action 281.
- [ ] Optional: raise GLX's severity floor to High only (~20 alerts/day today,
  half of them Medium) — `MIN_SEVERITY` is currently global, so this needs a
  per-scope override.

## 3. Watch items / small stuff

- [ ] SG's newly monitored unconventional rooms (`ECS test 2026`, `Home`,
  `L16 Cafe test`) and the flapping Corp IT Test Rooms: if they spam the SG
  SeaTalk group, mark them **Under Construction** in Zoom admin — alert
  suppression for that status is built into the collector.
- [ ] Optional alert refinements when asked: escalation reminder ("still down
  after 2h") as a second action step; per-region quiet hours via the service
  user's media "When active" window.
- [ ] Zabbix server health (2026-08-11 incident): housekeeper pinned 100%,
  ~40k LLD backlog, ~9s/call API latency → gateway 521s. Our dashboards were
  hardened (trends, small windows), but the server issue belongs to the CIT
  Zabbix admins — chase the ticket if slowness returns.
- Known exception, leave in place: SG host **41153** `Home` (visible
  `SG-Forrest Li Home-Home-Home`) is a VIP home room. It left the SG directory
  subtree on 2026-08-14 and receives no data, so provisioning ignores it and its
  two problems (High "Room is offline" + Medium) stay open permanently. **Do not
  delete it.** Cost of keeping it: a permanent red tile in the SG room grid, two
  permanent rows in Active issues, and a "Forrest Li Home" entry in the Building
  filter. If that noise ever matters, disable the host in Zabbix (keeps history,
  closes the problems, removes it from dashboards) rather than deleting it.
- [ ] Local cleanup: `homebrew.mxcl.grafana` LaunchAgent (old local POC) still
  autostarts on the Mac; `brew services stop grafana` when no longer needed.
- Known artifact: CNGR data gap 2026-08-14 ~12:00–15:30 (LOCATION_ROOT
  regression, fixed same day).

## Remaining regions (room counts by directory node, 2026-08-14)

CNDC 143, ID 77 + ID-BKE 20, CNCB 67, VN 61, PH 50 + PH-BLI 10, TH 34,
MY 29, TW 20, MX 7, KR 5, IN 3 — plus live SG 143, BR 71, CNGR 24 ≈ 760 total.

## Onboarding recipe (current, per region)

See docs/SETUP.md "Setting up another country". Short form: verify the
directory node → add `"XX": {}` to `bridge/regions.py` → `./run_onboard.sh XX`
→ SeaTalk group/webhook in `.env` + `setup_seatalk.py XX`. No dashboard step —
the fleet dashboard picks the region up from its host group.
