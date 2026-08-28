# Single Region Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define each region in exactly one place (`bridge/regions.py`) and make onboarding a region two steps — one table row, one command — removing the hand-typed env vars that once silently zeroed CNGR for 3.5h.

**Architecture:** A dict keyed by region name; every field is derived from the key unless the row overrides it. `provision.py` takes the region as argv and resolves it through the manifest instead of reading four env vars; `install_collector.py` imports the table; `setup_seatalk.py` merges generated region scopes with its hand-written building scopes. `run_onboard.sh` chains the two existing shell wrappers and prints the manual SeaTalk/dashboard steps.

**Tech Stack:** Python 3, bash. No new dependencies, no new Zabbix objects.

**Spec:** `TODO.md` §1 "Single region manifest"; `HANDOVER.md` "Immediate next steps" item 2. Design agreed in session 2026-08-28.

## Global Constraints

- **No live Zabbix object may change.** The refactor is a no-op for SG/CNGR/BR: same host groups, same fleet hosts, same host names and tags, same `regions` JSON parameter on itemid 6528238.
- Mutating scripts are run by the user, never from the agent session. Read-only API calls are fine.
- `test_provision.py` imports `provision` at module level — argv must NOT be parsed at import time (pytest's argv would poison it). Resolve the region inside `main()`.
- `DEVICE_STALE_WINDOW` stays a global env knob (fleet-wide, not per-region).
- Building scopes in `setup_seatalk.py` stay hand-written — a building is not derivable from a region name and each needs a manually created SeaTalk group.

## Verified facts (checked live 2026-08-28, do not re-derive)

- BR campus directory nodes are `BRA-FLP`, `BRA-SFB`, `BRA-HYP`, `BRA-B32`, `BRA-FBSSP9`; live BR host `building` tags are `FLP`/`SFB`/`HYP`/`B32`/`FBSSP9`. **BR ran with `strip_campus_prefix` ON** (the default). Only CNGR sets it False.
- `collector.js` reads `[{name, location_root?, fleet_host?}]` and defaults `location_root` to `name`, `fleet_host` to `name + '-Fleet-Summary'` — identical to the manifest's defaults, so emitting `[{"name": k} for k in REGIONS]` reproduces today's parameter exactly.
- `run_provision.sh` already ends in `exec .venv/bin/python provision.py "$@"`, so it needs no change to accept a region argument.

---

### Task 1: The manifest

**Files:** Create `bridge/regions.py`

- [ ] **Step 1: Write the table, the accessor, and its self-check**

```python
"""Region manifest — the one place a region is defined.

Everything is derived from the region name; a row only lists what differs.
Adding a region is one line here, then ./run_onboard.sh <REGION>.
"""

REGIONS = {
    "SG":   {"host_group": "Rooms/Singapore"},          # pre-dates the Rooms/<KEY> convention
    "CNGR": {"webhook_env": "SEATALK_WEBHOOK_URL",      # legacy unsuffixed var name
             "strip_campus_prefix": False},             # campus names carry the city (BJ-JinHui)
    "BR":   {},
}


def region(name):
    """Full config for one region. Unknown name exits loudly rather than
    falling back to a default region — that fallback cost CNGR 3.5h once."""
    if name not in REGIONS:
        raise SystemExit(
            f"unknown region {name!r} — add it to regions.py; known: {' '.join(REGIONS)}")
    r = REGIONS[name]
    return {
        "region_prefix": name,
        "location_root": r.get("location_root", name),
        "host_group": r.get("host_group", f"Rooms/{name}"),
        "fleet_host": r.get("fleet_host", f"{name}-Fleet-Summary"),
        "webhook_env": r.get("webhook_env", f"SEATALK_WEBHOOK_URL_{name}"),
        "strip_campus_prefix": r.get("strip_campus_prefix", True),
    }


if __name__ == "__main__":  # must match what the 3 live regions run with today
    assert region("SG")["host_group"] == "Rooms/Singapore"
    assert region("SG")["strip_campus_prefix"] is True
    assert region("CNGR") == {
        "region_prefix": "CNGR", "location_root": "CNGR", "host_group": "Rooms/CNGR",
        "fleet_host": "CNGR-Fleet-Summary", "webhook_env": "SEATALK_WEBHOOK_URL",
        "strip_campus_prefix": False}
    assert region("BR") == {
        "region_prefix": "BR", "location_root": "BR", "host_group": "Rooms/BR",
        "fleet_host": "BR-Fleet-Summary", "webhook_env": "SEATALK_WEBHOOK_URL_BR",
        "strip_campus_prefix": True}
    try:
        region("XX")
    except SystemExit as e:
        assert "known: SG CNGR BR" in str(e)
    else:
        raise AssertionError("unknown region must exit")
    print("ok")
```

- [ ] **Step 2:** `python3 bridge/regions.py` prints `ok`.

---

### Task 2: provision.py reads the manifest

**Files:** Modify `bridge/provision.py`

- [ ] **Step 1: Replace the env reads**

Delete the `REGION_PREFIX` / `LOCATION_ROOT` / `HOST_GROUP` / `STRIP_CAMPUS_PREFIX` `os.environ.get` lines (24-32) and their comments. Keep the names as module constants — every function below uses them — but initialise them to `None` and assign in `main()`. The same applies to `FLEET_HOST_TECH` / `FLEET_HOST_NAME` (lines 41-42): they are f-strings over `REGION_PREFIX` today and would raise at import if it were `None`, so they become `None` here too. `DEVICE_STALE_WINDOW` stays an env read.

- [ ] **Step 2: Resolve the region in main()**

```python
def main():
    # ponytail: module constants set once at startup, same as when they came
    # from the environment — just argv-driven now. Threading six values through
    # location_tags/canonical_room_name/select_rooms/ensure_fleet_host would be
    # a much larger diff for the same result.
    global REGION_PREFIX, LOCATION_ROOT, HOST_GROUP, STRIP_CAMPUS_PREFIX
    global FLEET_HOST_TECH, FLEET_HOST_NAME
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: provision.py <REGION>   ({' '.join(REGIONS)})")
    r = region(sys.argv[1])
    REGION_PREFIX = r["region_prefix"]
    LOCATION_ROOT = r["location_root"]
    HOST_GROUP = r["host_group"]
    STRIP_CAMPUS_PREFIX = r["strip_campus_prefix"]
    FLEET_HOST_TECH = r["fleet_host"]
    FLEET_HOST_NAME = f"{REGION_PREFIX} Fleet Summary"   # unchanged from today
    ...
```

- [ ] **Step 3: Delete the name-prefix fallback**

`select_rooms` (line ~294) currently falls back to `name.startswith(REGION_PREFIX)` when `LOCATION_ROOT` is empty. `LOCATION_ROOT` can no longer be empty, and the directory is the single source of truth. Reduce to the subtree branch only:

```python
    sub = location_subtree(locs, LOCATION_ROOT)
    return [x for x in rooms if x.get("location_id") in sub]
```

Fail loudly if the subtree is empty — a region that selects zero rooms is the CNGR regression, not a valid state.

- [ ] **Step 4:** `pytest test_provision.py` still passes (it imports `ensure_*` helpers only, which are untouched).

---

### Task 3: install_collector.py imports the table

**Files:** Modify `bridge/install_collector.py`

- [ ] **Step 1:** Delete the local `REGIONS` list; `from regions import REGIONS, region`. Build the script parameter as `[{"name": k} for k in REGIONS]` and rewrite the local `fleet_host()` helper to `region(name)["fleet_host"]`, updating the three loops that call it.
- [ ] **Step 2:** Verify the generated `regions` parameter still serialises to `[{"name": "SG"}, {"name": "CNGR"}, {"name": "BR"}]` — print it and compare against the live item's parameter before the user re-runs the installer.

---

### Task 4: setup_seatalk.py generates its region scopes

**Files:** Modify `bridge/setup_seatalk.py`

- [ ] **Step 1:** Rename the existing `SCOPES` to `BUILDING_SCOPES`, keeping only the six building rows (SG-GLX, SG-RC, SG-5SPD, BR-FLP, BR-B32 and any added since). Then:

```python
from regions import REGIONS, region

SCOPES = {name: {"hostgroup": region(name)["host_group"], "tags": {},
                 "webhook_env": region(name)["webhook_env"]}
          for name in REGIONS}
SCOPES.update(BUILDING_SCOPES)
```

- [ ] **Step 2:** `python3 -c "import setup_seatalk; print(setup_seatalk.SCOPES)"` produces the same eight scopes with the same host groups and webhook env vars as today (BR's row already exists; it stays skipped until its webhook is set).

---

### Task 5: run_onboard.sh

**Files:** Create `bridge/run_onboard.sh` (chmod +x)

- [ ] **Step 1:**

```bash
#!/usr/bin/env bash
# Onboard one region: provision its hosts, then teach the collector about it.
# Alerts and dashboards stay manual — they need a human-created SeaTalk group.
set -euo pipefail
cd "$(dirname "$0")"
[ $# -eq 1 ] || { echo "usage: $0 <REGION>"; exit 1; }
./run_provision.sh "$1"
./run_install_collector.sh
cat <<EOF

Next, by hand:
  1. Create the SeaTalk group + System Account webhook
  2. Add its URL to bridge/.env  (see regions.py for the var name)
  3. python3 setup_seatalk.py $1
  4. Copy the fleet dashboard (until the \$region template lands)
EOF
```

- [ ] **Step 2:** `./run_onboard.sh XX` fails at provisioning with the unknown-region message and never reaches the collector step.

---

### Task 6: Docs

**Files:** Modify `HANDOVER.md`, `TODO.md`, `docs/SETUP.md`

- [ ] **Step 1:** `HANDOVER.md` — runbook rows become `./run_provision.sh SG` (no env prefix) and a "New region" row pointing at `regions.py` + `run_onboard.sh`. Add gotcha #2's resolution: region config now lives only in `regions.py`, and provisioning fails loudly on an unknown region.
- [ ] **Step 2:** `TODO.md` — tick §1 "Single region manifest" with the date; update the onboarding recipe at the bottom to the two-step form.
- [ ] **Step 3:** `docs/SETUP.md` — "Setting up another country" collapses to: add the row, run `./run_onboard.sh XX`, then the SeaTalk/dashboard steps. Remove the `LOCATION_ROOT=`/`REGION_PREFIX=`/`HOST_GROUP=` env examples from the `.env` sample block.

---

### Task 7: Live verification (user-run)

- [ ] **Step 1:** `./run_onboard.sh SG`, then CNGR, then BR. Each must report its expected room count (140 / 24 / 71) with nothing created — the scripts are idempotent, so a clean run is a no-op.
- [ ] **Step 2:** Confirm in Zabbix that host counts per group are unchanged (507 = 140, 512 = 24, 513 = 71) and that no host was renamed.
- [ ] **Step 3:** Check `zoom.bridge.run` lastvalue on `SG-Fleet-Summary` for two cycles: all three regions present, `failed:0`. (`failed:N` immediately after a provision run is the known configuration-cache red herring — wait two cycles.)
- [ ] **Step 4:** Commit.
