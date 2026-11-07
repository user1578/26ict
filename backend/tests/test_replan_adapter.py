"""Local simulation contract: input incompleteness must never fabricate a PASS."""

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.replan_adapter import adapt_replan
from replan_fixtures import simulation_bundle


def result(bundle):
    return adapt_replan(bundle)


def option(bundle):
    return bundle["workflow_output"]["options"][0]


def support(bundle):
    return bundle["context"]["option_support"]["OPT_A"]


def codes(value):
    return {issue["code"] for issue in value["issues"]}


def test_complete_candidate_is_independent_pass_request_and_preserves_analysis():
    bundle = simulation_bundle()
    original = deepcopy(bundle)
    adapted = result(bundle)
    assert adapted["status"] == "successfully_adapted"
    candidate = adapted["options"][0]
    assert candidate["status"] == "successfully_adapted"
    request = candidate["draft_request"]
    assert (request["base_version"], request["event_revision"], request["history_revision"]) == (1, 1, 0)
    assert request["handled_event_ids"] == ["B-E1"]
    assert request["plan"]["activities"][0]["id"] == "A1"
    assert request["plan"]["activities"][0]["start_at"] == "2026-11-18T11:00:00+08:00"
    assert request["plan"]["charges"] == support(bundle)["charges"]
    assert request["plan"]["refunds"] == support(bundle)["refunds"]
    assert request["plan"]["financial_evidence"]["paid"] == "simulation:paid"
    assert candidate["analysis"] == option(bundle)
    assert candidate["evaluation"]["changed_activity_count"] == 1
    assert candidate["evaluation"]["unchanged_activity_retention_rate"] == "0.5"
    assert candidate["evaluation"]["budget_delta_cny"] == "0.00"
    assert candidate["evaluation"]["candidate_validation_status"] == "PASS"
    assert candidate["evaluation"]["adapter_elapsed_ms"] is None
    assert bundle == original
    assert result(bundle) == adapted


def test_multiple_options_have_stable_distinct_draft_and_request_ids():
    bundle = simulation_bundle()
    second = deepcopy(option(bundle))
    second["option_id"] = "OPT_B"
    bundle["workflow_output"]["options"].append(second)
    bundle["context"]["option_support"]["OPT_B"] = deepcopy(support(bundle))
    adapted = result(bundle)["options"]
    assert all(item["status"] == "successfully_adapted" for item in adapted)
    assert len({item["draft_request"]["draft_id"] for item in adapted}) == 2
    assert len({item["draft_request"]["request_id"] for item in adapted}) == 2


@pytest.mark.parametrize("field,value,code", [
    ("start_time", "11:00", "missing_date"), ("end_time", None, "missing_time"),
    ("start_time", None, "missing_time"), ("start_time", "bad-time", "invalid_time"),
])
def test_incomplete_or_invalid_time_has_option_reason_without_draft(field, value, code):
    bundle = simulation_bundle()
    option(bundle)["proposed_schedule"][0][field] = value
    adapted = result(bundle)["options"][0]
    assert adapted["status"] != "successfully_adapted"
    assert adapted["draft_request"] is None
    assert code in codes(adapted)
    assert all(issue["option_id"] == "OPT_A" for issue in adapted["issues"])
    assert adapted["evaluation"]["budget_delta_cny"] is None


def test_short_time_requires_explicit_activity_date_and_timezone():
    bundle = simulation_bundle()
    row = option(bundle)["proposed_schedule"][0]
    row.update(start_time="11:00", end_time="12:00")
    support(bundle)["activity_dates"] = {"A1": "2026-11-18"}
    assert result(bundle)["options"][0]["status"] == "successfully_adapted"
    bundle["context"]["timezone_offset"] = None
    assert "missing_timezone" in codes(result(bundle)["options"][0])


def test_malformed_offset_minutes_cannot_be_silently_normalized():
    bundle = simulation_bundle()
    # Python datetime would normalize +01:99 to +02:39, yielding exactly 11:00/12:00 +08:00 here.
    option(bundle)["proposed_schedule"][0].update(
        start_time="2026-11-18T05:39:00+01:99", end_time="2026-11-18T06:39:00+01:99")
    adapted = result(bundle)["options"][0]
    assert adapted["status"] == "rejected"
    assert "invalid_time" in codes(adapted)


def without_events(bundle):
    bundle["context"]["trip"].update(events=[], event_revision=0)
    bundle["context"]["event_bindings"] = {}
    bundle["workflow_input"].update(active_events=[], event_revision=0)
    bundle["workflow_output"]["event_ids"] = []


