"""Pure mapping functions: Zoom payloads -> Zabbix host names, tags, and item
key/value pairs. No I/O here, so this is unit-testable against sample payloads.
"""
from __future__ import annotations

import re

# A room counts as "online" unless Zoom explicitly reports it Offline.
# UnderConstruction = being set up, not an incident -> treated as online.
OFFLINE_STATUSES = {"Offline"}

# Zabbix technical host names disallow some characters (e.g. "|"). Keep letters,
# digits, space, dot, dash, underscore; collapse the rest to a single dash.
_HOSTNAME_BAD = re.compile(r"[^A-Za-z0-9 ._-]+")
_MULTISPACE = re.compile(r"\s+")

# Room name convention: SG-{building}-{floor}-{room} | {number}
_NAME_RE = re.compile(r"^(?P<region>[A-Za-z]+)-(?P<building>[^-]+)-(?P<floor>[^-]+)-")


def sanitize_host_name(room_name: str) -> str:
    """Map a Zoom room name to a valid, stable Zabbix technical host name."""
    cleaned = _HOSTNAME_BAD.sub(" ", room_name)
    return _MULTISPACE.sub(" ", cleaned).strip()


def parse_tags(room_name: str) -> dict[str, str]:
    """Derive region/building/floor tags from the naming convention.

    Falls back gracefully: anything not parseable just isn't tagged.
    """
    tags: dict[str, str] = {}
    m = _NAME_RE.match(room_name)
    if m:
        tags["region"] = m.group("region").upper()
        tags["building"] = m.group("building").strip()
        tags["floor"] = m.group("floor").strip()
    return tags


def room_online(status: str) -> int:
    return 0 if status in OFFLINE_STATUSES else 1


def room_to_values(room: dict) -> dict[str, object]:
    """Per-room trapper values from a /rooms list entry."""
    status = room.get("status", "Unknown")
    return {
        "zoom.room.status": status,
        "zoom.room.online": room_online(status),
    }


def fleet_counts(rooms: list[dict]) -> dict[str, int]:
    """Fleet-level rollup counts for the summary host / headline stats."""
    from collections import Counter
    c = Counter(r.get("status", "Unknown") for r in rooms)
    total = len(rooms)
    offline = c.get("Offline", 0)
    return {
        "zoom.fleet.total": total,
        "zoom.fleet.offline": offline,
        "zoom.fleet.online": total - offline,
        "zoom.fleet.inmeeting": c.get("InMeeting", 0),
    }


def _device_online(status: str) -> int:
    return 1 if str(status).lower() == "online" else 0


def devices_to_values(devices: list[dict]) -> dict[str, object]:
    """Per-device trapper values from a /rooms/{id}/devices response.

    Collapses devices by role. If multiple devices share a role, the worst
    (offline) status wins so a disconnect is never masked.
    """
    values: dict[str, object] = {}
    roles = {
        "Zoom Rooms Computer": "computer",
        "Controller": "controller",
    }
    for dev in devices:
        role = roles.get(dev.get("device_type", ""))
        if not role:
            continue
        online = _device_online(dev.get("status", ""))
        key = f"zoom.device.{role}.status"
        # worst-status-wins if duplicate roles
        if key in values:
            values[key] = min(values[key], online)  # type: ignore[type-var]
        else:
            values[key] = online
        # app/firmware are informational text items (last one wins)
        ver = dev.get("app_version") or dev.get("device_firmware") or ""
        if ver:
            values[f"zoom.device.{role}.version"] = ver
    return values
