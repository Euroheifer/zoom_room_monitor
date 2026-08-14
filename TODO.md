# TODO / Roadmap

Pending work as of 2026-08-14. Context: SG (139 rooms) + CNGR (24) live on
company Zabbix/Grafana with SeaTalk alerting; location directory is the single
source of truth for region membership.

## 1. Scale-out prerequisites (do before mass region onboarding)

- [ ] **Global device-rotation budget** — the device-detail subset is 15 rooms
  *per region*, fetched sequentially inside one script-item run (60s timeout).
  Fine at 2 regions (30 calls); blows the timeout at ~16 regions (240 calls).
  Switch `collector.js` to one global rotation budget (~30 rooms/cycle across
  all regions); peripheral freshness stretches with fleet size — widen
  `DEVICE_STALE_WINDOW` (provision.py) to match `ceil(rooms/budget)*interval`.
- [ ] **Single region manifest** — region list currently lives in 3 places:
  `install_collector.py` REGIONS, `setup_seatalk.py` REGIONS, and env vars
  typed for provisioning. One `regions.py` table consumed by all three + an
  `onboard.py <REGION>` that provisions, reinstalls the collector, and wires
  alerts in one run.
- [ ] **Templated fleet dashboard** — replace per-region dashboard copies with
  one dashboard using a `$region` host-group variable (room-detail already
  works this way). Removes the copy/swap/import step per region and the
  N-times maintenance of every dashboard fix. Needs the building/floor
  template-var regexes generalized (or switched to host tags).

## 2. Per-building SeaTalk groups (design agreed, not built)

Hosts already carry `region`/`building`/`floor` tags from the location
directory; trigger actions can filter on them — no provisioning changes.

- [ ] Refactor `setup_seatalk.py` to a **scopes** table:
  `{name, tags: {region, building?}, webhook_env}`; one action per scope.
- [ ] Replace per-destination media-type clones with **one shared media type**
  reading the webhook URL from `{ALERT.SENDTO}` (destination = one media row
  on `svc-zoomrooms-seatalk`). Migrate media types 151/152 so message
  formatting lives in one place.
- [ ] Pilot with one building (e.g. CNGR SH-CaoHeJing): human creates the
  SeaTalk group + System Account webhook, wire it, watch volume before
  rolling out. Skip dedicated groups for tiny sites (3-room sites alert
  ~monthly — share a city group instead).

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
- [ ] Local cleanup: `homebrew.mxcl.grafana` LaunchAgent (old local POC) still
  autostarts on the Mac; `brew services stop grafana` when no longer needed.
- Known artifact: CNGR data gap 2026-08-14 ~12:00–15:30 (LOCATION_ROOT
  regression, fixed same day).

## Remaining regions (room counts by directory node, 2026-08-14)

CNDC 143, ID 77 + ID-BKE 20, BR 71, CNCB 67, VN 61, PH 50 + PH-BLI 10,
TH 34, MY 29, TW 20, MX 7, KR 5, IN 3 — plus live SG 139, CNGR 24 ≈ 760 total.

## Onboarding recipe (current, per region)

See docs/SETUP.md "Setting up another country". Short form: verify directory
node → `LOCATION_ROOT=XX REGION_PREFIX=XX HOST_GROUP=Rooms/XX
./run_provision.sh` → add REGIONS entry in `install_collector.py` + reinstall
→ SeaTalk group/webhook + `setup_seatalk.py` entry + run → dashboard copy
(until the templated dashboard above lands).
