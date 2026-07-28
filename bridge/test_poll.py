"""Unit tests for the poller's rotating device-subset selection."""
from poll import choose_subset


def _rooms(n_online, n_offline):
    rooms = [{"name": f"SG-A-{i:02d}", "status": "Available"} for i in range(n_online)]
    rooms += [{"name": f"SG-Z-{i:02d}", "status": "Offline"} for i in range(n_offline)]
    return rooms


def test_only_online_rooms_are_picked():
    subset = choose_subset(_rooms(3, 5), size=10, offset=0)
    assert len(subset) == 3
    assert all(r["status"] != "Offline" for r in subset)


def test_rotation_sweeps_whole_online_fleet():
    rooms = _rooms(13, 2)
    seen = set()
    for cycle_no in range(3):  # 3 cycles x 5 = 15 slots > 13 online rooms
        for r in choose_subset(rooms, size=5, offset=cycle_no * 5):
            seen.add(r["name"])
    assert len(seen) == 13


def test_rotation_wraps_around():
    rooms = _rooms(4, 0)
    subset = choose_subset(rooms, size=3, offset=3)
    assert [r["name"] for r in subset] == ["SG-A-03", "SG-A-00", "SG-A-01"]


def test_no_online_rooms_gives_empty_subset():
    assert choose_subset(_rooms(0, 4), size=5, offset=7) == []
