"""Persistence API contracts; existing stateless tool contracts stay unchanged."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .schemas import Activity, BudgetRequest, BudgetResult, Charge, Refund, ValidatePlanResult


ID_PATTERN = r"^[^\s/\\]+$"
Identifier = Annotated[str, StringConstraints(pattern=ID_PATTERN, min_length=1, max_length=128)]
EvidenceRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


def require_timezone(value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError("时间必须带有时区")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoredActivity(Activity):
    model_config = ConfigDict(extra="forbid")
    id: Identifier
    poi_id: Identifier


class StoredCharge(Charge):
    model_config = ConfigDict(extra="forbid")
    id: Identifier


class StoredRefund(Refund):
    model_config = ConfigDict(extra="forbid")
    id: Identifier


class TravelPlan(Contract):
    activities: list[StoredActivity] = Field(min_length=1)
    charges: list[StoredCharge] = Field(default_factory=list)
    refunds: list[StoredRefund] = Field(default_factory=list)
    arrival_at_return_station: datetime | None = None
    activity_evidence: dict[Identifier, EvidenceRef] = Field(default_factory=dict)
    financial_evidence: dict[Identifier, EvidenceRef] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_snapshot(self):
        ids = [a.id for a in self.activities]
        if len(ids) != len(set(ids)):
            raise ValueError("行程活动ID不得重复")
        BudgetRequest(budget_cny=0, charges=self.charges, refunds=self.refunds)
        require_timezone(self.arrival_at_return_station)
        if set(self.activity_evidence) - set(ids):
            raise ValueError("活动证据必须引用本方案中的活动")
        if set(self.financial_evidence) - {x.id for x in [*self.charges, *self.refunds]}:
            raise ValueError("财务证据必须引用本方案中的费用流水")
        return self


class TripConstraints(Contract):
    budget_cny: Decimal = Field(ge=0, decimal_places=2)
    max_walking_minutes_per_leg: int | None = Field(default=None, ge=0)
    return_deadline: datetime | None = None

    @model_validator(mode="after")
    def validate_deadline(self):
        require_timezone(self.return_deadline)
        return self


class CreateTrip(TripConstraints):
    request_id: Identifier
    trip_id: Identifier
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    plan: TravelPlan
    locked_activity_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_locks(self):
        if len(self.locked_activity_ids) != len(set(self.locked_activity_ids)):
            raise ValueError("锁定活动ID不得重复")
        if set(self.locked_activity_ids) - {a.id for a in self.plan.activities}:
            raise ValueError("只能锁定正式行程中的活动")
        return self


class EventFacts(Contract):
    kind: Literal["train_delay", "poi_closed"]
    active: bool = True
    activity_id: Identifier | None = None
    earliest_start_at: datetime | None = None
    poi_id: Identifier | None = None
    effective_at: datetime | None = None
    source: Literal["simulation", "reported"]
    evidence_ref: EvidenceRef
    verification_status: Literal["verified", "unverified"] = "unverified"

    @model_validator(mode="after")
    def validate_event(self):
        require_timezone(self.earliest_start_at)
        require_timezone(self.effective_at)
        if self.kind == "train_delay":
            if self.activity_id is None or self.earliest_start_at is None:
                raise ValueError("列车晚点必须指定活动和最早开始时间")
            if self.poi_id is not None or self.effective_at is not None:
                raise ValueError("列车晚点不能带景区关闭字段")
        else:
            if self.poi_id is None or self.effective_at is None:
                raise ValueError("景区关闭必须指定地点和生效时间")
            if self.activity_id is not None or self.earliest_start_at is not None:
                raise ValueError("景区关闭不能带列车晚点字段")
        return self


class PutEvent(EventFacts):
    request_id: Identifier
    expected_event_revision: int = Field(ge=0)


class RevisionTokens(Contract):
    base_version: int = Field(ge=1)
    event_revision: int = Field(ge=0)
    history_revision: int = Field(ge=0)


class CreateDraft(RevisionTokens):
    request_id: Identifier
    draft_id: Identifier
    plan: TravelPlan
    handled_event_ids: list[Identifier]

    @model_validator(mode="after")
    def unique_events(self):
        if len(self.handled_event_ids) != len(set(self.handled_event_ids)):
            raise ValueError("异常ID不得重复")
        return self


class ConfirmDraft(RevisionTokens):
    request_id: Identifier
    user_confirmed: Literal[True]
    confirmed_by: Identifier

    @field_validator("user_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("用户确认必须为JSON布尔值true")
        return value


class LockActivities(Contract):
    request_id: Identifier
    base_version: int = Field(ge=1)
    history_revision: int = Field(ge=0)
    activity_ids: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_activities(self):
        if len(self.activity_ids) != len(set(self.activity_ids)):
            raise ValueError("锁定活动ID不得重复")
        return self


class Confirmation(Contract):
    request_id: Identifier
    confirmed_by: Identifier
    confirmed_at: datetime


class VersionView(Contract):
    trip_id: str
    version: int
    event_revision: int
    history_revision: int
    source_draft_id: str | None
    plan: TravelPlan
    budget: BudgetResult
    validation: ValidatePlanResult
    confirmation: Confirmation | None
    created_at: datetime


class EventView(EventFacts):
    event_id: str
    revision: int


class DraftView(RevisionTokens):
    trip_id: str
    draft_id: str
    handled_event_ids: list[str]
    status: Literal["pending", "stale", "committed"]
    committed_version: int | None
    plan: TravelPlan
    validation: ValidatePlanResult
    created_at: datetime


class TripView(Contract):
    trip_id: str
    title: str
    current_version: int
    event_revision: int
    history_revision: int
    constraints: TripConstraints
    locked_activity_ids: list[str]
    current_plan: VersionView
    events: list[EventView]
