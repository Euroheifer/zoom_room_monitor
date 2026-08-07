"""Provision Zabbix for the POC (idempotent).

Creates:
  * host group     Rooms/Singapore
  * template group Templates/Zoom
  * template       "Template Zoom Room"          -> status/online + offline trigger
  * template       "Template Zoom Room Devices"  -> device status + disconnect triggers
  * one host per SG room, linked to both templates (the poller's device subset is
    dynamic, so every host must accept device items), tagged region/building/floor.

Run:  ./run_provision.sh         (loads .env, runs in the venv)
"""
from __future__ import annotations

import os
import sys

import re

from zoom_client import ZoomClient
from zabbix_client import ZabbixAPI
from mapper import sanitize_host_name, parse_tags

REGION_PREFIX = os.environ.get("REGION_PREFIX", "SG")
# Room selection: by name prefix (REGION_PREFIX) by default, or — when rooms
# don't share a name prefix (e.g. CNGR = CNBJ-/CNSH-) — by location-directory
# subtree: set LOCATION_ROOT to the directory node name (e.g. "CNGR").
LOCATION_ROOT = os.environ.get("LOCATION_ROOT", "")
HOST_GROUP = os.environ.get("HOST_GROUP", "Rooms/Singapore")
# Campus names like SGP-GLX carry a redundant site prefix; CNGR campuses like
# BJ-JinHui carry the CITY, which must be kept. Set 0 to keep the full name.
STRIP_CAMPUS_PREFIX = os.environ.get("STRIP_CAMPUS_PREFIX", "1") == "1"
# Must exceed the device sweep time: ceil(rooms/subset) * poll interval.
# 135 rooms / 15 per 5m cycle ~= 45m -> 1h. At the 700-room final design,
# raise to 3h (subset 30 -> ~2h sweep).
DEVICE_STALE_WINDOW = os.environ.get("DEVICE_STALE_WINDOW", "1h")

ROOM_TEMPLATE = "Template Zoom Room"
DEV_TEMPLATE = "Template Zoom Room Devices"
FLEET_TEMPLATE = "Template Zoom Fleet"
FLEET_HOST_TECH = f"{REGION_PREFIX}-Fleet-Summary"
FLEET_HOST_NAME = f"{REGION_PREFIX} Fleet Summary"

# Zabbix value types
T_UNSIGNED, T_TEXT = 3, 4
TYPE_TRAPPER = 2
SEV_AVERAGE, SEV_HIGH = 3, 4


# --- generic get-or-create helpers --------------------------------------------

def get_or_create_hostgroup(api, name):
    g = api.call("hostgroup.get", {"filter": {"name": [name]}})
    if g:
        return g[0]["groupid"]
    return api.call("hostgroup.create", {"name": name})["groupids"][0]


def get_or_create_templategroup(api, name):
    g = api.call("templategroup.get", {"filter": {"name": [name]}})
    if g:
        return g[0]["groupid"]
    return api.call("templategroup.create", {"name": name})["groupids"][0]


def get_or_create_template(api, tech_name, tg_id):
    t = api.call("template.get", {"filter": {"host": [tech_name]}})
    if t:
        return t[0]["templateid"]
    return api.call("template.create",
                    {"host": tech_name, "groups": [{"groupid": tg_id}]})["templateids"][0]


def ensure_items(api, template_id, specs, history="90d", trends="365d"):
    """specs: list of (key, name, value_type). Creates missing items and keeps
    history/trends retention in sync on existing ones (30-day dashboards need
    more history margin than Zabbix's 31d default; a year of hourly trends on
    numeric items enables quarter-over-quarter uptime reporting)."""
    existing = {i["key_"]: i for i in api.call("item.get",
                {"templateids": template_id, "output": ["itemid", "key_", "history", "trends"]})}
    for key, name, vtype in specs:
        tr = trends if vtype == T_UNSIGNED else "0"  # text items have no trends
        cur = existing.get(key)
        if cur is None:
            api.call("item.create", {
                "name": name, "key_": key, "hostid": template_id,
                "type": TYPE_TRAPPER, "value_type": vtype,
                "history": history, "trends": tr,
            })
        elif cur["history"] != history or cur["trends"] != tr:
            api.call("item.update", {"itemid": cur["itemid"],
                                     "history": history, "trends": tr})


