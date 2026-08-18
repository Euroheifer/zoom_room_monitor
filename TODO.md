# TODO / Roadmap

Pending work as of 2026-08-14. Context: SG (139 rooms) + CNGR (24) live on
company Zabbix/Grafana with SeaTalk alerting; location directory is the single
source of truth for region membership.

## 1. Scale-out prerequisites (do before mass region onboarding)

- [x] **Global device-rotation budget** — DONE 2026-08-18: one shared budget
  (`subset_size`, default 30) across all regions, so Zoom calls per cycle stay
  flat as regions are added. Verified live with 3 regions (235 rooms, ~40min
  sweep, under the 1h `DEVICE_STALE_WINDOW`). Check:
  `node bridge/test_collector_subset.js`.
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

## 2. Per-building SeaTalk groups — DONE for SG (2026-08-18)

Shipped: one shared media type (**153** `Seatalk-ZoomRooms`, webhook from
`{ALERT.SENDTO}`) + one user and one action per scope, driven by the `SCOPES`
table in `setup_seatalk.py`. SG buildings live: **GLX 282**, **RC 283**,
**5SPD 284**; region scopes SG **281** / CNGR **280** migrated onto the shared
media type; old clones 151/152 and user 146 deleted. Region and building groups
overlap by design (regional IT keeps the full view).

- [ ] CNGR buildings when wanted — add `SCOPES` rows with
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
- [ ] Local cleanup: `homebrew.mxcl.grafana` LaunchAgent (old local POC) still
  autostarts on the Mac; `brew services stop grafana` when no longer needed.
- Known artifact: CNGR data gap 2026-08-14 ~12:00–15:30 (LOCATION_ROOT
  regression, fixed same day).

## Remaining regions (room counts by directory node, 2026-08-14)

CNDC 143, ID 77 + ID-BKE 20, CNCB 67, VN 61, PH 50 + PH-BLI 10, TH 34,
MY 29, TW 20, MX 7, KR 5, IN 3 — plus live SG 140, BR 71, CNGR 24 ≈ 760 total.

## Onboarding recipe (current, per region)

See docs/SETUP.md "Setting up another country". Short form: verify directory
node → `LOCATION_ROOT=XX REGION_PREFIX=XX HOST_GROUP=Rooms/XX
./run_provision.sh` → add REGIONS entry in `install_collector.py` + reinstall
→ SeaTalk group/webhook + `setup_seatalk.py` entry + run → dashboard copy
(until the templated dashboard above lands).
