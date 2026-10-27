"""Offline simulation only: no provider, model, or real booking facts."""

from copy import deepcopy
from decimal import Decimal

from app.logic import calculate_budget
from app.travel_schemas import TravelPlan, TripConstraints
from app.travel_validation import budget_input, validate_snapshot


def simulation_bundle():
    plan = TravelPlan.model_validate({
        "activities": [
            {"id": "A1", "poi_id": "simulation:station", "start_at": "2026-11-18T09:00:00+08:00",
             "end_at": "2026-11-18T10:00:00+08:00", "opening_status": "confirmed_open"},
            {"id": "A3", "poi_id": "simulation:museum", "start_at": "2026-11-18T14:00:00+08:00",
             "end_at": "2026-11-18T15:00:00+08:00", "opening_status": "confirmed_open",
             "transport_minutes_from_previous": 30, "walking_minutes_from_previous": 10},
        ],
        "charges": [{"id": "paid", "amount_cny": "100.00", "status": "paid"},
                    {"id": "future", "amount_cny": "50.00", "status": "planned"}],
        "refunds": [{"id": "received", "amount_cny": "10.00", "status": "received"},
                    {"id": "pending", "amount_cny": "40.00", "status": "pending"}],
        "arrival_at_return_station": "2026-11-18T17:00:00+08:00",
        "activity_evidence": {"A1": "simulation:station-open", "A3": "simulation:museum-open"},
        "financial_evidence": {"paid": "simulation:paid", "received": "simulation:received"},
    })
    constraints = TripConstraints(budget_cny=Decimal("300.00"), max_walking_minutes_per_leg=20,
                                  return_deadline="2026-11-18T18:00:00+08:00")
    version = {
        "trip_id": "simulation-trip", "version": 1, "event_revision": 0, "history_revision": 0,
        "source_draft_id": None, "plan": plan.model_dump(mode="json"),
        "budget": calculate_budget(budget_input(plan, constraints)).model_dump(mode="json"),
        "validation": validate_snapshot(plan, constraints, [], []).model_dump(mode="json"),
        "confirmation": None, "created_at": "2026-10-28T00:00:00Z",
    }
    trip = {
        "trip_id": "simulation-trip", "title": "simulation:离线重规划", "city": "武汉", "party_size": 3,
        "start_date": "2026-11-18", "end_date": "2026-11-18", "preferences": {"stay_together": True},
        "current_version": 1, "event_revision": 1, "history_revision": 0,
        "constraints": constraints.model_dump(mode="json"), "locked_activity_ids": [],
        "current_plan": version,
        "events": [{"event_id": "B-E1", "revision": 1, "kind": "train_delay", "active": True,
                    "activity_id": "A1", "earliest_start_at": "2026-11-18T11:00:00+08:00",
                    "source": "simulation", "evidence_ref": "simulation:delay", "verification_status": "verified"}],
    }
    support = {
        "activities": {"A1": {**plan.activities[0].model_dump(mode="json"),
                               "start_at": "2026-11-18T11:00:00+08:00", "end_at": "2026-11-18T12:00:00+08:00"}},
        "activity_dates": {}, "removed_activity_ids": [],
        "charges": plan.model_dump(mode="json")["charges"],
        "refunds": plan.model_dump(mode="json")["refunds"],
        "arrival_at_return_station": "2026-11-18T17:00:00+08:00",
        "activity_evidence": {"A1": "simulation:station-open-at-new-time"},
        "financial_evidence": {},
    }
    return {
        "data_type": "simulation",
        "context": {"trip": trip, "versions": [deepcopy(version)], "timezone_offset": "+08:00",
                    "activity_dates": {}, "event_bindings": {"E1": "B-E1"}, "option_support": {"OPT_A": support}},
        "workflow_input": {
            "trip_id": trip["trip_id"], "formal_version": "v1", "event_revision": 1, "history_revision": 0,
            "constraints": {"fixed_activity_ids": [], "user_authorizations": []},
            "current_plan": {"activities": [
                {"activity_id": a.id, "name": "simulation:" + a.id, "start_time": a.start_at.isoformat(),
                 "end_time": a.end_at.isoformat(), "fixed": False} for a in plan.activities]},
            "active_events": [{"event_id": "E1", "event_type": "transport_disruption", "status": "active",
                               "verification_status": "verified", "severity": "medium", "confidence": "0.9",
                               "start_time": None, "end_time": None}],
        },
        "workflow_output": {
            "trip_id": trip["trip_id"], "base_version": "v1", "event_ids": ["E1"], "draft_id": "WF-D1",
            "draft_status": "awaiting_confirmation", "warnings": ["simulation:未调用AgentArts"],
            "official_version_unchanged": True,
            "options": [{"option_id": "OPT_A", "feasibility": "feasible", "changed_activity_ids": ["A1"],
                         "additional_estimated_cost_cny": "0.00", "warnings": [], "requires_external_actions": [],
                         "proposed_schedule": [
                             {"activity_id": "A1", "name": "simulation:晚点列车", "start_time": "2026-11-18T11:00:00+08:00",
                              "end_time": "2026-11-18T12:00:00+08:00", "action": "reschedule", "reason": "模拟晚点"},
                             {"activity_id": "A3", "name": "simulation:博物馆", "start_time": "2026-11-18T14:00:00+08:00",
                              "end_time": "2026-11-18T15:00:00+08:00", "action": "keep", "reason": "保留"},
                         ]}],
        },
    }