def ensure_trigger(api, description, expression, priority, manual_close=0, opdata=""):
    """Create the template trigger, or bring an existing one's expression /
    manual_close / opdata in line (idempotent, like ensure_items)."""
    existing = api.call("trigger.get", {"filter": {"description": description},
                                        "templated": True,  # the template's own trigger, not host-inherited copies
                                        "output": ["triggerid", "expression", "manual_close", "opdata"],
                                        "expandExpression": True})
    if not existing:
        api.call("trigger.create",
                 {"description": description, "expression": expression,
                  "priority": priority, "manual_close": manual_close, "opdata": opdata})
        return
    cur = existing[0]
    if (cur["expression"] != expression or int(cur.get("manual_close", 0)) != manual_close
            or cur.get("opdata", "") != opdata):
        api.call("trigger.update", {"triggerid": cur["triggerid"],
                                    "expression": expression,
                                    "manual_close": manual_close, "opdata": opdata})


def ensure_trigger_dependency(api, template_id, description, dep_template_id, dep_description):
    """Make template trigger `description` depend on `dep_description`, so Zabbix
    suppresses the dependent problem while the parent is active (e.g. no device
    alerts while the whole room is offline — one incident, one row)."""
    trig = api.call("trigger.get", {"templateids": template_id,
                                    "filter": {"description": description},
                                    "output": ["triggerid"],
                                    "selectDependencies": ["triggerid"]})[0]
    dep = api.call("trigger.get", {"templateids": dep_template_id,
                                   "filter": {"description": dep_description},
                                   "output": ["triggerid"]})[0]
    cur = [d["triggerid"] for d in trig.get("dependencies", [])]
    if dep["triggerid"] in cur:
        return
    api.call("trigger.update", {"triggerid": trig["triggerid"],
                                "dependencies": [{"triggerid": t}
                                                 for t in cur + [dep["triggerid"]]]})


# --- templates ----------------------------------------------------------------

def build_room_template(api, tg_id):
    tid = get_or_create_template(api, ROOM_TEMPLATE, tg_id)
    ensure_items(api, tid, [
        ("zoom.room.status", "Room status (raw)", T_TEXT),
        ("zoom.room.online", "Room online (1/0)", T_UNSIGNED),
        ("zoom.room.health", "Room health", T_TEXT),
        ("zoom.room.issues", "Room issues", T_TEXT),
    ])
    ensure_trigger(
        api,
        "Room {HOST.NAME} is offline",
        f"min(/{ROOM_TEMPLATE}/zoom.room.online,#2)=0",
        SEV_HIGH,
    )
    # Zoom-dashboard health: mic / speaker / camera / controller issues the
    # device polling can't see. Suppressed while the room is offline (dep in
    # main); stale guard mirrors the device triggers.
    ensure_trigger(
        api,
        "{ITEM.LASTVALUE1}",
        f'last(/{ROOM_TEMPLATE}/zoom.room.issues)<>"none"'
        f' and nodata(/{ROOM_TEMPLATE}/zoom.room.issues,{DEVICE_STALE_WINDOW})=0',
        SEV_AVERAGE,
        manual_close=1,
        opdata="{ITEM.LASTVALUE1}",  # the live issue text, shown on dashboards
    )
    return tid


def build_fleet_template(api, tg_id):
    tid = get_or_create_template(api, FLEET_TEMPLATE, tg_id)
    ensure_items(api, tid, [
        ("zoom.fleet.total", "Fleet: total rooms", T_UNSIGNED),
        ("zoom.fleet.online", "Fleet: rooms online", T_UNSIGNED),
        ("zoom.fleet.offline", "Fleet: rooms offline", T_UNSIGNED),
        ("zoom.fleet.inmeeting", "Fleet: rooms in meeting", T_UNSIGNED),
    ])
    return tid


def ensure_fleet_host(api, hg_id, fleet_tpl):
    existing = api.call("host.get", {"filter": {"host": [FLEET_HOST_TECH]}, "output": ["hostid"]})
    if existing:
        api.call("host.update", {"hostid": existing[0]["hostid"],
                                 "templates": [{"templateid": fleet_tpl}]})
        return
    api.call("host.create", {
        "host": FLEET_HOST_TECH,
        "name": FLEET_HOST_NAME,
        "groups": [{"groupid": hg_id}],
        "templates": [{"templateid": fleet_tpl}],
        "tags": [{"tag": "region", "value": REGION_PREFIX}, {"tag": "role", "value": "summary"}],
    })


