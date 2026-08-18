"""Install the in-Zabbix collector: ONE script item on the carrier fleet host
that sweeps the Zoom account once per cycle and buckets rooms per region
(see collector.js). Other regions' fleet hosts get a zoom.bridge.run trapper
item fed by the collector, so every region keeps its own nodata trigger.
Idempotent.

Run:  set -a; . ./.env; set +a; .venv/bin/python install_collector.py
"""
from __future__ import annotations

import json
import os
import pathlib

from zabbix_client import ZabbixAPI

# one entry per region. Rooms are selected by the Zoom location-directory
# subtree under the node named after the region — the directory is the single
# source of truth (room naming conventions are not trusted: test/VIP rooms
# don't follow them). Optional keys: location_root (if the directory node is
# named differently), fleet_host.
REGIONS = [
    {"name": "SG"},
    {"name": "CNGR"},
    {"name": "BR"},
]
CARRIER = "SG-Fleet-Summary"  # host carrying the script item
KEY = "zoom.bridge.run"
SCRIPT = (pathlib.Path(__file__).parent / "collector.js").read_text()

TEXT, SECRET = 0, 1  # macro types
MACROS = [
    ("{$ZOOM.ACCOUNT.ID}", os.environ["ZOOM_ACCOUNT_ID"], TEXT),
    ("{$ZOOM.CLIENT.ID}", os.environ["ZOOM_CLIENT_ID"], TEXT),
    ("{$ZOOM.CLIENT.SECRET}", os.environ["ZOOM_CLIENT_SECRET"], SECRET),
    ("{$ZOOM.ZBX.URL}", os.environ["ZBX_API_URL"], TEXT),
    ("{$ZOOM.ZBX.TOKEN}", os.environ["ZBX_API_TOKEN"], SECRET),
]
PARAMETERS = [
    {"name": "account_id", "value": "{$ZOOM.ACCOUNT.ID}"},
    {"name": "client_id", "value": "{$ZOOM.CLIENT.ID}"},
    {"name": "client_secret", "value": "{$ZOOM.CLIENT.SECRET}"},
    {"name": "zbx_url", "value": "{$ZOOM.ZBX.URL}"},
    {"name": "zbx_token", "value": "{$ZOOM.ZBX.TOKEN}"},
    {"name": "regions", "value": json.dumps(REGIONS)},
    {"name": "carrier_fleet_host", "value": CARRIER},
    # Device-detail rotation budget, GLOBAL across regions: Zoom calls per cycle
    # = subset_size regardless of region count (30 sequential calls fits the 60s
    # item timeout). Keep ceil(total_rooms/subset)*interval under the device
    # triggers' DEVICE_STALE_WINDOW (provision.py): 234 rooms / 30 per 5m ~= 40m
    # < 1h. At ~760 rooms that sweep is ~2h — raise DEVICE_STALE_WINDOW to 3h.
    {"name": "subset_size", "value": os.environ.get("PERIPHERAL_SUBSET_SIZE", "30")},
    {"name": "interval", "value": "300"},  # must match the item delay below
]


def fleet_host(region: dict) -> str:
    return region.get("fleet_host", f"{region['name']}-Fleet-Summary")


def main():
    api = ZabbixAPI()
    api.login()
    hostids = {}
    for region in REGIONS:
        h = fleet_host(region)
        hostids[h] = api.call("host.get", {"filter": {"host": [h]}})[0]["hostid"]
    carrier_id = hostids[CARRIER]

    existing = {m["macro"]: m["hostmacroid"]
                for m in api.call("usermacro.get", {"hostids": [carrier_id]})}
    for macro, val, typ in MACROS:
        if macro in existing:
            api.call("usermacro.update",
                     {"hostmacroid": existing[macro], "value": val, "type": typ})
        else:
            api.call("usermacro.create",
                     {"hostid": carrier_id, "macro": macro, "value": val, "type": typ})
    print(f">> {len(MACROS)} macros set on {CARRIER}")

    # carrier: the script item (its return value is the cycle summary)
    item = {
        "name": "Zoom collector cycle",
        "key_": KEY,
        "hostid": carrier_id,
        "type": 21,          # SCRIPT
        "value_type": 4,     # TEXT (JSON summary of the cycle)
        "delay": "300s",
        "timeout": "60s",
        "params": SCRIPT,
        "parameters": PARAMETERS,
    }
    got = api.call("item.get", {"hostids": [carrier_id], "filter": {"key_": [KEY]}})
    if got:
        upd = {k: v for k, v in item.items() if k not in ("hostid", "key_")}
        api.call("item.update", {"itemid": got[0]["itemid"], **upd})
        print(f">> {CARRIER}: script item {KEY} updated (itemid={got[0]['itemid']})")
    else:
        r = api.call("item.create", item)
        print(f">> {CARRIER}: script item {KEY} created (itemid={r['itemids'][0]})")

    # other regions: zoom.bridge.run as a TRAPPER the collector pushes to
    for region in REGIONS:
        h = fleet_host(region)
        if h == CARRIER:
            continue
        got = api.call("item.get", {"hostids": [hostids[h]], "filter": {"key_": [KEY]}})
        if got and got[0]["type"] == "2":
            print(f">> {h}: trapper {KEY} exists (itemid={got[0]['itemid']})")
        elif got:
            api.call("item.update", {"itemid": got[0]["itemid"], "type": 2, "delay": "0"})
            print(f">> {h}: item {KEY} converted to trapper (itemid={got[0]['itemid']})")
        else:
            r = api.call("item.create", {
                "name": "Zoom collector cycle", "key_": KEY, "hostid": hostids[h],
                "type": 2, "value_type": 4})
            print(f">> {h}: trapper {KEY} created (itemid={r['itemids'][0]})")

    for region in REGIONS:
        h = fleet_host(region)
        desc = "Zoom collector stopped reporting"
        if not api.call("trigger.get", {"filter": {"description": [desc]},
                                        "hostids": [hostids[h]]}):
            api.call("trigger.create", {
                "description": desc,
                "expression": f"nodata(/{h}/{KEY},10m)=1",
                "priority": 4,  # High — the whole feed is down
            })
            print(f">> {h}: nodata trigger created")
    print("Done.")


if __name__ == "__main__":
    main()
