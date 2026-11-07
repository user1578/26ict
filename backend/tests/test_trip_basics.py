"""Trip metadata and migration contracts, using temporary databases only."""

from copy import deepcopy
from hashlib import sha256
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.travel_schemas import TravelPlan
from app.travel_store import TravelStore
from test_travel_state import KEY, ROOT, client, create, database, plan


BASICS = {
    "city": "武汉", "party_size": 3,
    "start_date": "2026-11-18", "end_date": "2026-11-19",
    "preferences": {"stay_together": True},
}
UNKNOWN_BASICS = {
    "city": None, "party_size": None, "start_date": None, "end_date": None,
    "preferences": {"stay_together": None},
}


@pytest.mark.parametrize("stay_together", [True, False])
def test_create_and_get_preserve_basics_and_separate_preferences(client, stay_together):
    basics = {**BASICS, "preferences": {"stay_together": stay_together}}
    response = create(client, **{**basics, "city": "  武汉\t"})
    assert response.status_code == 201, response.text
    for state in [response.json(), client.get(ROOT, headers=KEY).json()]:
        assert {key: state[key] for key in basics} == basics
        assert state["constraints"] == {
            "budget_cny": "300.00", "max_walking_minutes_per_leg": 20,
            "return_deadline": "2026-11-19T17:00:00+08:00",
        }
        assert state["current_plan"]["validation"]["overall"] == "PASS"
        assert all("together" not in check["name"]
                   for check in state["current_plan"]["validation"]["checks"])
    assert create(client, **basics).json() == response.json()
    changed = {**basics, "preferences": {"stay_together": not stay_together}}
    assert create(client, **changed).status_code == 409


@pytest.mark.parametrize("changes", [
    {"city": ""}, {"city": " \t\n\u3000"}, {"city": 123},
    {"party_size": 0}, {"party_size": -1}, {"party_size": 11},
    {"party_size": 1.5}, {"party_size": 3.0}, {"party_size": True}, {"party_size": "3"},
    {"start_date": "2026-02-30"}, {"end_date": "2026-13-01"},
    {"start_date": "2026-2-01"}, {"end_date": "20261119"},
    {"start_date": "2026-11-18T00:00:00+08:00"}, {"start_date": 1794960000},
    {"start_date": ""}, {"end_date": " 2026-11-19"},
    {"end_date": "2026-11-17"},
    {"preferences": {"stay_together": "true"}}, {"preferences": {"stay_together": 1}},
])
def test_invalid_basics_are_rejected_without_creating_trip(client, changes):
    response = create(client, **{**BASICS, **changes})
    assert response.status_code == 422, response.text
    assert client.get(ROOT, headers=KEY).status_code == 404


@pytest.mark.parametrize("changes, expected", [
    ({}, UNKNOWN_BASICS),
    (UNKNOWN_BASICS, UNKNOWN_BASICS),
    ({"city": "武汉"}, {**UNKNOWN_BASICS, "city": "武汉"}),
    ({"start_date": "2026-11-18"}, {**UNKNOWN_BASICS, "start_date": "2026-11-18"}),
    ({"end_date": "2026-11-19"}, {**UNKNOWN_BASICS, "end_date": "2026-11-19"}),
    ({"party_size": 1}, {**UNKNOWN_BASICS, "party_size": 1}),
    ({"party_size": 10}, {**UNKNOWN_BASICS, "party_size": 10}),
    ({"start_date": "2028-02-29", "end_date": "2028-02-29"},
     {**UNKNOWN_BASICS, "start_date": "2028-02-29", "end_date": "2028-02-29"}),
])
def test_legacy_and_partial_requests_keep_missing_information_unknown(client, changes, expected):
    response = create(client, **changes)
    assert response.status_code == 201, response.text
    assert {key: response.json()[key] for key in expected} == expected
    state = client.get(ROOT, headers=KEY).json()
    assert {key: state[key] for key in expected} == expected


def test_restart_preserves_basics(database, monkeypatch):
    monkeypatch.setenv("TRAVELGUARD_TOOL_API_KEY", KEY["X-Tool-Key"])
    monkeypatch.setenv("TRAVELGUARD_DB_PATH", str(database))
    with TestClient(app) as first:
        response = create(first, **BASICS)
        assert response.status_code == 201, response.text
        original = response.json()
    with TestClient(app) as restarted:
        assert restarted.get(ROOT, headers=KEY).json() == original
        assert create(restarted, **BASICS).json() == original


