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

from zoom_client import ZoomClient
from zabbix_client import send_values
from mapper import sanitize_host_name, room_to_values, devices_to_values

REGION_PREFIX = os.environ.get("REGION_PREFIX", "SG")
SUBSET_SIZE = int(os.environ.get("PERIPHERAL_SUBSET_SIZE", "5"))
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


def choose_subset(rooms, size):
    offline = [r for r in rooms if r.get("status") == "Offline"]
    others = [r for r in rooms if r.get("status") != "Offline"]
    ordered = sorted(offline, key=lambda r: r["name"]) + sorted(others, key=lambda r: r["name"])
    return ordered[:size]


def cycle(client) -> dict:
    rooms = fetch_region_rooms(client)
    batch = []
    for room in rooms:
        host = sanitize_host_name(room["name"])
        for key, value in room_to_values(room).items():
            batch.append({"host": host, "key": key, "value": str(value)})

    # peripheral detail for the subset
    subset = choose_subset(rooms, SUBSET_SIZE)
    for room in subset:
        host = sanitize_host_name(room["name"])
        resp = client.get(f"/rooms/{room['id']}/devices")
        if resp.status_code != 200:
            continue
        devices = resp.json().get("devices", [])
        for key, value in devices_to_values(devices).items():
            batch.append({"host": host, "key": key, "value": str(value)})

    result = send_values(batch)
    offline = sum(1 for r in rooms if r.get("status") == "Offline")
    return {"rooms": len(rooms), "offline": offline, "items": len(batch),
            "subset": len(subset), "server": result.get("info", result)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="poll repeatedly")
    args = ap.parse_args()

    client = ZoomClient()
    while True:
        try:
            r = cycle(client)
            print(f"[poll] rooms={r['rooms']} offline={r['offline']} "
                  f"subset={r['subset']} items={r['items']} -> {r['server']}", flush=True)
        except Exception as e:  # keep the loop alive on transient errors
            print(f"[poll] ERROR: {e}", file=sys.stderr, flush=True)
        if not args.loop:
            break
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
