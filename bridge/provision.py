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

from zoom_client import ZoomClient
from zabbix_client import ZabbixAPI
from mapper import sanitize_host_name, parse_tags

REGION_PREFIX = os.environ.get("REGION_PREFIX", "SG")

ROOM_TEMPLATE = "Template Zoom Room"
DEV_TEMPLATE = "Template Zoom Room Devices"
FLEET_TEMPLATE = "Template Zoom Fleet"
FLEET_HOST_TECH = "SG-Fleet-Summary"
FLEET_HOST_NAME = "SG Fleet Summary"

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


def ensure_trigger(api, description, expression, priority):
    existing = api.call("trigger.get", {"filter": {"description": description}})
    if existing:
        return
    api.call("trigger.create",
             {"description": description, "expression": expression, "priority": priority})


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
    if any(d["triggerid"] == dep["triggerid"] for d in trig.get("dependencies", [])):
        return
    api.call("trigger.update", {"triggerid": trig["triggerid"],
                                "dependencies": [{"triggerid": dep["triggerid"]}]})


# --- templates ----------------------------------------------------------------

def build_room_template(api, tg_id):
    tid = get_or_create_template(api, ROOM_TEMPLATE, tg_id)
    ensure_items(api, tid, [
        ("zoom.room.status", "Room status (raw)", T_TEXT),
        ("zoom.room.online", "Room online (1/0)", T_UNSIGNED),
    ])
    ensure_trigger(
        api,
        "Room {HOST.NAME} is offline",
        f"min(/{ROOM_TEMPLATE}/zoom.room.online,#2)=0",
        SEV_HIGH,
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
    ensure_trigger(api, "Computer disconnected on {HOST.NAME}",
                   f"last(/{DEV_TEMPLATE}/zoom.device.computer.status)=0", SEV_AVERAGE)
    ensure_trigger(api, "Controller disconnected on {HOST.NAME}",
                   f"last(/{DEV_TEMPLATE}/zoom.device.controller.status)=0", SEV_AVERAGE)
    return tid


# --- hosts --------------------------------------------------------------------

def fetch_region_rooms(client):
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
    return [x for x in rooms if x.get("name", "").upper().startswith(REGION_PREFIX.upper())]


def ensure_hosts(api, rooms, hg_id, room_tpl, dev_tpl):
    # Every host gets both templates: the poller's device subset is dynamic
    # (offline rooms first), so any room may receive device items on any cycle.
    existing = {h["host"]: h["hostid"]
                for h in api.call("host.get", {"groupids": hg_id, "output": ["host"]})}
    created = linked = 0
    for room in rooms:
        name = room["name"]
        tech = sanitize_host_name(name)
        tags = [{"tag": k, "value": v} for k, v in parse_tags(name).items()]
        templates = [{"templateid": room_tpl}, {"templateid": dev_tpl}]
        if tech in existing:
            # keep idempotent: make sure template links are present
            api.call("host.update", {"hostid": existing[tech], "templates": templates})
            linked += 1
            continue
        api.call("host.create", {
            "host": tech,
            "name": name,
            "groups": [{"groupid": hg_id}],
            "templates": templates,
            "tags": tags,
        })
        created += 1
    return created, linked


def main():
    api = ZabbixAPI()
    api.login()
    print(">> Zabbix login OK")

    hg_id = get_or_create_hostgroup(api, "Rooms/Singapore")
    tg_id = get_or_create_templategroup(api, "Templates/Zoom")
    room_tpl = build_room_template(api, tg_id)
    dev_tpl = build_device_template(api, tg_id)
    fleet_tpl = build_fleet_template(api, tg_id)
    ensure_fleet_host(api, hg_id, fleet_tpl)
    for desc in ("Computer disconnected on {HOST.NAME}",
                 "Controller disconnected on {HOST.NAME}"):
        ensure_trigger_dependency(api, dev_tpl, desc,
                                  room_tpl, "Room {HOST.NAME} is offline")
    print(f">> templates ready (room={room_tpl}, devices={dev_tpl}, fleet={fleet_tpl})")

    client = ZoomClient()
    rooms = fetch_region_rooms(client)
    print(f">> {len(rooms)} {REGION_PREFIX} rooms from Zoom")

    created, linked = ensure_hosts(api, rooms, hg_id, room_tpl, dev_tpl)
    print(f">> hosts: {created} created, {linked} already existed (templates re-linked)")
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