def build_device_template(api, tg_id):
    tid = get_or_create_template(api, DEV_TEMPLATE, tg_id)
    ensure_items(api, tid, [
        ("zoom.device.computer.status", "Computer online (1/0)", T_UNSIGNED),
        ("zoom.device.controller.status", "Controller online (1/0)", T_UNSIGNED),
        ("zoom.device.computer.version", "Computer app version", T_TEXT),
        ("zoom.device.controller.version", "Controller version", T_TEXT),
    ])
    # nodata() guard: device values only refresh while a room is in the poller's
    # detail subset, so a bare last()=0 keeps firing on stale data long after a
    # room recovers. With the guard the alert self-clears once data goes stale.
    # manual_close lets stale problems be closed by hand / API.
    for role in ("computer", "controller"):
        key = f"zoom.device.{role}.status"
        ensure_trigger(
            api,
            f"{role.capitalize()} disconnected on {{HOST.NAME}}",
            f"last(/{DEV_TEMPLATE}/{key})=0 and nodata(/{DEV_TEMPLATE}/{key},{DEVICE_STALE_WINDOW})=0",
            SEV_AVERAGE,
            manual_close=1,
        )
    return tid


# --- locations ------------------------------------------------------------------
# The Zoom location directory (floor <- building <- campus <- country) is the
# source of truth for building/floor — room-name spelling drifts (GLX vs
# Galaxis). Building = campus name minus the site prefix (SGP-GLX -> GLX).

_CAMPUS_PREFIX = re.compile(r"^[A-Z]{2,4}-")
# Rooms whose directory location shouldn't be shown as-is on dashboards:
# tech host name -> (building, floor).
LOCATION_OVERRIDES = {"SG-Office": ("GLX", "17F")}


def fetch_locations(client):
    locs, tok = [], None
    while True:
        params = {"page_size": 300}
        if tok:
            params["next_page_token"] = tok
        r = client.get("/rooms/locations", params=params).json()
        locs += r.get("locations", [])
        tok = r.get("next_page_token") or ""
        if not tok:
            break
    return {l["id"]: l for l in locs}


def location_tags(room, locs):
    """{'building','floor'} from the room's location chain; {} if unassigned.
    Dashes are squashed so the SG-{building}-{floor}-{room} visible-name scheme
    (which the dashboard filters parse) stays unambiguous."""
    out, lid = {}, room.get("location_id")
    while lid and lid in locs:
        loc = locs[lid]
        if loc.get("type") == "floor":
            out["floor"] = loc["name"].replace("-", " ").strip()
        elif loc.get("type") == "campus":
            name = _CAMPUS_PREFIX.sub("", loc["name"]) if STRIP_CAMPUS_PREFIX else loc["name"]
            out["building"] = name.replace("-", " ").strip()
        lid = loc.get("parent_location_id")
    return out


def canonical_room_name(room, tech, locs):
    """Visible host name SG-{building}-{floor}-{leaf}, location-directory-driven.
    Falls back to the raw room name when the room has no building/floor."""
    over = LOCATION_OVERRIDES.get(tech)
    loc = dict(zip(("building", "floor"), over)) if over else location_tags(room, locs)
    if "building" not in loc or "floor" not in loc:
        return room["name"], loc
    leaf = re.sub(rf"^{REGION_PREFIX}-[^-]+-[^-]+-", "", room["name"]).strip()
    if leaf == room["name"] and "-" in leaf:
        # name doesn't follow the {REGION}-b-f- convention (e.g. CNBJ-JL_26F):
        # keep only the last dash-segment, the room's own identifier.
        leaf = leaf.rsplit("-", 1)[-1].strip()
    if not leaf:
        leaf = room["name"]
    if over:  # don't leak the raw name through the leaf (e.g. "SG-Office")
        leaf = re.sub(rf"^{REGION_PREFIX}-", "", leaf)
    return f"{REGION_PREFIX}-{loc['building']}-{loc['floor']}-{leaf}", loc


# --- hosts --------------------------------------------------------------------