def test_predecessor_poi_change_invalidates_successor_route_even_with_same_activity_id():
    bundle = simulation_bundle()
    without_events(bundle)
    support(bundle)["activities"]["A1"]["poi_id"] = "simulation:different-station"
    adapted = result(bundle)["options"][0]
    assert adapted["status"] == "needs_information"
    assert "missing_activity_details" in codes(adapted)
    assert adapted["draft_request"] is None


def test_keep_cannot_silently_replace_the_poi_via_support_data():
    bundle = simulation_bundle()
    without_events(bundle)
    original = deepcopy(bundle["context"]["trip"]["current_plan"]["plan"]["activities"][0])
    support(bundle)["activities"]["A1"] = {**original, "poi_id": "simulation:replacement"}
    option(bundle)["proposed_schedule"][0].update(action="keep", start_time=original["start_at"], end_time=original["end_at"])
    adapted = result(bundle)["options"][0]
    assert adapted["status"] == "rejected"
    assert "invalid_action" in codes(adapted)


def test_new_candidate_cannot_invent_poi_or_opening_evidence():
    bundle = simulation_bundle()
    row = option(bundle)["proposed_schedule"][1]
    row.update(activity_id="A_NEW", action="new_candidate")
    support(bundle)["removed_activity_ids"] = ["A3"]
    adapted = result(bundle)["options"][0]
    assert "missing_activity_details" in codes(adapted)
    assert adapted["draft_request"] is None


def test_name_only_changes_are_analysis_and_do_not_count_as_itinerary_changes():
    bundle = simulation_bundle()
    option(bundle)["proposed_schedule"][1]["name"] = "纯展示名称变更"
    candidate = result(bundle)["options"][0]
    assert candidate["evaluation"]["changed_activity_count"] == 1  # A1 actually moved; A3 only renamed.
    assert candidate["evaluation"]["unchanged_activity_retention_rate"] == "0.5"


def test_incomplete_option_does_not_discard_an_independent_complete_option():
    bundle = simulation_bundle()
    incomplete = deepcopy(option(bundle))
    incomplete["option_id"] = "OPT_B"
    incomplete["proposed_schedule"][0]["start_time"] = None
    bundle["workflow_output"]["options"].append(incomplete)
    bundle["context"]["option_support"]["OPT_B"] = deepcopy(support(bundle))
    candidates = result(bundle)["options"]
    assert [item["status"] for item in candidates] == ["successfully_adapted", "needs_information"]
    assert candidates[1]["draft_request"] is None


def test_a_simulation_claim_cannot_change_official_state_or_boolean_contract():
    for value in [False, 1]:
        bundle = simulation_bundle()
        bundle["workflow_output"]["official_version_unchanged"] = value
        assert result(bundle)["status"] == "rejected"


def test_missing_official_history_is_rejected_instead_of_forgetting_booking_rules():
    bundle = simulation_bundle()
    bundle["context"]["trip"]["current_version"] = 2
    bundle["workflow_input"]["formal_version"] = "v2"
    bundle["workflow_output"]["base_version"] = "v2"
    assert "history_mismatch" in codes(result(bundle))


def test_missing_baseline_financial_snapshot_returns_structured_unknown_without_crashing():
    bundle = simulation_bundle()
    for version in [bundle["context"]["trip"]["current_plan"], bundle["context"]["versions"][0]]:
        version["plan"].pop("charges")
        version["plan"].pop("refunds")
        version["plan"]["financial_evidence"] = {}
    support(bundle).update(charges=[], refunds=[])
    adapted = result(bundle)["options"][0]
    assert adapted["status"] == "needs_information"
    assert adapted["draft_request"] is None
    assert adapted["evaluation"]["candidate_validation_status"] == "UNKNOWN"
    assert adapted["evaluation"]["locked_activity_violations"] is None
    assert "complete_financial_snapshots_required" in adapted["evaluation"]["unavailable_reasons"]
    assert "backend_validation_unknown" in codes(adapted)


