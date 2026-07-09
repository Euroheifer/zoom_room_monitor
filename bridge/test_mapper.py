"""Unit tests for the pure mapper, against real captured Zoom payloads."""
from mapper import (
    sanitize_host_name,
    parse_tags,
    room_online,
    room_to_values,
    devices_to_values,
    fleet_counts,
)


def test_sanitize_host_name_strips_pipe():
    assert sanitize_host_name("SG-5SPD-2F-Eric Bui | 6898") == "SG-5SPD-2F-Eric Bui 6898"


def test_parse_tags_from_convention():
    tags = parse_tags("SG-5SPD-2F-Eric Bui | 6898")
    assert tags == {"region": "SG", "building": "5SPD", "floor": "2F"}


def test_parse_tags_galaxis():
    tags = parse_tags("SG-Galaxis-15F-Finance09 | 6852")
    assert tags == {"region": "SG", "building": "Galaxis", "floor": "15F"}


def test_parse_tags_unparseable_is_empty():
    assert parse_tags("WeirdName") == {}


def test_room_online_mapping():
    assert room_online("Available") == 1
    assert room_online("InMeeting") == 1
    assert room_online("UnderConstruction") == 1
    assert room_online("Offline") == 0


def test_room_to_values():
    vals = room_to_values({"name": "x", "status": "Offline"})
    assert vals == {"zoom.room.status": "Offline", "zoom.room.online": 0}


def test_devices_to_values_partial_failure():
    # Real offline-room payload: computer Offline, controller Online.
    devices = [
        {"device_type": "Zoom Rooms Computer", "status": "Offline", "app_version": "7.0.0 (7486)"},
        {"device_type": "Controller", "status": "Online", "device_firmware": "2.0.86"},
    ]
    vals = devices_to_values(devices)
    assert vals["zoom.device.computer.status"] == 0
    assert vals["zoom.device.controller.status"] == 1
    assert vals["zoom.device.computer.version"] == "7.0.0 (7486)"
    assert vals["zoom.device.controller.version"] == "2.0.86"


def test_fleet_counts():
    rooms = [
        {"status": "Available"}, {"status": "Available"},
        {"status": "InMeeting"}, {"status": "Offline"},
        {"status": "UnderConstruction"},
    ]
    c = fleet_counts(rooms)
    assert c == {
        "zoom.fleet.total": 5,
        "zoom.fleet.offline": 1,
        "zoom.fleet.online": 4,
        "zoom.fleet.inmeeting": 1,
    }


def test_devices_to_values_healthy():
    devices = [
        {"device_type": "Zoom Rooms Computer", "status": "Online", "app_version": "7.0.0 (7486)"},
        {"device_type": "Controller", "status": "Online", "app_version": "7.0.0 (5186)"},
    ]
    vals = devices_to_values(devices)
    assert vals["zoom.device.computer.status"] == 1
    assert vals["zoom.device.controller.status"] == 1


if __name__ == "__main__":
    import sys
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(funcs)-failed}/{len(funcs)} passed")
    sys.exit(1 if failed else 0)
