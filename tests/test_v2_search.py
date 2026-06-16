"""Unit tests for the v2 two-tool flight search (search_direct_flight +
search_onestop_flight). Regression for tasks 9/20/35: the earlier merged
`search_route` hid the direct/one-stop distinction and dropped per-leg times.
No LLM — the tools are pure functions over the store.
"""
from __future__ import annotations

from src.agents.v2.tools import make_tools
from src.config import DB_PATH
from src.domain.store import Store


def _tools():
    return {t.name: t for t in make_tools(Store.load_from_path(DB_PATH))}


def test_direct_search_returns_full_fields_and_visible_empty():
    tools = _tools()
    # task 9: JFK->MCO has no nonstop on this date — must return [] *visibly*
    # (so the agent/judge can see a direct search was run and found none).
    assert tools["search_direct_flight"].invoke(
        {"origin": "JFK", "destination": "MCO", "date": "2024-05-22"}
    ) == []
    # a route that does have a nonstop: every result carries times + prices + seats
    res = tools["search_direct_flight"].invoke(
        {"origin": "JFK", "destination": "SFO", "date": "2024-05-24"}
    )
    assert res, "expected at least one nonstop JFK->SFO"
    r = res[0]
    assert r["scheduled_departure_time_est"] and r["scheduled_arrival_time_est"]
    assert r["prices"] and r["available_seats"]
    assert r["origin"] == "JFK" and r["destination"] == "SFO" and r["date"] == "2024-05-24"


def test_onestop_search_has_times_and_feasible_connections():
    tools = _tools()
    opts = tools["search_onestop_flight"].invoke(
        {"origin": "JFK", "destination": "MCO", "date": "2024-05-22"}
    )
    assert opts, "expected one-stop options JFK->MCO when no nonstop exists"
    for o in opts:
        leg1, leg2 = o["legs"]
        # task 20: connections must carry departure/arrival times so the agent
        # can filter by e.g. 'depart after 11 AM'.
        for leg in (leg1, leg2):
            assert leg["scheduled_departure_time_est"] and leg["scheduled_arrival_time_est"]
            assert leg["prices"]
        assert leg1["destination"] == leg2["origin"] == o["via"]
        # feasible: on a same-day connection, leg2 departs at/after leg1 arrives
        if leg1["date"] == leg2["date"]:
            arr = leg1["scheduled_arrival_time_est"].replace("+1", "")
            assert leg2["scheduled_departure_time_est"] >= arr
        # combined per-cabin price is provided for cheapest/Nth-cheapest compares
        assert o["prices"] is None or isinstance(o["prices"], dict)


def test_onestop_search_allows_next_day_connection():
    """When leg1 lands after midnight ('+1' arrival), the connecting leg is found
    on the NEXT day — the merged search_route only joined same-date legs."""
    tools = _tools()
    opts = tools["search_onestop_flight"].invoke(
        {"origin": "LGA", "destination": "SFO", "date": "2024-05-20"}
    )
    next_day = [o for o in opts if o["legs"][0]["date"] != o["legs"][1]["date"]]
    assert next_day, "expected a next-day connection (e.g. via PHX on HAT002 +1 arrival)"
    o = next_day[0]
    assert o["legs"][0]["date"] == "2024-05-20"
    assert o["legs"][1]["date"] == "2024-05-21"
    assert "+1" in o["legs"][0]["scheduled_arrival_time_est"]