@pytest.mark.parametrize("change,expected_code", [
    ("missing-event", "event_set_mismatch"), ("duplicate-event", "duplicate_event_id"),
    ("event-revision", "revision_conflict"), ("history-revision", "revision_conflict"),
    ("version", "revision_conflict"), ("trip", "trip_mismatch"),
    ("missing-binding", "event_binding_mismatch"),
])
def test_snapshot_identity_and_exact_event_set_are_required(change, expected_code):
    bundle = simulation_bundle()
    if change == "missing-event":
        bundle["workflow_output"]["event_ids"] = []
    elif change == "duplicate-event":
        bundle["workflow_output"]["event_ids"] *= 2
    elif change == "event-revision":
        bundle["workflow_input"]["event_revision"] = 0
    elif change == "history-revision":
        bundle["workflow_input"]["history_revision"] = 1
    elif change == "version":
        bundle["workflow_output"]["base_version"] = "v2"
    elif change == "trip":
        bundle["workflow_output"]["trip_id"] = "other"
    else:
        bundle["context"]["event_bindings"] = {}
    adapted = result(bundle)
    assert adapted["status"] == "rejected"
    assert expected_code in codes(adapted)
    assert all(item["draft_request"] is None for item in adapted["options"])


@pytest.mark.parametrize("cause,expected_status", [("walking", "FAIL"), ("transport", "UNKNOWN"), ("evidence", "UNKNOWN")])
def test_feasible_does_not_override_backend_verification(cause, expected_status):
    bundle = simulation_bundle()
    facts = deepcopy(bundle["context"]["trip"]["current_plan"]["plan"]["activities"][1])
    if cause == "walking":
        facts["walking_minutes_from_previous"] = 40
    elif cause == "transport":
        facts["transport_minutes_from_previous"] = None
    else:
        support(bundle)["activity_evidence"].pop("A1")
    support(bundle)["activities"]["A3"] = facts
    candidate = result(bundle)["options"][0]
    assert candidate["draft_request"] is None
    assert candidate["evaluation"]["candidate_validation_status"] == expected_status
    assert candidate["analysis"]["feasibility"] == "feasible"


@pytest.mark.parametrize("layer", ["needs_information", "conditional", "external_action"])
def test_unresolved_analysis_is_retained_without_submittable_draft(layer):
    bundle = simulation_bundle()
    if layer == "needs_information":
        bundle["workflow_output"]["draft_status"] = layer
    elif layer == "conditional":
        option(bundle)["feasibility"] = layer
    else:
        option(bundle)["requires_external_actions"] = ["核实预约规则"]
    adapted = result(bundle)["options"][0]
    assert adapted["status"] == "needs_information"
    assert adapted["draft_request"] is None
    assert adapted["analysis"] == option(bundle)


@pytest.mark.parametrize("authorized", [False, True])
def test_future_fixed_changes_require_unimplemented_coordination_even_if_authorized(authorized):
    bundle = simulation_bundle()
    bundle["workflow_input"]["constraints"]["fixed_activity_ids"] = ["A1"]
    if authorized:
        bundle["workflow_input"]["constraints"]["user_authorizations"] = ["A1"]
    candidate = result(bundle)["options"][0]
    assert candidate["status"] == ("needs_information" if authorized else "rejected")
    assert candidate["draft_request"] is None
    assert ("fixed_reschedule_unsupported" if authorized else "fixed_activity_unauthorized") in codes(candidate)


def test_user_authorization_cannot_override_historical_lock():
    bundle = simulation_bundle()
    bundle["context"]["trip"]["locked_activity_ids"] = ["A1"]
    bundle["workflow_input"]["constraints"]["user_authorizations"] = ["A1"]
    candidate = result(bundle)["options"][0]
    assert candidate["status"] == "rejected"
    assert "locked_activity_changed" in codes(candidate)
    assert candidate["evaluation"]["locked_activity_violations"] == ["A1"]


@pytest.mark.parametrize("cause", ["paid", "received", "evidence", "new-paid"])
def test_financial_facts_cannot_be_changed_or_created(cause):
    bundle = simulation_bundle()
    if cause == "paid":
        support(bundle)["charges"][0]["amount_cny"] = "101.00"
    elif cause == "received":
        support(bundle)["refunds"][0]["amount_cny"] = "11.00"
    elif cause == "evidence":
        support(bundle)["financial_evidence"]["paid"] = "simulation:invented"
    else:
        support(bundle)["charges"].append({"id": "invented", "amount_cny": "1.00", "status": "paid"})
        support(bundle)["financial_evidence"]["invented"] = "simulation:invented"
    candidate = result(bundle)["options"][0]
    assert candidate["status"] == "rejected"
    assert candidate["draft_request"] is None
    assert candidate["evaluation"]["candidate_validation_status"] == "FAIL"


@pytest.mark.parametrize("estimate", [None, "0.00", "30.00"])
def test_estimate_is_never_a_complete_ledger_or_a_payment(estimate):
    bundle = simulation_bundle()
    option(bundle)["additional_estimated_cost_cny"] = estimate
    support(bundle).pop("charges")
    candidate = result(bundle)["options"][0]
    assert candidate["status"] == "needs_information"
    assert "missing_financial_snapshot" in codes(candidate)
    assert candidate["evaluation"]["budget_delta_cny"] is None