def location_subtree(locs, root_name):
    """All location ids at or under the directory node named root_name."""
    sub = {lid for lid, l in locs.items() if l["name"] == root_name}
    if not sub:
        raise SystemExit(f"location '{root_name}' not found in the Zoom directory")
    while True:
        more = {lid for lid, l in locs.items()
                if lid not in sub and l.get("parent_location_id") in sub}
        if not more:
            return sub
        sub |= more


def fetch_region_rooms(client, locs=None):
    rooms, tok = [], None
    while True:
        params = {"page_size": 300}
        if tok:
            params["next_page_token"] = tok
        r = client.get("/rooms", params=params).json()
        rooms += r.get("rooms", [])
        tok = r.get("next_page_token") or ""
        if not tok:
            break
    if LOCATION_ROOT:
        sub = location_subtree(locs, LOCATION_ROOT)
        return [x for x in rooms if x.get("location_id") in sub]
    return [x for x in rooms if x.get("name", "").upper().startswith(REGION_PREFIX.upper())]


def ensure_hosts(api, rooms, locs, hg_id, room_tpl, dev_tpl):
    # Every host gets both templates: the poller's device subset is dynamic
    # (offline rooms first), so any room may receive device items on any cycle.
    # Visible name + tags come from the location directory and are kept in sync.
    existing = {h["host"]: h
                for h in api.call("host.get", {"groupids": hg_id,
                                               "output": ["hostid", "host", "name"],
                                               "selectTags": "extend"})}
    created = renamed = linked = 0
    for room in rooms:
        tech = sanitize_host_name(room["name"])
        visible, loc = canonical_room_name(room, tech, locs)
        tag_map = {"region": REGION_PREFIX, **(loc or parse_tags(room["name"]))}
        tags = [{"tag": k, "value": v} for k, v in sorted(tag_map.items())]
        templates = [{"templateid": room_tpl}, {"templateid": dev_tpl}]
        cur = existing.get(tech)
        if cur is None:
            api.call("host.create", {
                "host": tech, "name": visible, "groups": [{"groupid": hg_id}],
                "templates": templates, "tags": tags,
            })
            created += 1
            continue
        upd = {"hostid": cur["hostid"], "templates": templates}
        cur_tags = sorted((t["tag"], t["value"]) for t in cur.get("tags", []))
        if cur["name"] != visible or cur_tags != sorted(tag_map.items()):
            upd.update({"name": visible, "tags": tags})
            renamed += 1
        api.call("host.update", upd)
        linked += 1
    return created, renamed, linked


def main():
    api = ZabbixAPI()
    api.login()
    print(">> Zabbix login OK")

    hg_id = get_or_create_hostgroup(api, HOST_GROUP)
    tg_id = get_or_create_templategroup(api, "Templates/Zoom")
    room_tpl = build_room_template(api, tg_id)
    dev_tpl = build_device_template(api, tg_id)
    fleet_tpl = build_fleet_template(api, tg_id)
    ensure_fleet_host(api, hg_id, fleet_tpl)
    for desc in ("Computer disconnected on {HOST.NAME}",
                 "Controller disconnected on {HOST.NAME}"):
        ensure_trigger_dependency(api, dev_tpl, desc,
                                  room_tpl, "Room {HOST.NAME} is offline")
    # health alert defers to the more specific problems (offline dominates the
    # dashboard-metrics 'critical' state; computer/controller have own triggers)
    ensure_trigger_dependency(api, room_tpl, "{ITEM.LASTVALUE1}",
                              room_tpl, "Room {HOST.NAME} is offline")
    for desc in ("Computer disconnected on {HOST.NAME}",
                 "Controller disconnected on {HOST.NAME}"):
        ensure_trigger_dependency(api, room_tpl, "{ITEM.LASTVALUE1}",
                                  dev_tpl, desc)
    print(f">> templates ready (room={room_tpl}, devices={dev_tpl}, fleet={fleet_tpl})")

    client = ZoomClient()
    locs = fetch_locations(client)
    rooms = fetch_region_rooms(client, locs)
    print(f">> {len(rooms)} {REGION_PREFIX} rooms from Zoom, {len(locs)} directory locations")

    created, renamed, linked = ensure_hosts(api, rooms, locs, hg_id, room_tpl, dev_tpl)
    print(f">> hosts: {created} created, {renamed} renamed/retagged, "
          f"{linked} existing (templates re-linked)")
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
