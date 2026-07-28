# Room History Drilldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Click an active issue (or room tile) on the main Grafana dashboard and land on a per-room dashboard showing 30 days of online/offline history, outage events, and device status.

**Architecture:** A second provisioned Grafana dashboard (`zoom-room-detail`) with a `$room` template variable, reached via data links from the main dashboard. The main dashboard's triggers panel is replaced by a table panel (the triggers panel cannot carry per-row data links). Zabbix item history retention is bumped 31d → 90d so a 30-day view always has margin.

**Tech Stack:** Grafana OSS (schemaVersion 42, pluginVersion 13.0.2), alexanderzobnin-zabbix-datasource (uid `zabbix-poc`, plugin 6.4.0), Zabbix 7.0 JSON-RPC API, Python 3 (bridge venv at `bridge/.venv`), bash + curl deploy scripts.

## Global Constraints

- Datasource reference in every panel/target: `{"type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc"}` — the uid is pinned by `deploy/configure-grafana.sh`, never auto-generated.
- Grafana auth in scripts: `GF_ADMIN_USER`/`GF_ADMIN_PASS` env vars (defaults `admin`/`admin`), loud failure on bad credentials. The live instance has a user-set password — every import command below must be run as `GF_ADMIN_PASS=<real password> ./import-dashboard.sh`.
- Zabbix API: defaults `Admin`/`zabbix` at `http://localhost:8080/api_jsonrpc.php` (see `bridge/zabbix_client.py`); override via `ZBX_USER`/`ZBX_PASS` if changed.
- Host group in all queries: `Rooms/Singapore`. Item visible names: `Room online (1/0)`, `Room status (raw)`, `Computer online (1/0)`, `Controller online (1/0)`, `Computer app version`, `Controller version`.
- Tests run with the plain runner (no pytest installed): `.venv/bin/python -c "import test_x as t; [getattr(t,n)() for n in dir(t) if n.startswith('test_')]"` from `bridge/`.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Commit the pending poller-baseline fix

The working tree already contains an unrelated, verified fix (devices template linked to all hosts; timestamped poll logs). Land it first so drilldown commits stay clean.

**Files:**
- Modify: none (commit existing changes to `bridge/poll.py`, `bridge/provision.py`)

**Interfaces:**
- Produces: clean working tree; `provision.py` whose `ensure_hosts(api, rooms, hg_id, room_tpl, dev_tpl)` links both templates to every host (Task 2 edits this file further).

- [ ] **Step 1: Confirm only the two expected files are dirty**

Run: `git -C /Users/SG3966/Claude/zoom_room_monitor status --short -- bridge/`
Expected: ` M bridge/poll.py` and ` M bridge/provision.py` only.

- [ ] **Step 2: Run the mapper tests**

Run (from `bridge/`): `.venv/bin/python -c "import test_mapper as t; fns=[getattr(t,n) for n in dir(t) if n.startswith('test_')]; [f() for f in fns]; print(len(fns),'passed')"`
Expected: `9 passed`

- [ ] **Step 3: Commit**

```bash
git add bridge/poll.py bridge/provision.py
git commit -m "Fix trapper rejects: devices template on all hosts, timestamped poll logs

The poller picks its device subset dynamically (offline rooms first) but
provisioning linked the devices template to a subset frozen at provision
time, so drifted rooms' device items were rejected (failed: 4 for weeks).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Bump item history retention to 90d (with update of existing items)

**Files:**
- Modify: `bridge/provision.py` (function `ensure_items`, currently lines 59-70)
- Test: `bridge/test_provision.py` (new)

**Interfaces:**
- Consumes: `ZabbixAPI.call(method, params)` from `bridge/zabbix_client.py`.
- Produces: `ensure_items(api, template_id, specs, history="90d")` — creates missing template items with the given retention and updates retention on existing ones. Callers (`build_room_template`, `build_device_template`, `build_fleet_template`) need no change.

- [ ] **Step 1: Write the failing test**

Create `bridge/test_provision.py`:

```python
"""Unit tests for ensure_items against a stub Zabbix API."""
from provision import ensure_items


class StubAPI:
    def __init__(self, existing_items):
        self.existing = existing_items
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "item.get":
            return self.existing
        return {}


SPECS = [("zoom.room.online", "Room online (1/0)", 3)]


def test_creates_missing_item_with_history():
    api = StubAPI([])
    ensure_items(api, "100", SPECS)
    creates = [p for m, p in api.calls if m == "item.create"]
    assert len(creates) == 1
    assert creates[0]["history"] == "90d"
    assert creates[0]["key_"] == "zoom.room.online"


