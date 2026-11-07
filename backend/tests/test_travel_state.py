"""Business regression tests use isolated SQLite files and the public HTTP API."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


KEY = {"X-Tool-Key": "state-test-key"}
ROOT = "/api/trips/wuhan"


def plan():
    return {
        "activities": [
            {"id": "train", "poi_id": "wuhan-station",
             "start_at": "2026-11-18T09:00:00+08:00", "end_at": "2026-11-18T10:00:00+08:00",
             "opening_status": "confirmed_open"},
            {"id": "tower", "poi_id": "yellow-crane-tower",
             "start_at": "2026-11-18T14:00:00+08:00", "end_at": "2026-11-18T15:00:00+08:00",
             "transport_minutes_from_previous": 30, "walking_minutes_from_previous": 10,
             "opening_status": "confirmed_open"},
            {"id": "museum", "poi_id": "hubei-museum",
             "start_at": "2026-11-19T10:00:00+08:00", "end_at": "2026-11-19T11:00:00+08:00",
             "transport_minutes_from_previous": 30, "walking_minutes_from_previous": 10,
             "opening_status": "confirmed_open"},
        ],
        "charges": [{"id": "train-ticket", "amount_cny": "100.00", "status": "paid"},
                    {"id": "tower-ticket", "amount_cny": "70.00", "status": "planned"}],
        "refunds": [],
        "activity_evidence": {"train": "simulation:station", "tower": "simulation:tower",
                              "museum": "simulation:museum"},
        "financial_evidence": {"train-ticket": "simulation:paid-ticket"},
        "arrival_at_return_station": "2026-11-19T16:00:00+08:00",
    }


def create(client, **changes):
    body = {"request_id": "create-1", "trip_id": "wuhan", "title": "武汉两日游",
            "budget_cny": "300.00", "max_walking_minutes_per_leg": 20,
            "return_deadline": "2026-11-19T17:00:00+08:00", "plan": plan()}
    body.update(changes)
    return client.post("/api/trips", headers=KEY, json=body)


def event(client, event_id="E1", revision=0, **changes):
    body = {"request_id": f"event-{event_id}-{revision}", "expected_event_revision": revision,
            "kind": "train_delay", "activity_id": "train",
            "earliest_start_at": "2026-11-18T11:00:00+08:00", "source": "simulation",
            "evidence_ref": f"simulation:{event_id}", "verification_status": "verified"}
    body.update(changes)
    return client.put(f"{ROOT}/events/{event_id}", headers=KEY, json=body)


def delayed_plan():
    result = plan()
    result["activities"][0].update(start_at="2026-11-18T11:00:00+08:00",
                                   end_at="2026-11-18T12:00:00+08:00")
    return result


def draft(client, draft_id="D1", revision=1, base_version=1, history_revision=0,
          candidate=None, handled_event_ids=None):
    return client.post(f"{ROOT}/drafts", headers=KEY, json={
        "request_id": f"draft-{draft_id}", "draft_id": draft_id,
        "base_version": base_version, "event_revision": revision,
        "history_revision": history_revision,
        "handled_event_ids": ["E1"] if handled_event_ids is None else handled_event_ids,
        "plan": delayed_plan() if candidate is None else candidate,
    })


def confirm(client, draft_id="D1", revision=1, request_id="confirm-1", **changes):
    body = {"request_id": request_id, "base_version": 1, "event_revision": revision,
            "history_revision": 0, "user_confirmed": True, "confirmed_by": "local-user"}
    body.update(changes)
    return client.post(f"{ROOT}/drafts/{draft_id}/confirm", headers=KEY, json=body)


@pytest.fixture
def database(tmp_path):
    return tmp_path / "travel.local.sqlite3"


@pytest.fixture
def client(database, monkeypatch):
    monkeypatch.setenv("TRAVELGUARD_TOOL_API_KEY", KEY["X-Tool-Key"])
    monkeypatch.setenv("TRAVELGUARD_DB_PATH", str(database))
    with TestClient(app) as client:
        yield client


def setup_draft(client):
    assert create(client).status_code == 201
    assert event(client).status_code == 200
    result = draft(client)
    assert result.status_code == 201, result.text
    return result.json()


def test_create_is_idempotent_and_preserves_initial_version(client):
    first = create(client)
    assert first.status_code == 201, first.text
    assert create(client).json() == first.json()
    assert create(client, title="changed").status_code == 409
    assert len(client.get(f"{ROOT}/versions", headers=KEY).json()) == 1
    assert client.get(ROOT, headers=KEY).json()["current_plan"]["budget"]["paid_cny"] == "100.00"


def test_new_event_stales_draft_without_changing_formal_plan(client):
    assert setup_draft(client)["validation"]["overall"] == "PASS"
    assert event(client, "E2", 1, kind="poi_closed", activity_id=None, earliest_start_at=None,
                 poi_id="yellow-crane-tower", effective_at="2026-11-18T13:00:00+08:00").status_code == 200
    assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "stale"
    assert confirm(client).status_code == 409
    current = client.get(ROOT, headers=KEY).json()
    assert current["current_version"] == 1
    assert current["current_plan"]["plan"]["activities"][0]["start_at"] == "2026-11-18T09:00:00+08:00"


def test_updated_and_resolved_events_stale_candidates_but_retries_do_not(client):
    setup_draft(client)
    # Exact retry, including the old expected revision, replays its receipt.
    assert event(client).status_code == 200
    assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "pending"
    assert event(client, revision=1, active=False).status_code == 200
    assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "stale"
    assert client.get(ROOT, headers=KEY).json()["event_revision"] == 2


def test_candidate_requires_current_versions_and_all_active_events(client):
    setup_draft(client)
    assert draft(client, "bad-base", base_version=2).status_code == 409
    assert draft(client, "bad-revision", revision=0).status_code == 409
    assert draft(client, "missing-event", handled_event_ids=[]).status_code == 409
    assert event(client, "E2", revision=0).status_code == 409


@pytest.mark.parametrize("change, expected", [
    ("unknown-opening", "UNKNOWN"), ("missing-evidence", "UNKNOWN"),
    ("over-budget", "FAIL"), ("walking", "FAIL"), ("late-return", "FAIL"),
    ("unconfirmed-booking", "FAIL"), ("ignored-delay", "FAIL"),
    ("invented-booking", "FAIL"),
    ("new-payment", "FAIL"), ("lost-payment", "FAIL"), ("invented-refund", "FAIL"),
])
def test_confirmation_rechecks_constraints_and_financial_facts(client, change, expected):
    assert create(client).status_code == 201
    assert event(client).status_code == 200
    candidate = delayed_plan()
    if change == "unknown-opening":
        candidate["activities"][1]["opening_status"] = "unknown"
    elif change == "missing-evidence":
        candidate["activity_evidence"].pop("tower")
    elif change == "over-budget":
        candidate["charges"][1]["amount_cny"] = "250.00"
    elif change == "walking":
        candidate["activities"][1]["walking_minutes_from_previous"] = 30
    elif change == "late-return":
        candidate["arrival_at_return_station"] = "2026-11-19T18:00:00+08:00"
    elif change == "unconfirmed-booking":
        candidate["activities"][1].update(booking_required=True, booking_status="not_confirmed")
    elif change == "invented-booking":
        candidate["activities"][1].update(booking_required=True, booking_status="confirmed")
    elif change == "ignored-delay":
        candidate = plan()
    elif change == "new-payment":
        candidate["charges"][1]["status"] = "paid"
        candidate["financial_evidence"]["tower-ticket"] = "claimed-payment"
    elif change == "lost-payment":
        candidate["charges"].pop(0)
        candidate["financial_evidence"].pop("train-ticket")
    elif change == "invented-refund":
        candidate["refunds"] = [{"id": "refund", "status": "received", "amount_cny": "70.00"}]
        candidate["financial_evidence"]["refund"] = "claimed-refund"
    result = draft(client, candidate=candidate)
    assert result.status_code == 201, result.text
    assert result.json()["validation"]["overall"] == expected
    rejected = confirm(client)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["validation"]["overall"] == expected
    assert client.get(ROOT, headers=KEY).json()["current_version"] == 1
    assert len(client.get(f"{ROOT}/versions", headers=KEY).json()) == 1


def test_unverified_event_and_closed_poi_cannot_pass(client):
    assert create(client).status_code == 201
    assert event(client, verification_status="unverified").status_code == 200
    assert draft(client).json()["validation"]["overall"] == "UNKNOWN"
    assert confirm(client).status_code == 422
    assert event(client, "E2", 1, kind="poi_closed", activity_id=None, earliest_start_at=None,
                 poi_id="yellow-crane-tower", effective_at="2026-11-18T13:00:00+08:00").status_code == 200
    result = draft(client, "closed", revision=2, handled_event_ids=["E1", "E2"])
    assert result.json()["validation"]["overall"] == "FAIL"


def test_rescheduling_a_booked_activity_cannot_imply_rescheduling_the_booking(client):
    initial = plan()
    initial["activities"][1].update(booking_required=True, booking_status="confirmed")
    assert create(client, plan=initial).status_code == 201
    assert event(client).status_code == 200
    candidate = delayed_plan()
    candidate["activities"][1].update(booking_required=True, booking_status="confirmed")
    assert draft(client, "unchanged-booking", candidate=candidate).json()["validation"]["overall"] == "PASS"
    candidate["activities"][1].update(start_at="2026-11-18T15:00:00+08:00",
                                       end_at="2026-11-18T16:00:00+08:00")
    result = draft(client, "moved-booking", candidate=candidate)
    assert result.json()["validation"]["overall"] == "FAIL"
    assert confirm(client, "moved-booking").status_code == 422


def test_known_booking_requirement_survives_omitting_and_readding_visit(client):
    initial = plan()
    initial["activities"][1].update(booking_required=True, booking_status="confirmed")
    assert create(client, plan=initial).status_code == 201
    assert event(client).status_code == 200
    omitted = delayed_plan()
    omitted["activities"].pop(1)
    omitted["activity_evidence"].pop("tower")
    assert draft(client, candidate=omitted).json()["validation"]["overall"] == "PASS"
    assert confirm(client).status_code == 200
    readded = draft(client, "readded", base_version=2, candidate=delayed_plan())
    assert readded.status_code == 201
    assert readded.json()["validation"]["overall"] == "FAIL"


@pytest.mark.parametrize("required,status", [(False, "confirmed"), (True, "unknown")])
def test_booking_facts_cannot_be_bypassed_by_clearing_requirement(client, required, status):
    initial = plan()
    initial["activities"][1].update(booking_required=True, booking_status="confirmed")
    assert create(client, plan=initial).status_code == 201
    assert event(client).status_code == 200
    candidate = delayed_plan()
    candidate["activities"][1].update(booking_required=required, booking_status=status,
                                       start_at="2026-11-18T15:00:00+08:00",
                                       end_at="2026-11-18T16:00:00+08:00")
    result = draft(client, candidate=candidate)
    assert result.json()["validation"]["overall"] == ("FAIL" if not required else "UNKNOWN")
    assert confirm(client).status_code == 422


def test_confirmation_requires_explicit_user_consent_and_matching_tokens(client):
    setup_draft(client)
    assert confirm(client, user_confirmed=False).status_code == 422
    assert confirm(client, base_version=2).status_code == 409
    assert confirm(client, revision=0).status_code == 409
    assert confirm(client, history_revision=1).status_code == 409
    assert client.get(ROOT, headers=KEY).json()["current_version"] == 1


def test_numeric_truthiness_is_not_explicit_user_confirmation(client):
    setup_draft(client)
    assert confirm(client, user_confirmed=1).status_code == 422
    assert client.get(ROOT, headers=KEY).json()["current_version"] == 1


def test_active_event_update_invalidates_draft_and_new_draft_uses_new_fact(client):
    setup_draft(client)
    changed = event(client, revision=1, earliest_start_at="2026-11-18T13:00:00+08:00")
    assert changed.status_code == 200
    assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "stale"
    result = draft(client, "updated-event", revision=2)
    assert result.json()["validation"]["overall"] == "FAIL"
    assert confirm(client, "updated-event", revision=2).status_code == 422


def test_concurrent_repeated_confirmation_returns_the_same_version(client):
    setup_draft(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: confirm(client), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert len(client.get(f"{ROOT}/versions", headers=KEY).json()) == 2


def test_repeated_confirmation_does_not_duplicate_versions_or_expenses(client):
    setup_draft(client)
    first = confirm(client)
    assert first.status_code == 200, first.text
    assert confirm(client).json() == first.json()
    assert confirm(client, request_id="second-click").json() == first.json()
    assert confirm(client, confirmed_by="changed-user").status_code == 409
    versions = client.get(f"{ROOT}/versions", headers=KEY).json()
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[1]["budget"]["conservative_total_cny"] == "170.00"
    assert versions[1]["confirmation"]["confirmed_by"] == "local-user"


def test_competing_confirmations_have_one_winner(client):
    setup_draft(client)
    assert draft(client, "competing").status_code == 201
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: confirm(client, pair[0], request_id=pair[1]),
                                [("D1", "one"), ("competing", "two")]))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert len(client.get(f"{ROOT}/versions", headers=KEY).json()) == 2


def test_history_locks_are_persistent_and_invalidate_drafts(client):
    setup_draft(client)
    lock = {"request_id": "lock-1", "base_version": 1, "history_revision": 0,
            "activity_ids": ["museum"]}
    assert client.post(f"{ROOT}/locks", headers=KEY, json=lock).status_code == 200
    assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "stale"
    candidate = delayed_plan()
    candidate["activities"][2]["end_at"] = "2026-11-19T11:30:00+08:00"
    result = draft(client, "changed-history", history_revision=1, candidate=candidate)
    assert result.json()["validation"]["overall"] == "FAIL"
    assert confirm(client, "changed-history", history_revision=1).status_code == 422
    assert client.get(ROOT, headers=KEY).json()["locked_activity_ids"] == ["museum"]


def test_sqlite_failure_rolls_back_version_pointer_draft_and_receipt(client, database):
    setup_draft(client)
    # Inject a real SQLite failure after the version insert, without mocking the transaction.
    with sqlite3.connect(database) as db:
        db.execute("CREATE TRIGGER reject_pointer BEFORE UPDATE OF current_version ON trips "
                   "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with TestClient(app, raise_server_exceptions=False) as failing:
        assert confirm(failing).status_code == 500
    assert client.get(ROOT, headers=KEY).json()["current_version"] == 1
    assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "pending"
    assert len(client.get(f"{ROOT}/versions", headers=KEY).json()) == 1
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER reject_pointer")
    assert confirm(client).status_code == 200
    assert len(client.get(f"{ROOT}/versions", headers=KEY).json()) == 2


def test_new_endpoints_are_authenticated_and_reject_malformed_input(client):
    assert client.get(ROOT).status_code == 401
    assert client.get(ROOT, headers=KEY).status_code == 404
    assert create(client).status_code == 201
    assert event(client, earliest_start_at="2026-11-18T11:00:00").status_code == 422
    assert event(client, evidence_ref="   ").status_code == 422
    assert draft(client, candidate={**plan(), "budget_cny": 99999}).status_code == 422
    candidate = plan()
    candidate["charges"].append(deepcopy(candidate["charges"][0]))
    assert draft(client, candidate=candidate).status_code == 422


def test_resource_identifiers_cannot_create_unaddressable_records(client):
    assert create(client, trip_id="a/b").status_code == 422
    assert create(client).status_code == 201
    assert event(client, " E1 ", request_id="space-event").status_code == 422
    assert event(client).status_code == 200
    assert draft(client, "D/1").status_code == 422


def test_receipt_failure_rolls_back_the_entire_confirmation(client, database):
    setup_draft(client)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON requests "
                   "WHEN NEW.request_id='confirm-1' BEGIN SELECT RAISE(ABORT, 'receipt failure'); END")
    with TestClient(app, raise_server_exceptions=False) as failing:
        assert confirm(failing).status_code == 500
    assert client.get(ROOT, headers=KEY).json()["current_version"] == 1
    assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "pending"
    assert len(client.get(f"{ROOT}/versions", headers=KEY).json()) == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM requests WHERE request_id='confirm-1'").fetchone()[0] == 0
        db.execute("DROP TRIGGER reject_receipt")
    assert confirm(client).status_code == 200
    assert confirm(client).status_code == 200
    assert len(client.get(f"{ROOT}/versions", headers=KEY).json()) == 2


def test_event_racing_confirmation_cannot_commit_an_unhandled_event(client):
    setup_draft(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        confirmation = pool.submit(confirm, client)
        updated = pool.submit(event, client, "E2", 1, kind="poi_closed", activity_id=None,
                              earliest_start_at=None, poi_id="yellow-crane-tower",
                              effective_at="2026-11-18T13:00:00+08:00")
        committed, changed = confirmation.result(), updated.result()
    assert changed.status_code == 200
    state = client.get(ROOT, headers=KEY).json()
    assert state["event_revision"] == 2
    if committed.status_code == 200:
        assert state["current_version"] == 2
        assert committed.json()["event_revision"] == 1  # committed before E2; E2 remains active
    else:
        assert committed.status_code == 409
        assert state["current_version"] == 1
        assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "stale"
    assert {e["event_id"] for e in state["events"] if e["active"]} == {"E1", "E2"}


def test_snapshot_preserves_paid_history_and_pending_refunds_across_versions(client):
    setup_draft(client)
    candidate = delayed_plan()
    candidate["refunds"] = [{"id": "pending", "amount_cny": "80.00", "status": "pending"}]
    assert draft(client, "with-refund", candidate=candidate).status_code == 201
    first = confirm(client, "with-refund").json()
    assert first["budget"]["conservative_total_cny"] == "170.00"
    assert first["budget"]["pending_refunds_cny"] == "80.00"
    assert draft(client, "next", base_version=2, candidate=candidate).status_code == 201
    second = confirm(client, "next", base_version=2, request_id="confirm-next").json()
    assert second["version"] == 3
    assert second["budget"] == first["budget"]
    assert second["budget"]["paid_cny"] == "100.00"
    changed = deepcopy(candidate)
    changed["charges"][0]["status"] = "planned"
    r = draft(client, "hide-paid", base_version=3, candidate=changed)
    assert r.json()["validation"]["overall"] == "FAIL"
    assert confirm(client, "hide-paid", base_version=3, request_id="cannot-hide-paid").status_code == 422


def workflow(client, **trip_changes):
    assert create(client, locked_activity_ids=["museum"], **trip_changes).status_code == 201
    assert event(client).status_code == 200
    assert draft(client).json()["validation"]["overall"] == "PASS"
    assert event(client, "E2", 1, kind="poi_closed", activity_id=None, earliest_start_at=None,
                 poi_id="yellow-crane-tower", effective_at="2026-11-18T13:00:00+08:00").status_code == 200
    assert client.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "stale"
    assert confirm(client).status_code == 409
    replacement = delayed_plan()
    replacement["activities"][1]["poi_id"] = "east-lake"
    replacement["activity_evidence"]["tower"] = "simulation:east-lake-open"
    replacement["charges"][1] = {"id": "lake-transport", "amount_cny": "50.00", "status": "planned"}
    replacement["refunds"] = [{"id": "pending-refund", "amount_cny": "20.00", "status": "pending"}]
    d2 = draft(client, "D2", revision=2, candidate=replacement, handled_event_ids=["E1", "E2"])
    assert d2.status_code == 201, d2.text
    assert d2.json()["validation"]["overall"] == "PASS"
    result = confirm(client, "D2", revision=2, request_id="confirm-d2")
    assert result.status_code == 200, result.text
    assert confirm(client, "D2", revision=2, request_id="confirm-d2").json() == result.json()
    state = client.get(ROOT, headers=KEY).json()
    assert state["current_version"] == 2
    assert state["locked_activity_ids"] == ["museum"]
    assert state["current_plan"]["budget"]["conservative_total_cny"] == "150.00"
    assert state["current_plan"]["budget"]["received_refunds_cny"] == "0.00"
    assert state["current_plan"]["budget"]["pending_refunds_cny"] == "20.00"
    return state


@pytest.mark.parametrize("trip_changes", [{}, {
    "city": "武汉", "party_size": 3, "start_date": "2026-11-18", "end_date": "2026-11-19",
    "preferences": {"stay_together": True},
}], ids=["legacy", "complete-basics"])
def test_real_http_workflow_and_service_restart(database, monkeypatch, trip_changes):
    """Start the actual ASGI server twice; no TestClient transport in this acceptance case."""
    monkeypatch.setenv("TRAVELGUARD_DB_PATH", str(database))
    monkeypatch.setenv("TRAVELGUARD_TOOL_API_KEY", KEY["X-Tool-Key"])
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    previous = None
    for run in range(2):
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=Path(__file__).resolve().parents[1], env=os.environ.copy(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=url, timeout=3, trust_env=False) as http:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        if http.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if process.poll() is not None or time.monotonic() > deadline:
                        pytest.fail("Uvicorn failed to start")
                    time.sleep(0.05)
                if run == 0:
                    previous = workflow(http, **trip_changes)
                    for key, value in trip_changes.items():
                        assert previous[key] == value
                else:
                    assert http.get(ROOT, headers=KEY).json() == previous
                    assert http.get(f"{ROOT}/drafts/D1", headers=KEY).json()["status"] == "stale"
                    assert len(http.get(f"{ROOT}/versions", headers=KEY).json()) == 2
                    assert confirm(http, "D2", revision=2, request_id="confirm-d2").status_code == 200
        finally:
            process.terminate()
            process.communicate(timeout=10)