@pytest.mark.parametrize("cause", ["duplicate-option", "bad-option", "duplicate-activity", "bad-activity"])
def test_duplicate_or_invalid_identifiers_are_rejected(cause):
    bundle = simulation_bundle()
    if cause == "duplicate-option":
        bundle["workflow_output"]["options"].append(deepcopy(option(bundle)))
    elif cause == "bad-option":
        option(bundle)["option_id"] = "bad/id"
    elif cause == "duplicate-activity":
        option(bundle)["proposed_schedule"].append(deepcopy(option(bundle)["proposed_schedule"][0]))
    else:
        option(bundle)["proposed_schedule"][0]["activity_id"] = "bad id"
    adapted = result(bundle)
    assert adapted["status"] == "rejected"
    assert all(item["draft_request"] is None for item in adapted["options"])


def test_no_safe_options_is_an_explicit_empty_analysis():
    bundle = simulation_bundle()
    bundle["workflow_output"]["options"] = []
    adapted = result(bundle)
    assert adapted["status"] == "needs_information"
    assert adapted["options"] == []
    assert "no_safe_options" in codes(adapted)


def test_return_completion_semantics_do_not_reuse_station_arrival_as_completion():
    bundle = simulation_bundle()
    # A3 14:00-16:00, fixed A4 17:00-18:00; only A3 is authorized, hard completion 15:30.
    a4 = {**deepcopy(bundle["context"]["trip"]["current_plan"]["plan"]["activities"][1]),
          "id": "A4", "poi_id": "simulation:return", "start_at": "2026-11-18T17:00:00+08:00",
          "end_at": "2026-11-18T18:00:00+08:00"}
    for version in [bundle["context"]["trip"]["current_plan"], bundle["context"]["versions"][0]]:
        version["plan"]["activities"].append(deepcopy(a4))
        version["plan"]["arrival_at_return_station"] = "2026-11-18T18:00:00+08:00"
        version["plan"]["activity_evidence"]["A4"] = "simulation:return-open"
    bundle["workflow_input"]["current_plan"]["activities"].append({
        "activity_id": "A4", "name": "固定返程", "start_time": a4["start_at"], "end_time": a4["end_at"], "fixed": True})
    bundle["workflow_input"]["constraints"].update(
        return_deadline="2026-11-18T15:30:00+08:00", return_deadline_hard=True,
        fixed_activity_ids=["A4"], user_authorizations=["A3"])
    option(bundle)["proposed_schedule"][1]["end_time"] = "2026-11-18T16:00:00+08:00"
    option(bundle)["proposed_schedule"][1]["action"] = "reschedule"
    option(bundle)["proposed_schedule"].append({
        "activity_id": "A4", "name": "固定返程", "start_time": a4["start_at"], "end_time": a4["end_at"],
        "action": "keep", "reason": "不在授权范围"})
    support(bundle)["activities"]["A3"] = {
        **deepcopy(bundle["context"]["trip"]["current_plan"]["plan"]["activities"][1]),
        "end_at": "2026-11-18T16:00:00+08:00"}
    support(bundle)["activity_evidence"]["A3"] = "simulation:updated-hours"
    support(bundle)["arrival_at_return_station"] = "2026-11-18T18:00:00+08:00"
    candidate = result(bundle)["options"][0]
    assert candidate["draft_request"] is None
    assert "return_deadline_semantics_unresolved" in codes(candidate)
    # B retains station arrival <= deadline: equality itself is still PASS.
    check = next(c for c in candidate["evaluation"]["hard_constraint_result"]["checks"] if c["name"] == "return_check")
    assert check["status"] == "PASS"


def test_explicit_timing_is_local_and_deterministic_fields_remain_equal():
    bundle = simulation_bundle()
    plain = result(bundle)
    measured = adapt_replan(bundle, measure=True)
    elapsed = measured["options"][0]["evaluation"]["adapter_elapsed_ms"]
    assert Decimal(elapsed) >= 0
    measured["options"][0]["evaluation"]["adapter_elapsed_ms"] = None
    assert measured == plain


def test_adapter_cli_is_offline_and_json_reproducible():
    fixture = Path(__file__).parent / "fixtures" / "wf_replan_simulation.json"
    command = [sys.executable, "-m", "app.replan_adapter", str(fixture)]
    first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
    second = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["options"][0]["status"] == "successfully_adapted"
