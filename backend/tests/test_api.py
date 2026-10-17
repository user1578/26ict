import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
KEY = {"X-Tool-Key": "local-test-key"}

ACTIVITY = {
    "id": "a01",
    "poi_id": "WH01",
    "start_at": "2026-11-18T14:00:00+08:00",
    "end_at": "2026-11-18T15:00:00+08:00",
    "opening_status": "confirmed_open",
}


@pytest.fixture(autouse=True)
def tool_key(monkeypatch):
    monkeypatch.setenv("TRAVELGUARD_TOOL_API_KEY", "local-test-key")


def post_budget(body):
    return client.post("/api/tools/calculate-budget", headers=KEY, json=body)


def post_plan(body):
    return client.post("/api/tools/validate-plan", headers=KEY, json=body)


def check(result, name):
    return next(x for x in result.json()["checks"] if x["name"] == name)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_tools_require_key():
    assert client.post("/api/tools/calculate-budget", json={"budget_cny": 10}).status_code == 401


def test_no_key_configured(monkeypatch):
    monkeypatch.delenv("TRAVELGUARD_TOOL_API_KEY")
    assert client.post("/api/tools/calculate-budget", headers=KEY, json={"budget_cny": 10}).status_code == 503


def test_pending_refund_is_not_available():
    r = post_budget({
        "budget_cny": "200.00",
        "charges": [{"id": "ticket", "amount_cny": "120.00", "status": "paid"},
                    {"id": "replacement", "amount_cny": "135.00", "status": "planned"}],
        "refunds": [{"id": "ticket-refund", "amount_cny": "120.00", "status": "pending"}],
    })
    assert r.status_code == 200
    assert r.json()["conservative_total_cny"] == "255.00"
    assert r.json()["pending_refunds_cny"] == "120.00"
    assert r.json()["within_budget"] is False


def test_received_refund_can_offset():
    r = post_budget({
        "budget_cny": "200.00",
        "charges": [{"id": "ticket", "amount_cny": "120.00", "status": "paid"}],
        "refunds": [{"id": "return", "amount_cny": "120.00", "status": "received"}],
    })
    assert r.status_code == 200
    assert r.json()["remaining_cny"] == "200.00"


def test_duplicate_expense_rejected():
    r = post_budget({
        "budget_cny": 200,
        "charges": [{"id": "x", "amount_cny": 50, "status": "paid"},
                    {"id": "x", "amount_cny": 50, "status": "planned"}],
    })
    assert r.status_code == 422


def test_unbacked_refund_rejected():
    r = post_budget({
        "budget_cny": 300,
        "refunds": [{"id": "r", "amount_cny": 500, "status": "received"}],
    })
    assert r.status_code == 422


def test_validate_unknown_opening_not_pass():
    r = post_plan({"activities": [{**ACTIVITY, "opening_status": "unknown"}]})
    assert r.status_code == 200
    assert r.json()["overall"] == "UNKNOWN"


def test_validate_overlapping_activities_fail():
    second = {**ACTIVITY, "id": "a02", "start_at": "2026-11-18T14:30:00+08:00",
              "end_at": "2026-11-18T15:30:00+08:00", "transport_minutes_from_previous": 20}
    r = post_plan({"activities": [ACTIVITY, second], "budget": {"budget_cny": 300}})
    assert r.json()["overall"] == "FAIL"
    assert check(r, "time_check")["status"] == "FAIL"


def test_locked_activity_cannot_be_changed():
    changed = {**ACTIVITY, "end_at": "2026-11-18T15:30:00+08:00"}
    r = post_plan({"activities": [changed], "locked_activities": [ACTIVITY],
                   "budget": {"budget_cny": 300}})
    assert check(r, "state_check")["status"] == "FAIL"


def test_return_deadline():
    r = post_plan({
        "activities": [ACTIVITY],
        "budget": {"budget_cny": 300},
        "return_deadline": "2026-11-18T17:00:00+08:00",
        "arrival_at_return_station": "2026-11-18T17:30:00+08:00",
    })
    assert check(r, "return_check")["status"] == "FAIL"


def test_unconfirmed_booking_cannot_pass():
    r = post_plan({
        "activities": [{**ACTIVITY, "booking_required": True, "booking_status": "not_confirmed"}],
        "budget": {"budget_cny": 300},
    })
    assert check(r, "booking_check")["status"] == "FAIL"


def test_closed_place_blocks_plan():
    r = post_plan({
        "activities": [{**ACTIVITY, "opening_status": "confirmed_closed"}],
        "budget": {"budget_cny": 300},
    })
    assert r.json()["overall"] == "FAIL"


def test_first_activity_does_not_need_previous_walking_leg():
    r = post_plan({
        "activities": [ACTIVITY],
        "budget": {"budget_cny": 300},
        "max_walking_minutes_per_leg": 20,
    })
    assert check(r, "walking_check")["status"] == "PASS"


def test_walking_limit_fails_on_excessive_leg():
    second = {
        **ACTIVITY, "id": "a02", "start_at": "2026-11-18T16:00:00+08:00",
        "end_at": "2026-11-18T17:00:00+08:00",
        "transport_minutes_from_previous": 25,
        "walking_minutes_from_previous": 25,
    }
    r = post_plan({
        "activities": [ACTIVITY, second],
        "budget": {"budget_cny": 300},
        "max_walking_minutes_per_leg": 20,
    })
    assert check(r, "walking_check")["status"] == "FAIL"


def test_unknown_transport_keeps_overall_unknown():
    second = {
        **ACTIVITY, "id": "a02", "start_at": "2026-11-18T16:00:00+08:00",
        "end_at": "2026-11-18T17:00:00+08:00",
        "transport_minutes_from_previous": None,
    }
    r = post_plan({"activities": [ACTIVITY, second], "budget": {"budget_cny": 300}})
    assert check(r, "time_check")["status"] == "UNKNOWN"


def test_naive_datetime_is_rejected():
    r = post_plan({"activities": [{**ACTIVITY, "start_at": "2026-11-18T14:00:00"}]})
    assert r.status_code == 422


def test_duplicate_activity_ids_are_rejected():
    r = post_plan({"activities": [ACTIVITY, ACTIVITY]})
    assert r.status_code == 422
