"""Hand-derived quality metrics, independent of WF labels and presentation names."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from app.replan_evaluation import evaluate_replan
from replan_fixtures import simulation_bundle


def inputs():
    bundle = simulation_bundle()
    trip = bundle["context"]["trip"]
    return {"baseline": trip["current_plan"]["plan"], "candidate": deepcopy(trip["current_plan"]["plan"]),
            "constraints": trip["constraints"], "events": [], "locked_activity_ids": ["A1"],
            "required_booking_pois": []}


def test_identity_and_new_activities_do_not_dilute_retention_denominator():
    body = inputs()
    extra = {**deepcopy(body["candidate"]["activities"][1]), "id": "A_NEW",
             "start_at": "2026-11-18T15:30:00+08:00", "end_at": "2026-11-18T16:00:00+08:00"}
    body["candidate"]["activities"].append(extra)
    body["candidate"]["activity_evidence"]["A_NEW"] = "simulation:new-opening"
    evaluated = evaluate_replan(**body)
    assert evaluated["changed_activity_count"] == 0
    assert evaluated["added_activity_count"] == 1
    assert evaluated["unchanged_activity_retention_rate"] == "1"
    assert evaluated["locked_activity_violations"] == []
    assert evaluated["candidate_validation_status"] == "PASS"


def test_deletions_replacements_time_and_other_activity_attributes_count():
    for change in ["delete", "replace", "time", "walking"]:
        body = inputs()
        if change == "delete":
            body["candidate"]["activities"].pop(1)
            body["candidate"]["activity_evidence"].pop("A3")
        elif change == "replace":
            body["candidate"]["activities"][1]["poi_id"] = "simulation:replacement"
        elif change == "time":
            body["candidate"]["activities"][1]["end_at"] = "2026-11-18T15:30:00+08:00"
        else:
            body["candidate"]["activities"][1]["walking_minutes_from_previous"] = 15
        evaluated = evaluate_replan(**body)
        assert evaluated["changed_activity_count"] == 1
        assert evaluated["unchanged_activity_retention_rate"] == "0.5"
        assert evaluated["added_activity_count"] == 0


def test_money_uses_complete_snapshots_and_never_offsets_pending_refunds():
    body = inputs()
    body["candidate"]["charges"][1]["amount_cny"] = "50.01"
    body["candidate"]["refunds"][1]["amount_cny"] = "99.99"
    evaluated = evaluate_replan(**body)
    assert evaluated["budget_delta_cny"] == "0.01"
    assert evaluated["hard_constraint_result"]["overall"] == "PASS"


def test_history_activity_and_evidence_changes_are_violations():
    body = inputs()
    body["candidate"]["activity_evidence"]["A1"] = "simulation:different-proof"
    evaluated = evaluate_replan(**body)
    assert evaluated["locked_activity_violations"] == ["A1"]
    assert evaluated["candidate_validation_status"] == "FAIL"


def test_missing_candidate_is_uncomputable_and_never_zero_or_pass():
    body = inputs()
    body["candidate"] = None
    evaluated = evaluate_replan(**body)
    for metric in ["changed_activity_count", "added_activity_count", "unchanged_activity_retention_rate",
                   "budget_delta_cny", "hard_constraint_result", "locked_activity_violations"]:
        assert evaluated[metric] is None
    assert evaluated["candidate_validation_status"] == "UNKNOWN"
    assert evaluated["unavailable_reasons"]


def test_missing_ledger_is_not_implicitly_an_empty_zero_cost_ledger():
    body = inputs()
    body["candidate"].pop("charges")
    body["candidate"].pop("refunds")
    body["candidate"].pop("financial_evidence")
    evaluated = evaluate_replan(**body)
    assert evaluated["budget_delta_cny"] is None
    assert evaluated["candidate_validation_status"] == "UNKNOWN"


def test_missing_context_is_uncomputable_in_standalone_evaluator():
    body = inputs()
    body["events"] = None
    evaluated = evaluate_replan(**body)
    assert evaluated["hard_constraint_result"] is None
    assert evaluated["candidate_validation_status"] == "UNKNOWN"


def test_evaluation_is_standalone_reproducible_and_does_not_mutate_inputs():
    body = inputs()
    before = deepcopy(body)
    assert evaluate_replan(**body) == evaluate_replan(**body)
    assert body == before


def test_evaluation_cli_runs_without_adapter_or_database():
    fixture = Path(__file__).parent / "fixtures" / "replan_evaluation_simulation.json"
    run = subprocess.run([sys.executable, "-m", "app.replan_evaluation", str(fixture)],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(run.stdout)["budget_delta_cny"] == "0.00"