def legacy_database(database, *, version=1):
    """Freeze schema v1 independently of the migrator; seed all five tables."""
    stored_plan = TravelPlan.model_validate(plan()).model_dump(mode="json")
    constraints = {"budget_cny": "300.00", "max_walking_minutes_per_leg": 20,
                   "return_deadline": "2026-11-19T17:00:00+08:00"}
    budget = {"budget_cny": "300.00", "paid_cny": "100.00", "planned_cny": "70.00",
              "received_refunds_cny": "0.00", "pending_refunds_cny": "0.00",
              "conservative_total_cny": "170.00", "remaining_cny": "130.00", "within_budget": True}
    validation = {"overall": "PASS", "checks": [], "note": "legacy simulation"}
    initial = {
        "trip_id": "wuhan", "version": 1, "event_revision": 0, "history_revision": 0,
        "source_draft_id": None, "plan": stored_plan, "budget": budget,
        "validation": validation, "confirmation": None, "created_at": "2026-10-21T00:00:00Z",
    }
    current = deepcopy(initial)
    current.update(version=2, event_revision=1, history_revision=1, source_draft_id="D1",
                   confirmation={"request_id": "confirm-legacy", "confirmed_by": "local-user",
                                 "confirmed_at": "2026-10-21T01:00:00Z"})
    current["plan"]["refunds"] = [{"id": "pending-refund", "amount_cny": "20.00", "status": "pending"}]
    current["budget"]["pending_refunds_cny"] = "20.00"
    event = {"event_id": "E1", "revision": 1, "kind": "poi_closed", "active": True,
             "poi_id": "unvisited-poi", "effective_at": "2026-11-18T00:00:00+08:00",
             "activity_id": None, "earliest_start_at": None, "source": "simulation",
             "evidence_ref": "simulation:legacy-event", "verification_status": "verified"}
    initial_view = {
        "trip_id": "wuhan", "title": "武汉两日游", "current_version": 1,
        "event_revision": 0, "history_revision": 0, "constraints": constraints,
        "locked_activity_ids": [], "current_plan": initial, "events": [],
    }
    # Exact normalized v1 request: new optional defaults must not change this fingerprint.
    legacy_request = {"request_id": "create-1", "trip_id": "wuhan", "title": "武汉两日游",
                      **constraints, "plan": stored_plan, "locked_activity_ids": []}
    fingerprint = sha256(json.dumps({"operation": "create_trip", "body": legacy_request},
                                   ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                         .encode("utf-8")).hexdigest()
    with sqlite3.connect(database) as db:
        db.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE trips (
                trip_id TEXT PRIMARY KEY, title TEXT NOT NULL, constraints_json TEXT NOT NULL,
                current_version INTEGER NOT NULL CHECK(current_version >= 1),
                event_revision INTEGER NOT NULL DEFAULT 0, history_revision INTEGER NOT NULL DEFAULT 0,
                locked_ids_json TEXT NOT NULL);
            CREATE TABLE versions (
                trip_id TEXT NOT NULL REFERENCES trips(trip_id), version INTEGER NOT NULL,
                payload_json TEXT NOT NULL, PRIMARY KEY(trip_id, version));
            CREATE TABLE events (
                trip_id TEXT NOT NULL REFERENCES trips(trip_id), event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL, PRIMARY KEY(trip_id, event_id));
            CREATE TABLE drafts (
                trip_id TEXT NOT NULL REFERENCES trips(trip_id), draft_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','stale','committed')),
                committed_version INTEGER, payload_json TEXT NOT NULL, PRIMARY KEY(trip_id, draft_id),
                FOREIGN KEY(trip_id, committed_version) REFERENCES versions(trip_id, version));
            CREATE TABLE requests (
                trip_id TEXT NOT NULL REFERENCES trips(trip_id), request_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, response_json TEXT NOT NULL, PRIMARY KEY(trip_id, request_id));
        """)
        db.execute("INSERT INTO trips VALUES (?,?,?,2,1,1,?)",
                   ("wuhan", "武汉两日游", json.dumps(constraints), '["museum"]'))
        for item in [initial, current]:
            db.execute("INSERT INTO versions VALUES (?,?,?)", ("wuhan", item["version"], json.dumps(item)))
        db.execute("INSERT INTO events VALUES (?,?,?)", ("wuhan", "E1", json.dumps(event)))
        for draft_id, status, committed_version in [("D1", "committed", 2), ("D2", "pending", None),
                                                     ("D0", "stale", None)]:
            payload = {"trip_id": "wuhan", "draft_id": draft_id, "base_version": 2 if draft_id == "D2" else 1,
                       "event_revision": 1, "history_revision": 1, "handled_event_ids": ["E1"],
                       "status": status, "committed_version": committed_version,
                       "plan": current["plan"], "validation": validation, "created_at": "2026-10-21T00:30:00Z"}
            db.execute("INSERT INTO drafts VALUES (?,?,?,?,?)",
                       ("wuhan", draft_id, status, committed_version, json.dumps(payload)))
        db.execute("INSERT INTO requests VALUES (?,?,?,?)",
                   ("wuhan", "create-1", fingerprint, json.dumps(initial_view)))
        db.execute(f"PRAGMA user_version = {version}")


def legacy_rows(database):
    with sqlite3.connect(database) as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
                for table in ("versions", "drafts", "events", "requests")}


@pytest.mark.parametrize("version", [0, 1])
def test_legacy_migration_preserves_snapshots_fees_receipts_and_confirmation(database, monkeypatch, version):
    legacy_database(database, version=version)
    before = legacy_rows(database)
    with sqlite3.connect(database) as db:
        old_trip = db.execute("SELECT * FROM trips").fetchone()
    monkeypatch.setenv("TRAVELGUARD_TOOL_API_KEY", KEY["X-Tool-Key"])
    monkeypatch.setenv("TRAVELGUARD_DB_PATH", str(database))
    for _ in range(2):  # Upgrade and a second initialization must both preserve the original rows.
        with TestClient(app) as api:
            state = api.get(ROOT, headers=KEY).json()
            assert {key: state[key] for key in UNKNOWN_BASICS} == UNKNOWN_BASICS
            assert state["current_version"] == 2
            assert state["event_revision"] == 1
            assert state["history_revision"] == 1
            assert state["locked_activity_ids"] == ["museum"]
            assert state["current_plan"]["budget"]["paid_cny"] == "100.00"
            assert state["current_plan"]["budget"]["pending_refunds_cny"] == "20.00"
            assert state["current_plan"]["budget"]["conservative_total_cny"] == "170.00"
            assert len(api.get(f"{ROOT}/versions", headers=KEY).json()) == 2
            assert {d["draft_id"]: d["status"] for d in api.get(f"{ROOT}/drafts", headers=KEY).json()} == {
                "D0": "stale", "D1": "committed", "D2": "pending"}
            retried = create(api)
            assert retried.status_code == 201, retried.text
            assert retried.json()["current_version"] == 1  # Historical receipt, not current state.
            assert {key: retried.json()[key] for key in UNKNOWN_BASICS} == UNKNOWN_BASICS
            assert create(api, **BASICS).status_code == 409  # Never overwrite unknown data on retry.
        assert legacy_rows(database) == before
        with sqlite3.connect(database) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 2
            assert db.execute("SELECT * FROM trips").fetchone()[:7] == old_trip
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with TestClient(app) as api:
        confirmed = api.post(f"{ROOT}/drafts/D2/confirm", headers=KEY, json={
            "request_id": "confirm-migrated", "base_version": 2, "event_revision": 1,
            "history_revision": 1, "user_confirmed": True, "confirmed_by": "local-user"})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["version"] == 3
        assert confirmed.json()["budget"]["paid_cny"] == "100.00"
        assert confirmed.json()["budget"]["pending_refunds_cny"] == "20.00"


def test_failed_migration_rolls_back_schema_and_original_data(database):
    legacy_database(database)
    before = legacy_rows(database)
    # A conflicting column forces failure midway through ADD COLUMN, after city/party_size.
    with sqlite3.connect(database) as db:
        db.execute("ALTER TABLE trips ADD COLUMN start_date TEXT")
        schema = db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    with pytest.raises(sqlite3.OperationalError):
        TravelStore(database).initialize()
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema
    assert legacy_rows(database) == before


def test_unknown_schema_version_is_rejected_without_mutation(database):
    legacy_database(database, version=99)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="99"):
        TravelStore(database).initialize()
    assert database.read_bytes() == before
