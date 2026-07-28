"""The bridge: poll Zoom -> map -> push to Zabbix trapper.

One cycle:
  1. GET /rooms (all rooms)         -> status/online for every SG host   (cheap)
  2. GET /rooms/{id}/devices        -> device status for the subset only (per-room)
  3. push all values to the Zabbix trapper in one batch

Runs once by default; pass --loop to poll on an interval (POLL_INTERVAL secs).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

from zoom_client import ZoomClient
from zabbix_client import send_values
from mapper import sanitize_host_name, room_to_values, devices_to_values, fleet_counts

FLEET_HOST = "SG-Fleet-Summary"

REGION_PREFIX = os.environ.get("REGION_PREFIX", "SG")
# 10/cycle x 120s sweeps ~130 online rooms in ~26 min — inside the device
# triggers' nodata(30m) window, so healthy alerts don't self-clear mid-sweep.
SUBSET_SIZE = int(os.environ.get("PERIPHERAL_SUBSET_SIZE", "10"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "120"))


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


def choose_subset(rooms, size, offset):
    """Rotate a device-polling window through the ONLINE rooms.

    Offline rooms are skipped: their devices are known-dead and the device
    triggers are suppressed by the room-offline dependency anyway. The window
    advances by `size` each cycle, so the whole online fleet is swept every
    ceil(n/size) cycles — keep that sweep under the device triggers'
    nodata(30m) window or healthy alerts self-clear between visits.
    """
    online = sorted((r for r in rooms if r.get("status") != "Offline"),
                    key=lambda r: r["name"])
    if not online:
        return []
    start = offset % len(online)
    return [online[(start + i) % len(online)] for i in range(min(size, len(online)))]


def cycle(client, offset=0) -> dict:
    rooms = fetch_region_rooms(client)
    batch = []
    for room in rooms:
        host = sanitize_host_name(room["name"])
        for key, value in room_to_values(room).items():
            batch.append({"host": host, "key": key, "value": str(value)})

    # peripheral detail for the rotating subset
    subset = choose_subset(rooms, SUBSET_SIZE, offset)
    for room in subset:
        host = sanitize_host_name(room["name"])
        resp = client.get(f"/rooms/{room['id']}/devices")
        if resp.status_code != 200:
            continue
        devices = resp.json().get("devices", [])
        for key, value in devices_to_values(devices).items():
            batch.append({"host": host, "key": key, "value": str(value)})

    # fleet-level rollup -> summary host (headline stats + history)
    for key, value in fleet_counts(rooms).items():
        batch.append({"host": FLEET_HOST, "key": key, "value": str(value)})

    result = send_values(batch)
    offline = sum(1 for r in rooms if r.get("status") == "Offline")
    return {"rooms": len(rooms), "offline": offline, "items": len(batch),
            "subset": len(subset), "server": result.get("info", result)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="poll repeatedly")
    args = ap.parse_args()

    client = ZoomClient()
    offset = 0
    while True:
        try:
            r = cycle(client, offset)
            offset += SUBSET_SIZE
            print(f"[poll {_now()}] rooms={r['rooms']} offline={r['offline']} "
                  f"subset={r['subset']} items={r['items']} -> {r['server']}", flush=True)
        except Exception as e:  # keep the loop alive on transient errors
            print(f"[poll {_now()}] ERROR: {e}", file=sys.stderr, flush=True)
        if not args.loop:
            break
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
