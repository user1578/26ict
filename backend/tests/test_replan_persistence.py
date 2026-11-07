"""Only this integration test persists adapter requests, always to pytest's temporary SQLite file."""

from copy import deepcopy
import sqlite3

from app.replan_adapter import adapt_replan
from replan_fixtures import simulation_bundle
from test_travel_state import KEY, client, database


def test_multi_event_adapter_drafts_obey_existing_staleness_and_confirmation(client, database):
    bundle = simulation_bundle()
    trip = bundle["context"]["trip"]
    root = "/api/trips/" + trip["trip_id"]
    created = client.post("/api/trips", headers=KEY, json={
        "request_id": "simulation-create", "trip_id": trip["trip_id"], "title": trip["title"],
        "city": trip["city"], "party_size": trip["party_size"], "start_date": trip["start_date"], "end_date": trip["end_date"],
        **trip["constraints"], "plan": trip["current_plan"]["plan"]})
    assert created.status_code == 201, created.text
    changed = client.put(root + "/events/B-E1", headers=KEY, json={
        "request_id": "simulation-event1", "expected_event_revision": 0, "kind": "train_delay", "activity_id": "A1",
        "earliest_start_at": "2026-11-18T11:00:00+08:00", "source": "simulation",
        "evidence_ref": "simulation:delay", "verification_status": "verified"})
    assert changed.status_code == 200
    bundle["context"]["trip"] = client.get(root, headers=KEY).json()
    bundle["context"]["versions"] = client.get(root + "/versions", headers=KEY).json()
    before = deepcopy(bundle["context"]["trip"])
    adapted = adapt_replan(bundle)["options"][0]
    assert adapted["status"] == "successfully_adapted"
    assert client.get(root, headers=KEY).json() == before  # The adapter itself writes nothing.
    first = adapted["draft_request"]
    saved = client.post(root + "/drafts", headers=KEY, json=first)
    assert saved.status_code == 201, saved.text
    assert saved.json()["validation"]["overall"] == "PASS"
    changed = client.put(root + "/events/B-E2", headers=KEY, json={
        "request_id": "simulation-event2", "expected_event_revision": 1, "kind": "poi_closed",
        "poi_id": "simulation:museum", "effective_at": "2026-11-18T13:00:00+08:00",
        "source": "simulation", "evidence_ref": "simulation:closed", "verification_status": "verified"})
    assert changed.status_code == 200
    confirmation = {"request_id": "simulation-confirm-old", "base_version": 1, "event_revision": 1,
                    "history_revision": 0, "user_confirmed": True, "confirmed_by": "simulation-user"}
    assert client.post(root + f"/drafts/{first['draft_id']}/confirm", headers=KEY, json=confirmation).status_code == 409
    assert client.get(root + f"/drafts/{first['draft_id']}", headers=KEY).json()["status"] == "stale"
    bundle["context"]["trip"] = client.get(root, headers=KEY).json()
    bundle["workflow_input"]["event_revision"] = 2
    bundle["workflow_input"]["active_events"].append({
        "event_id": "E2", "event_type": "site_closure", "status": "active", "verification_status": "verified"})
    bundle["workflow_output"]["event_ids"] = ["E1", "E2"]
    bundle["context"]["event_bindings"]["E2"] = "B-E2"
    assert adapt_replan(bundle)["options"][0]["status"] == "rejected"  # Still visits the closed POI.
    row = bundle["workflow_output"]["options"][0]["proposed_schedule"][1]
    row.update(activity_id="A5", action="new_candidate", name="simulation:替代地点")
    support = bundle["context"]["option_support"]["OPT_A"]
    support["removed_activity_ids"] = ["A3"]
    support["activities"]["A5"] = {**deepcopy(trip["current_plan"]["plan"]["activities"][1]),
                                    "id": "A5", "poi_id": "simulation:park"}
    support["activity_evidence"]["A5"] = "simulation:park-open"
    adapted = adapt_replan(bundle)["options"][0]
    assert adapted["status"] == "successfully_adapted", adapted["issues"]
    assert adapted["evaluation"]["changed_activity_count"] == 2  # Moved A1 and deleted A3.
    assert adapted["evaluation"]["added_activity_count"] == 1
    second = adapted["draft_request"]
    assert second["draft_id"] != first["draft_id"]
    assert client.post(root + "/drafts", headers=KEY, json=second).status_code == 201
    confirmation.update(request_id="simulation-confirm-new", event_revision=2)
    committed = client.post(root + f"/drafts/{second['draft_id']}/confirm", headers=KEY, json=confirmation)
    assert committed.status_code == 200, committed.text
    assert committed.json()["version"] == 2
    assert committed.json()["budget"]["conservative_total_cny"] == "140.00"
    assert committed.json()["budget"]["pending_refunds_cny"] == "40.00"
    assert len(client.get(root + "/versions", headers=KEY).json()) == 2
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
