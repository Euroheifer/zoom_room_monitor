"""Install the in-Zabbix collector: a script item on the fleet-summary host
that replaces the external Python poller (see collector.js). Idempotent.

Run:  set -a; . ./.env; set +a; .venv/bin/python install_collector.py
"""
from __future__ import annotations

import os
import pathlib

from zabbix_client import ZabbixAPI

HOST = "SG-Fleet-Summary"
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
    {"name": "region", "value": os.environ.get("REGION_PREFIX", "SG")},
    # subset/interval sizing: keep ceil(rooms/subset)*interval under the device
    # triggers' DEVICE_STALE_WINDOW (see provision.py). 15 per 5m cycle sweeps
    # 135 SG rooms in ~45m; at 700 rooms use subset 30 + a 3h window.
    {"name": "subset_size", "value": os.environ.get("PERIPHERAL_SUBSET_SIZE", "15")},
    {"name": "interval", "value": "300"},  # must match the item delay below
]


def main():
    api = ZabbixAPI()
    api.login()
    hostid = api.call("host.get", {"filter": {"host": [HOST]}})[0]["hostid"]

    existing = {m["macro"]: m["hostmacroid"]
                for m in api.call("usermacro.get", {"hostids": [hostid]})}
    for macro, val, typ in MACROS:
        if macro in existing:
            api.call("usermacro.update",
                     {"hostmacroid": existing[macro], "value": val, "type": typ})
        else:
            api.call("usermacro.create",
                     {"hostid": hostid, "macro": macro, "value": val, "type": typ})
    print(f">> {len(MACROS)} macros set on {HOST}")

    item = {
        "name": "Zoom collector cycle",
        "key_": KEY,
        "hostid": hostid,
        "type": 21,          # SCRIPT
        "value_type": 4,     # TEXT (JSON summary of the cycle)
        "delay": "300s",
        "timeout": "60s",
        "params": SCRIPT,
        "parameters": PARAMETERS,
    }
    got = api.call("item.get", {"hostids": [hostid], "filter": {"key_": [KEY]}})
    if got:
        upd = {k: v for k, v in item.items() if k not in ("hostid", "key_")}
        api.call("item.update", {"itemid": got[0]["itemid"], **upd})
        print(f">> item {KEY} updated (itemid={got[0]['itemid']})")
    else:
        r = api.call("item.create", item)
        print(f">> item {KEY} created (itemid={r['itemids'][0]})")

    desc = "Zoom collector stopped reporting"
    if not api.call("trigger.get", {"filter": {"description": [desc]}, "hostids": [hostid]}):
        api.call("trigger.create", {
            "description": desc,
            "expression": f"nodata(/{HOST}/{KEY},10m)=1",
            "priority": 4,  # High — the whole feed is down
        })
        print(">> nodata trigger created")
    print("Done.")


if __name__ == "__main__":
    main()
