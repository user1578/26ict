"""Local WF_Replan v0.1.0 simulation protocol, not a frozen AgentArts API."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt, field_validator

from .travel_schemas import (
    Contract, EvidenceRef, Identifier, StoredActivity, StoredCharge, StoredRefund,
    TripView, VersionView, require_timezone,
)


class WFActivity(Contract):
    activity_id: Identifier
    name: str
    start_time: str | None
    end_time: str | None
    fixed: StrictBool = False


class WFScheduledActivity(WFActivity):
    action: Literal["keep", "reschedule", "new_candidate"]
    reason: str


class WFCurrentPlan(Contract):
    activities: list[WFActivity] = Field(min_length=1)


class WFEvent(Contract):
    event_id: Identifier
    event_type: str
    status: Literal["active"]
    verification_status: Literal["verified", "unverified", "unknown"]
    severity: str | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    start_time: str | None = None
    end_time: str | None = None


class WFConstraints(Contract):
    budget_remaining_cny: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    return_deadline: str | None = None
    return_deadline_hard: StrictBool | None = None
    fixed_activity_ids: list[Identifier] = Field(default_factory=list)
    # Prototype convention: activity IDs authorized for a future reschedule proposal only.
    user_authorizations: list[Identifier] = Field(default_factory=list)
    return_transport_options: list[dict[str, Any]] = Field(default_factory=list)


class WFInput(Contract):
    trip_id: Identifier
    formal_version: str | StrictInt
    event_revision: StrictInt = Field(ge=0)
    history_revision: StrictInt = Field(ge=0)
    constraints: WFConstraints
    current_plan: WFCurrentPlan
    active_events: list[WFEvent]


class WFOption(Contract):
    option_id: Identifier
    feasibility: Literal["conditional", "feasible"]
    changed_activity_ids: list[Identifier]
    additional_estimated_cost_cny: Decimal | None = Field(decimal_places=2)
    warnings: list[str]
    requires_external_actions: list[str]
    proposed_schedule: list[WFScheduledActivity]


class WFOutput(Contract):
    trip_id: Identifier
    base_version: str | StrictInt
    event_ids: list[Identifier]
    draft_id: Identifier
    draft_status: Literal["needs_information", "awaiting_confirmation"]
    options: list[dict[str, Any]]
    warnings: list[str]
    official_version_unchanged: StrictBool
    # A's summary does not echo these. If provided, they must match the invocation too.
    event_revision: StrictInt | None = Field(default=None, ge=0)
    history_revision: StrictInt | None = Field(default=None, ge=0)


class CandidateSupport(Contract):
    """Explicit B-shaped simulation facts supplied separately from model analysis."""

    activities: dict[Identifier, StoredActivity] = Field(default_factory=dict)
    activity_dates: dict[Identifier, str] = Field(default_factory=dict)
    removed_activity_ids: list[Identifier] = Field(default_factory=list)
    charges: list[StoredCharge] | None = None
    refunds: list[StoredRefund] | None = None
    arrival_at_return_station: datetime | None = None
    activity_evidence: dict[Identifier, EvidenceRef] = Field(default_factory=dict)
    financial_evidence: dict[Identifier, EvidenceRef] = Field(default_factory=dict)

    @field_validator("arrival_at_return_station")
    @classmethod
    def aware_arrival(cls, value):
        require_timezone(value)
        return value


class ReplanContext(Contract):
    trip: TripView
    # Full official history is needed to retain booking rules omitted in a later version.
    versions: list[VersionView] = Field(min_length=1)
    timezone_offset: str | None = None
    activity_dates: dict[Identifier, str] = Field(default_factory=dict)
    # Explicitly narrowed A event -> existing B event; never infer a train delay from a generic disruption.
    event_bindings: dict[Identifier, Identifier]
    option_support: dict[Identifier, dict[str, Any]] = Field(default_factory=dict)


class SimulationBundle(Contract):
    data_type: Literal["simulation"]
    context: ReplanContext
    workflow_input: WFInput
    workflow_output: WFOutput