def test_updates_retention_on_existing_item():
    api = StubAPI([{"itemid": "42", "key_": "zoom.room.online", "history": "31d"}])
    ensure_items(api, "100", SPECS)
    assert ("item.update", {"itemid": "42", "history": "90d"}) in api.calls
    assert not any(m == "item.create" for m, _ in api.calls)


def test_leaves_correct_item_alone():
    api = StubAPI([{"itemid": "42", "key_": "zoom.room.online", "history": "90d"}])
    ensure_items(api, "100", SPECS)
    assert [m for m, _ in api.calls] == ["item.get"]
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `bridge/`): `.venv/bin/python -c "import test_provision as t; fns=[getattr(t,n) for n in dir(t) if n.startswith('test_')]; [f() for f in fns]; print(len(fns),'passed')"`
Expected: FAIL — `KeyError: 'history'` or assertion error (current `ensure_items` neither sets `history` nor updates existing items).

- [ ] **Step 3: Replace `ensure_items` in `bridge/provision.py`**

Replace the whole existing function:

```python
def ensure_items(api, template_id, specs, history="90d"):
    """specs: list of (key, name, value_type). Creates missing items and keeps
    history retention in sync on existing ones (a 30-day dashboard view needs
    more margin than Zabbix's 31d default)."""
    existing = {i["key_"]: i for i in api.call("item.get",
                {"templateids": template_id, "output": ["itemid", "key_", "history"]})}
    for key, name, vtype in specs:
        cur = existing.get(key)
        if cur is None:
            api.call("item.create", {
                "name": name, "key_": key, "hostid": template_id,
                "type": TYPE_TRAPPER, "value_type": vtype, "history": history,
            })
        elif cur["history"] != history:
            api.call("item.update", {"itemid": cur["itemid"], "history": history})
```

- [ ] **Step 4: Run tests to verify they pass**

Run both test modules from `bridge/`:
`.venv/bin/python -c "import test_provision as t; fns=[getattr(t,n) for n in dir(t) if n.startswith('test_')]; [f() for f in fns]; print(len(fns),'passed')"`
`.venv/bin/python -c "import test_mapper as t; fns=[getattr(t,n) for n in dir(t) if n.startswith('test_')]; [f() for f in fns]; print(len(fns),'passed')"`
Expected: `3 passed` and `9 passed`.

- [ ] **Step 5: Apply to the live stack and verify**

Run (from `bridge/`): `./run_provision.sh`
Expected: `>> Zabbix login OK` … `Done.` with no traceback.

Then verify retention:

```bash
.venv/bin/python - <<'EOF'
from zabbix_client import ZabbixAPI
api = ZabbixAPI(); api.login()
items = api.call("item.get", {"filter": {"key_": ["zoom.room.online", "zoom.fleet.total",
                 "zoom.device.computer.status"]}, "templated": True,
                 "output": ["key_", "history"]})
print(items)
assert all(i["history"] == "90d" for i in items), "retention not applied"
print("retention OK")
EOF
```

Expected: `retention OK`.

- [ ] **Step 6: Commit**

```bash
git add bridge/provision.py bridge/test_provision.py
git commit -m "Bump Zabbix item history to 90d, sync retention on reprovision

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Teach import-dashboard.sh to import multiple dashboards

**Files:**
- Modify: `deploy/import-dashboard.sh`

**Interfaces:**
- Produces: script imports every file in its `DASHBOARDS` list, failing loudly per file. Ships with only the existing dashboard in the list; Task 4 appends `grafana-room-detail.json`.

- [ ] **Step 1: Rewrite the script**

Replace the body of `deploy/import-dashboard.sh` with:

```bash
#!/usr/bin/env bash
# Import (or update) the POC Grafana dashboards.
set -euo pipefail
cd "$(dirname "$0")"
GF_PORT="${GF_PORT:-3001}"
GF_ADMIN_USER="${GF_ADMIN_USER:-admin}"
GF_ADMIN_PASS="${GF_ADMIN_PASS:-admin}"   # Grafana forces a change on first login — pass the real one via env
GF="http://${GF_ADMIN_USER}:${GF_ADMIN_PASS}@localhost:${GF_PORT}"

DASHBOARDS=(grafana-dashboard.json)

for f in "${DASHBOARDS[@]}"; do
  curl -s -X POST "$GF/api/dashboards/db" \
    -H "Content-Type: application/json" \
    -d @"$f" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d.get('status') != 'success':
    sys.exit(f'import FAILED ($f): {d}')
