"""Unit tests for the ensure_* provisioning helpers against stub Zabbix APIs."""
from provision import ensure_items, ensure_trigger, ensure_trigger_dependency


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


class SeqStubAPI:
    """Stub returning queued responses in call order."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        return self.responses.pop(0)


def test_creates_missing_trigger_dependency():
    api = SeqStubAPI([
        [{"triggerid": "7", "dependencies": []}],   # dependent trigger lookup
        [{"triggerid": "3"}],                        # parent trigger lookup
        {"triggerids": ["7"]},                       # trigger.update result
    ])
    ensure_trigger_dependency(api, "200", "Computer disconnected on {HOST.NAME}",
                              "100", "Room {HOST.NAME} is offline")
    assert ("trigger.update",
            {"triggerid": "7", "dependencies": [{"triggerid": "3"}]}) in api.calls


EXPR = "last(/T/k)=0 and nodata(/T/k,30m)=0"


def test_creates_trigger_with_manual_close():
    api = SeqStubAPI([[], {"triggerids": ["7"]}])
    ensure_trigger(api, "D on {HOST.NAME}", EXPR, 3, manual_close=1)
    creates = [p for m, p in api.calls if m == "trigger.create"]
    assert creates == [{"description": "D on {HOST.NAME}", "expression": EXPR,
                        "priority": 3, "manual_close": 1}]


def test_updates_trigger_when_expression_differs():
    api = SeqStubAPI([
        [{"triggerid": "7", "expression": "last(/T/k)=0", "manual_close": "0"}],
        {"triggerids": ["7"]},
    ])
    ensure_trigger(api, "D on {HOST.NAME}", EXPR, 3, manual_close=1)
    assert ("trigger.update", {"triggerid": "7", "expression": EXPR,
                               "manual_close": 1}) in api.calls


def test_leaves_matching_trigger_alone():
    api = SeqStubAPI([[{"triggerid": "7", "expression": EXPR, "manual_close": "1"}]])
    ensure_trigger(api, "D on {HOST.NAME}", EXPR, 3, manual_close=1)
    assert [m for m, _ in api.calls] == ["trigger.get"]


def test_skips_existing_trigger_dependency():
    api = SeqStubAPI([
        [{"triggerid": "7", "dependencies": [{"triggerid": "3"}]}],
        [{"triggerid": "3"}],
    ])
    ensure_trigger_dependency(api, "200", "Computer disconnected on {HOST.NAME}",
                              "100", "Room {HOST.NAME} is offline")
    assert not any(m == "trigger.update" for m, _ in api.calls)
