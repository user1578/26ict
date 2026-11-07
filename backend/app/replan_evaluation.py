"""Deterministic local quality metrics; never calls an agent or external service."""

import argparse
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sys

from pydantic import ValidationError

from .logic import calculate_budget
from .travel_schemas import EventView, TravelPlan, TripConstraints
from .travel_validation import budget_input, validate_snapshot


def evaluate_replan(*, baseline=None, candidate=None, constraints=None, events=None, locked_activity_ids=None,
                    required_booking_pois=None):
    """Compare complete B snapshots. Missing/invalid inputs yield explicit unavailable metrics."""
    unavailable = {
        "changed_activity_count": None, "added_activity_count": None,
        "unchanged_activity_retention_rate": None, "hard_constraint_result": None,
        "budget_delta_cny": None, "locked_activity_violations": None,
        "candidate_validation_status": "UNKNOWN", "adapter_elapsed_ms": None,
        "unavailable_reasons": [],
    }
    if baseline is None or candidate is None:
        return {**unavailable, "unavailable_reasons": ["baseline_or_candidate_missing"]}
    if constraints is None or events is None or locked_activity_ids is None or required_booking_pois is None:
        return {**unavailable, "unavailable_reasons": ["validation_context_missing"]}
    try:
        baseline = TravelPlan.model_validate(baseline)
        candidate = TravelPlan.model_validate(candidate)
        constraints = TripConstraints.model_validate(constraints)
        events = [EventView.model_validate(event) for event in events]
    except ValidationError as error:
        return {**unavailable, "unavailable_reasons": [str(loc["loc"]) for loc in error.errors()]}
    if any(not {"charges", "refunds"} <= snapshot.model_fields_set for snapshot in (baseline, candidate)):
        return {**unavailable, "unavailable_reasons": ["complete_financial_snapshots_required"]}
    previous = {activity.id: activity for activity in baseline.activities}
    current = {activity.id: activity for activity in candidate.activities}
    if (not set(locked_activity_ids) <= previous.keys() or required_booking_pois is None):
        return {**unavailable, "unavailable_reasons": ["incomplete_history_or_lock_context"]}
    changed = [key for key, activity in previous.items() if current.get(key) != activity]
    violations = sorted(key for key in locked_activity_ids
                        if current.get(key) != previous[key]
                        or candidate.activity_evidence.get(key) != baseline.activity_evidence.get(key))
    with localcontext() as decimal_context:
        decimal_context.prec = 28
        validation = validate_snapshot(candidate, constraints, events, locked_activity_ids,
                                       baseline, set(required_booking_pois))
        retention = Decimal(len(previous) - len(changed)) / Decimal(len(previous))
        delta = (calculate_budget(budget_input(candidate, constraints)).conservative_total_cny
                 - calculate_budget(budget_input(baseline, constraints)).conservative_total_cny)
    return {
        "changed_activity_count": len(changed), "added_activity_count": len(current.keys() - previous.keys()),
        "unchanged_activity_retention_rate": str(retention),
        "hard_constraint_result": validation.model_dump(mode="json"),
        "budget_delta_cny": format(delta, ".2f"), "locked_activity_violations": violations,
        "candidate_validation_status": validation.overall.value,
        "adapter_elapsed_ms": None, "unavailable_reasons": [],
    }


def main():
    # Stable UTF-8 JSON even when Windows redirects stdout using a legacy locale.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Offline snapshot evaluation; no database or AI calls")
    parser.add_argument("input", type=Path, help="simulation JSON containing evaluation inputs")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.pop("data_type", None) != "simulation":
        parser.error("only explicitly marked simulation inputs are supported")
    print(json.dumps(evaluate_replan(**payload), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