print('import:', d['status'], '->', d['url'])"
done
```

- [ ] **Step 2: Verify against the live Grafana**

Run: `GF_ADMIN_PASS=<real password> ./import-dashboard.sh` (from `deploy/`; ask the user for the password if not already in the environment).
Expected: `import: success -> /d/zoom-sg-poc/...`

- [ ] **Step 3: Commit**

```bash
git add deploy/import-dashboard.sh
git commit -m "import-dashboard.sh: loop over a dashboard list

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Create the room-detail dashboard

**Files:**
- Create: `deploy/grafana-room-detail.json`
- Modify: `deploy/import-dashboard.sh` (add the new file to `DASHBOARDS`)

**Interfaces:**
- Consumes: Zabbix items listed in Global Constraints; datasource uid `zabbix-poc`.
- Produces: dashboard uid `zoom-room-detail` with template variable `room`, reachable at `/d/zoom-room-detail?var-room=<host visible name>&from=now-30d&to=now`. Task 5's data links target exactly this URL shape.

- [ ] **Step 1: Write `deploy/grafana-room-detail.json`**

Full file (wrapper + dashboard). Every target uses the same Zabbix datasource block; panels are laid out top-to-bottom:

```json
{
  "overwrite": true,
  "folderId": 0,
  "dashboard": {
    "editable": true,
    "id": null,
    "uid": "zoom-room-detail",
    "title": "Zoom Room — Detail",
    "tags": ["zoom", "poc"],
    "schemaVersion": 42,
    "refresh": "1m",
    "timezone": "browser",
    "time": { "from": "now-30d", "to": "now" },
    "templating": {
      "list": [
        {
          "name": "room",
          "label": "Room",
          "type": "query",
          "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
          "query": {
            "queryType": 1,
            "group": { "filter": "Rooms/Singapore" },
            "host": { "filter": "/.*/" },
            "application": { "filter": "" },
            "item": { "filter": "" }
          },
          "refresh": 1,
          "sort": 1,
          "includeAll": false,
          "multi": false,
          "current": {}
        }
      ]
    },
    "panels": [
      {
        "type": "state-timeline",
        "title": "Online / offline",
        "id": 1,
        "gridPos": { "h": 6, "w": 18, "x": 0, "y": 0 },
        "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
        "fieldConfig": {
          "defaults": {
            "custom": { "fillOpacity": 70, "lineWidth": 0, "spanNulls": false },
            "mappings": [
              {
                "type": "value",
                "options": {
                  "0": { "color": "red", "text": "OFFLINE" },
                  "1": { "color": "green", "text": "ONLINE" }
                }
              }
            ],
            "displayName": "room"
          }
        },
        "options": { "showValue": "never", "legend": { "showLegend": false }, "tooltip": { "mode": "single" } },
        "targets": [
          {
            "refId": "A",
            "queryType": "0",
            "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
            "functions": [],
            "options": {},
            "application": { "filter": "" },
            "group": { "filter": "Rooms/Singapore" },
            "host": { "filter": "$room" },
            "item": { "filter": "Room online (1/0)" }
          }
        ]
      },
      {
        "type": "stat",
        "title": "Uptime (selected range)",
        "id": 2,
        "gridPos": { "h": 6, "w": 6, "x": 18, "y": 0 },
        "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
        "fieldConfig": {
          "defaults": {
            "unit": "percentunit",
            "decimals": 1,
            "thresholds": {
              "mode": "absolute",
              "steps": [
                { "color": "red", "value": 0 },
                { "color": "yellow", "value": 0.95 },
                { "color": "green", "value": 0.99 }
              ]
            }
          }
        },
        "options": {
          "colorMode": "value",
          "graphMode": "none",
          "reduceOptions": { "calcs": ["mean"], "fields": "", "values": false },
          "textMode": "value"
        },
        "targets": [
          {
            "refId": "A",
            "queryType": "0",
            "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
            "functions": [],
            "options": {},
            "application": { "filter": "" },
            "group": { "filter": "Rooms/Singapore" },
            "host": { "filter": "$room" },
            "item": { "filter": "Room online (1/0)" }
          }
        ]
      },
      {
        "type": "alexanderzobnin-zabbix-triggers-panel",
        "title": "Outages & issues (selected range)",
        "id": 3,
        "gridPos": { "h": 9, "w": 24, "x": 0, "y": 6 },
        "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
        "options": {
          "layout": "table",
          "hostField": "hostname",
          "severityField": true,
          "statusField": true,
          "ackField": false,
          "ageField": true,
          "descriptionField": true,
          "showTags": false,
          "problemTimeline": true,
          "sortProblems": "lastchange",
          "sortProblemsField": "lastchange",
          "fontSize": "100%",
          "pageSize": 15,
          "okEventColor": "rgb(56, 189, 113)",
          "highlightBackground": false,
          "highlightNewEvents": false,
          "highlightNewerThan": "1h",
          "customLastChangeFormat": false,
          "lastChangeFormat": "",
          "customTagColumns": "",
          "allowDangerousHTML": false,
          "descriptionAtNewLine": false,
          "hostGroups": false,
          "hostProxy": false,
          "hostTechNameField": false,
          "markAckEvents": false,
          "opdataField": false,
          "showDatasourceName": false,
          "statusIcon": false,
          "ackEventColor": false,
          "triggerSeverity": [
            { "priority": 0, "severity": "Not classified", "color": "rgb(108, 108, 108)", "show": true },
            { "priority": 1, "severity": "Information", "color": "rgb(120, 158, 183)", "show": true },
            { "priority": 2, "severity": "Warning", "color": "rgb(175, 180, 36)", "show": true },
            { "priority": 3, "severity": "Average", "color": "rgb(255, 137, 30)", "show": true },
            { "priority": 4, "severity": "High", "color": "rgb(255, 101, 72)", "show": true },
            { "priority": 5, "severity": "Disaster", "color": "rgb(215, 0, 0)", "show": true }
          ]
        },
        "targets": [
          {
            "refId": "A",
            "queryType": "5",
            "schema": 12,
            "showProblems": "history",
            "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
            "functions": [],
            "evaltype": "0",
            "application": { "filter": "" },
            "group": { "filter": "Rooms/Singapore" },
            "host": { "filter": "$room" },
            "item": { "filter": "" },
            "itemTag": { "filter": "" },
            "macro": { "filter": "" },
            "proxy": { "filter": "" },
            "tags": { "filter": "" },
            "trigger": { "filter": "" },
            "textFilter": "",
            "countTriggersBy": "",
            "options": {
              "acknowledged": 2,
              "count": false,
              "disableDataAlignment": false,
              "hostProxy": false,
              "hostsInMaintenance": false,
              "limit": 1001,
              "minSeverity": 0,
              "showDisabledItems": false,
              "skipEmptyValues": false,
              "sortProblems": "default",
              "useTimeRange": true,
              "useTrends": "default",
              "useZabbixValueMapping": false
            },
            "resultFormat": "time_series",
            "table": { "skipEmptyValues": false }
          }
        ]
      },
      {
        "type": "state-timeline",
        "title": "Devices — computer / controller",
        "description": "Device status is only collected while this room is in the poller's 5-room detail subset (offline rooms are picked first). Gaps mean the room was not in the subset, not that the devices were down.",
        "id": 4,
        "gridPos": { "h": 6, "w": 18, "x": 0, "y": 15 },
        "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
        "fieldConfig": {
          "defaults": {
            "custom": { "fillOpacity": 70, "lineWidth": 0, "spanNulls": false },
            "mappings": [
              {
                "type": "value",
                "options": {
                  "0": { "color": "red", "text": "OFFLINE" },
                  "1": { "color": "green", "text": "ONLINE" }
                }
              }
            ]
          }
        },
        "options": { "showValue": "never", "legend": { "showLegend": true }, "tooltip": { "mode": "single" } },
        "targets": [
          {
            "refId": "A",
            "queryType": "0",
            "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
            "functions": [],
            "options": {},
            "application": { "filter": "" },
            "group": { "filter": "Rooms/Singapore" },
            "host": { "filter": "$room" },
            "item": { "filter": "/(Computer|Controller) online/" }
          }
        ]
      },
      {
        "type": "stat",
        "title": "Now: status / versions",
        "id": 5,
        "gridPos": { "h": 6, "w": 6, "x": 18, "y": 15 },
        "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
        "fieldConfig": { "defaults": { "color": { "mode": "fixed", "fixedColor": "text" } } },
        "options": {
          "colorMode": "none",
          "graphMode": "none",
          "reduceOptions": { "calcs": ["lastNotNull"], "fields": "/.*/", "values": false },
          "textMode": "name_and_value"
        },
        "targets": [
          {
            "refId": "A",
            "queryType": "0",
            "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
            "functions": [],
            "options": {},
            "application": { "filter": "" },
            "group": { "filter": "Rooms/Singapore" },
            "host": { "filter": "$room" },
            "item": { "filter": "/(Room status \\(raw\\)|app version|Controller version)/" }
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Add the file to the import list**

In `deploy/import-dashboard.sh` change:

```bash
DASHBOARDS=(grafana-dashboard.json grafana-room-detail.json)
```

- [ ] **Step 3: Validate JSON and import**

```bash
python3 -m json.tool grafana-room-detail.json > /dev/null && echo JSON OK
GF_ADMIN_PASS=<real password> ./import-dashboard.sh
```

Expected: `JSON OK`, then two `import: success` lines, the second ending in `/d/zoom-room-detail/...`.

- [ ] **Step 4: Verify the dashboard works**

Scripted checks:

```bash
curl -s "http://admin:${GF_ADMIN_PASS}@localhost:3001/api/dashboards/uid/zoom-room-detail" \
  | python3 -c "import sys,json; d=json.load(sys.stdin)['dashboard']; \
print('panels:', len(d['panels']), 'vars:', [v['name'] for v in d['templating']['list']])"
```

Expected: `panels: 5 vars: ['room']`.

Manual check (needs a browser): open
`http://localhost:3001/d/zoom-room-detail?var-room=SG-Galaxis-17F-Charles Yang 6284&from=now-30d&to=now`
and confirm: (a) the room dropdown is populated with ~136 rooms — if empty, the variable query shape is wrong for this plugin version: open the variable editor, re-select Query type = Host, Group = Rooms/Singapore, Host = /.*/, save, and export the corrected JSON back into `grafana-room-detail.json`; (b) the online/offline timeline shows a long red band (this room has been offline since June); (c) the outages table lists the offline problem; (d) the device timeline shows data with gaps.

