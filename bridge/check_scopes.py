"""Zoom API scope-verification gate (POC spec, step 1).

Probes the read-only endpoints the POC needs and reports which ones the existing
Zoom app can actually call. Prints a summary table — no secrets, no writes.

Run:  python check_scopes.py
(Reads ZOOM_* credentials from the environment / .env via run_check.sh.)
"""
from __future__ import annotations

import json
import sys

from zoom_client import ZoomClient, ZoomAuthError


def _err_detail(resp) -> str:
    try:
        body = resp.json()
        code = body.get("code")
        msg = body.get("message", "")
        return f"(code {code}) {msg}"[:120]
    except Exception:
        return resp.text[:120]


def probe(client, label, path, params=None, needed=False):
    try:
        r = client.get(path, params=params)
    except Exception as e:  # network etc.
        return {"label": label, "path": path, "ok": False, "status": "ERR",
                "detail": str(e)[:120], "needed": needed, "resp": None}
    ok = r.status_code == 200
    detail = "ok" if ok else _err_detail(r)
    return {"label": label, "path": path, "ok": ok, "status": r.status_code,
            "detail": detail, "needed": needed, "resp": r if ok else None}


def main() -> int:
    try:
        client = ZoomClient()
        # Force a token fetch up front so auth problems surface clearly.
        client.get("/users/me")
    except ZoomAuthError as e:
        print(f"\nAUTH FAILED: {e}\n")
        print("Check ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET and that")
        print("the app is a Server-to-Server OAuth app, activated, on the right account.")
        return 2

    print("\nAuth OK — token acquired.\n")

    results = []

    # Core: list Zoom Rooms + their status -> offline detection (issue type 1)
    rooms_res = probe(client, "List Zoom Rooms (status)", "/rooms",
                      params={"page_size": 30}, needed=True)
    results.append(rooms_res)

    # Grab a sample room id for the room-scoped probes.
    sample_room_id = None
    sample_room_name = None
    if rooms_res["ok"]:
        try:
            rooms = rooms_res["resp"].json().get("rooms", [])
            if rooms:
                sample_room_id = rooms[0].get("id") or rooms[0].get("room_id")
                sample_room_name = rooms[0].get("name") or rooms[0].get("room_name")
        except Exception:
            pass

    # Peripheral/device state per room -> peripheral detection (issue type 2)
    if sample_room_id:
        results.append(probe(client, "Room devices (peripherals)",
                             f"/rooms/{sample_room_id}/devices", needed=True))
        results.append(probe(client, "Room profile/detail",
                             f"/rooms/{sample_room_id}", needed=False))

    # Device Management list (alternative peripheral/firmware source)
    results.append(probe(client, "Device Management list", "/devices",
                         params={"page_size": 5}, needed=False))

    # Dashboard metrics (richer; usually needs Business+ plan & dashboard scope)
    results.append(probe(client, "Dashboard Zoom Rooms", "/metrics/zoomrooms",
                         params={"page_size": 5}, needed=False))

    # Location hierarchy -> region mapping (Phase 1 proper, nice to confirm now)
    results.append(probe(client, "Room location hierarchy", "/rooms/locations",
                         params={"page_size": 5}, needed=False))

    # -- report -------------------------------------------------------------
    print(f"{'NEED':4} {'STATUS':7} {'ENDPOINT':28} DETAIL")
    print("-" * 90)
    for r in results:
        need = "REQ" if r["needed"] else " - "
        mark = "OK " if r["ok"] else "FAIL"
        print(f"{need:4} {mark} {str(r['status']):>3}  {r['label']:28.28} {r['detail']}")

    if sample_room_id:
        print(f"\nSample room: {sample_room_name} (id {sample_room_id})")
        # Show the status field so we can see what offline detection keys off.
        try:
            rooms = rooms_res["resp"].json().get("rooms", [])
            print("First rooms + status:")
            for room in rooms[:8]:
                print(f"  - {room.get('name','?'):35} status={room.get('status','?')}")
        except Exception:
            pass

    required = [r for r in results if r["needed"]]
    missing = [r for r in required if not r["ok"]]
    print("\n" + "=" * 60)
    if not missing:
        print("GATE PASSED: all REQUIRED endpoints for the POC are accessible.")
        return 0
    print("GATE BLOCKED: missing required scopes for:")
    for r in missing:
        print(f"  - {r['label']} [{r['path']}] -> {r['detail']}")
    print("\nAdd the matching scopes to the Server-to-Server OAuth app in the")
    print("Zoom App Marketplace, then re-run this check.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
