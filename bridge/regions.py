"""Region manifest — the one place a region is defined.

Everything is derived from the region name; a row only lists what differs.
Adding a region is one line here, then ./run_onboard.sh <REGION>.
"""

REGIONS = {
    "SG":   {"host_group": "Rooms/Singapore"},          # pre-dates the Rooms/<KEY> convention
    "CNGR": {"webhook_env": "SEATALK_WEBHOOK_URL",      # legacy unsuffixed var name
             "strip_campus_prefix": False},             # campus names carry the city (BJ-JinHui)
    "BR":   {},
}


def region(name):
    """Full config for one region. An unknown name exits loudly rather than
    falling back to a default region — that fallback cost CNGR 3.5h once."""
    if name not in REGIONS:
        raise SystemExit(
            f"unknown region {name!r} — add it to regions.py; known: {' '.join(REGIONS)}")
    r = REGIONS[name]
    return {
        "region_prefix": name,
        "location_root": r.get("location_root", name),
        "host_group": r.get("host_group", f"Rooms/{name}"),
        "fleet_host": r.get("fleet_host", f"{name}-Fleet-Summary"),
        "webhook_env": r.get("webhook_env", f"SEATALK_WEBHOOK_URL_{name}"),
        # SGP-GLX -> GLX; CNGR keeps the city (BJ-JinHui), BR strips (BRA-FLP -> FLP)
        "strip_campus_prefix": r.get("strip_campus_prefix", True),
    }


if __name__ == "__main__":  # must match what the 3 live regions run with today
    assert region("SG")["host_group"] == "Rooms/Singapore"
    assert region("SG")["strip_campus_prefix"] is True
    assert region("CNGR") == {
        "region_prefix": "CNGR", "location_root": "CNGR", "host_group": "Rooms/CNGR",
        "fleet_host": "CNGR-Fleet-Summary", "webhook_env": "SEATALK_WEBHOOK_URL",
        "strip_campus_prefix": False}
    assert region("BR") == {
        "region_prefix": "BR", "location_root": "BR", "host_group": "Rooms/BR",
        "fleet_host": "BR-Fleet-Summary", "webhook_env": "SEATALK_WEBHOOK_URL_BR",
        "strip_campus_prefix": True}
    try:
        region("XX")
    except SystemExit as e:
        assert "known: SG CNGR BR" in str(e)
    else:
        raise AssertionError("unknown region must exit")
    print("ok")
