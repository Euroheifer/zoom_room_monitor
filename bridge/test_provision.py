"""Unit tests for ensure_items against a stub Zabbix API."""
from provision import ensure_items


class StubAPI:
    def __init__(self, existing_items):
        self.existing = existing_items
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "item.get":
            return self.existing
        return {}


SPECS = [("zoom.room.online", "Room online (1/0)", 3)]


def test_creates_missing_item_with_history():
    api = StubAPI([])
    ensure_items(api, "100", SPECS)
    creates = [p for m, p in api.calls if m == "item.create"]
    assert len(creates) == 1
    assert creates[0]["history"] == "90d"
    assert creates[0]["key_"] == "zoom.room.online"


def test_updates_retention_on_existing_item():
    api = StubAPI([{"itemid": "42", "key_": "zoom.room.online", "history": "31d"}])
    ensure_items(api, "100", SPECS)
    assert ("item.update", {"itemid": "42", "history": "90d"}) in api.calls
    assert not any(m == "item.create" for m, _ in api.calls)


def test_leaves_correct_item_alone():
    api = StubAPI([{"itemid": "42", "key_": "zoom.room.online", "history": "90d"}])
    ensure_items(api, "100", SPECS)
    assert [m for m, _ in api.calls] == ["item.get"]