- [ ] **Step 5: Commit**

```bash
git add deploy/grafana-room-detail.json deploy/import-dashboard.sh
git commit -m "Add per-room detail dashboard: 30d timeline, outages, devices

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Wire click-through from the main dashboard

**Files:**
- Modify: `deploy/grafana-dashboard.json` (panel id 6 "Active issues (SG)" — replace; panel id 7 "Room status grid" — add data link)

**Interfaces:**
- Consumes: `/d/zoom-room-detail?var-room=...&from=now-30d&to=now` from Task 4.
- Produces: main dashboard where clicking an issue row or a grid tile opens the room's detail view.

- [ ] **Step 1: Replace the triggers panel with a table panel**

In `deploy/grafana-dashboard.json`, replace the entire panel object with `"id": 6` (currently `"type": "alexanderzobnin-zabbix-triggers-panel"`, lines ~295-442) with:

```json
{
  "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
  "gridPos": { "h": 12, "w": 24, "x": 0, "y": 4 },
  "id": 6,
  "title": "Active issues (SG) — click a row for 30-day room history",
  "type": "table",
  "fieldConfig": {
    "defaults": {
      "custom": { "align": "auto", "cellOptions": { "type": "auto" }, "filterable": false },
      "links": [
        {
          "title": "Room history (30d)",
          "url": "/d/zoom-room-detail?var-room=${__data.fields.Host:percentencode}&from=now-30d&to=now"
        }
      ]
    },
    "overrides": []
  },
  "options": {
    "cellHeight": "sm",
    "footer": { "show": false },
    "showHeader": true,
    "sortBy": [{ "displayName": "Time", "desc": true }]
  },
  "targets": [
    {
      "refId": "A",
      "queryType": "5",
      "schema": 12,
      "showProblems": "problems",
      "datasource": { "type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc" },
      "functions": [],
      "evaltype": "0",
      "application": { "filter": "" },
      "group": { "filter": "Rooms/Singapore" },
      "host": { "filter": "/.*/" },
      "item": { "filter": "" },
      "itemTag": { "filter": "" },
      "macro": { "filter": "" },
      "proxy": { "filter": "" },
      "tags": { "filter": "" },
      "trigger": { "filter": "" },
      "textFilter": "",
      "countTriggersBy": "",
      "options": {
        "acknowledged": 2,
        "count": false,
        "disableDataAlignment": false,
        "hostProxy": false,
        "hostsInMaintenance": false,
        "limit": 1001,
        "minSeverity": 0,
        "showDisabledItems": false,
        "skipEmptyValues": false,
        "sortProblems": "default",
        "useTimeRange": false,
        "useTrends": "default",
        "useZabbixValueMapping": false
      },
      "resultFormat": "table",
      "table": { "skipEmptyValues": false }
    }
  ]
}
```

- [ ] **Step 2: Verify the problems-table field names (the data link depends on them)**

Import first (`GF_ADMIN_PASS=<real password> ./import-dashboard.sh`), then query the datasource through Grafana and print the returned column names:

```bash
curl -s "http://admin:${GF_ADMIN_PASS}@localhost:3001/api/ds/query" \
  -H "Content-Type: application/json" -d '{
  "queries": [{
    "refId": "A", "queryType": "5", "schema": 12, "showProblems": "problems",
    "datasource": {"type": "alexanderzobnin-zabbix-datasource", "uid": "zabbix-poc"},
    "group": {"filter": "Rooms/Singapore"}, "host": {"filter": "/.*/"},
    "application": {"filter": ""}, "item": {"filter": ""}, "itemTag": {"filter": ""},
    "macro": {"filter": ""}, "proxy": {"filter": ""}, "tags": {"filter": ""},
    "trigger": {"filter": ""}, "textFilter": "", "evaltype": "0", "functions": [],
    "options": {"acknowledged": 2, "count": false, "limit": 1001, "minSeverity": 0,
                "useTimeRange": false},
    "resultFormat": "table", "intervalMs": 60000, "maxDataPoints": 100
  }],
  "from": "now-6h", "to": "now"
}' | python3 -c "
import sys, json
r = json.load(sys.stdin)
frames = r['results']['A']['frames']
print([f['schema']['name'] for f in frames])
print([fld['name'] for fld in frames[0]['schema']['fields']])"
```

Expected: a field list containing a host-name column. If it is `host` (lowercase) or `Hostname` instead of `Host`, update the data-link URL in Step 1's JSON to match (`${__data.fields.<actual name>:percentencode}`) and re-import.

- [ ] **Step 3: Add the data link to the status grid panel**

In the panel with `"id": 7` ("Room status grid (red = offline)"), inside `fieldConfig.defaults`, add a `links` array alongside the existing `displayName`/`mappings`/`thresholds` keys:

```json
"links": [
  {
    "title": "Room history (30d)",
    "url": "/d/zoom-room-detail?var-room=${__field.labels.host:percentencode}&from=now-30d&to=now"
  }
]
```

- [ ] **Step 4: Import and verify end-to-end**

Run: `GF_ADMIN_PASS=<real password> ./import-dashboard.sh`
Expected: two `import: success` lines.

Manual browser check on `http://localhost:3001/d/zoom-sg-poc`:
1. Active issues table shows current problems (compare count with the old panel's — poller reports ~4 offline).
2. Clicking a row offers "Room history (30d)" and lands on the detail dashboard with that room selected and a 30-day range.
3. Clicking any grid tile does the same.
4. The detail page for `SG-Galaxis-17F-Charles Yang 6284` shows the June-to-now outage.

If the grid-tile link resolves to an empty `var-room`, the field label name differs — inspect the panel (Panel → Inspect → Data) and switch the URL to the label actually present (e.g. `${__field.name:percentencode}`), re-import.

- [ ] **Step 5: Commit**

```bash
git add deploy/grafana-dashboard.json
git commit -m "Main dashboard: issues table + grid tiles link to room detail

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Update README and final verification

**Files:**
- Modify: `README.md` (dashboard bullet list in "See it live", ~lines 61-71; "Project layout" table already covers deploy/)

**Interfaces:**
- Consumes: everything above, live and verified.

- [ ] **Step 1: Update README "See it live" section**

After the four dashboard bullets in `README.md` (the list ending with the 136-tile grid bullet), add:

```markdown
- **Click any issue or room tile** to drill into that room's **30-day history**
  (`/d/zoom-room-detail`): online/offline timeline, uptime %, outage log, and
  device status (collected while the room is in the 5-room detail subset).
```

- [ ] **Step 2: Full test sweep**

From `bridge/`:
`.venv/bin/python -c "import test_mapper as t; fns=[getattr(t,n) for n in dir(t) if n.startswith('test_')]; [f() for f in fns]; print(len(fns),'passed')"`
`.venv/bin/python -c "import test_provision as t; fns=[getattr(t,n) for n in dir(t) if n.startswith('test_')]; [f() for f in fns]; print(len(fns),'passed')"`
Expected: `9 passed`, `3 passed`.

Check the poller is still clean after the reprovision (retention update must not have disturbed it):
`tail -2 bridge/logs/agent.log` → expect `failed: 0`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "README: document room-history drilldown

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
