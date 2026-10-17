from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Charge(BaseModel):
    id: str = Field(min_length=1)
    amount_cny: Decimal = Field(ge=0, decimal_places=2)
    status: Literal["paid", "planned"]


class Refund(BaseModel):
    id: str = Field(min_length=1)
    amount_cny: Decimal = Field(ge=0, decimal_places=2)
    status: Literal["received", "pending"]


class BudgetRequest(BaseModel):
    budget_cny: Decimal = Field(ge=0, decimal_places=2)
    charges: list[Charge] = Field(default_factory=list)
    refunds: list[Refund] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_ids(self):
        ids = [x.id for x in [*self.charges, *self.refunds]]
        if len(ids) != len(set(ids)):
            raise ValueError("费用流水ID不得重复，避免重复计费")
        paid = sum((x.amount_cny for x in self.charges if x.status == "paid"), Decimal(0))
        received = sum((x.amount_cny for x in self.refunds if x.status == "received"), Decimal(0))
        if received > paid:
            raise ValueError("已到账退款不能超过当前行程已支付费用")
        return self


class BudgetResult(BaseModel):
    budget_cny: Decimal
    paid_cny: Decimal
    planned_cny: Decimal
    received_refunds_cny: Decimal
    pending_refunds_cny: Decimal
    conservative_total_cny: Decimal
    remaining_cny: Decimal
    within_budget: bool


class Activity(BaseModel):
    id: str = Field(min_length=1)
    poi_id: str = Field(min_length=1)
    start_at: datetime
    end_at: datetime
    transport_minutes_from_previous: int | None = Field(default=None, ge=0)
    walking_minutes_from_previous: int | None = Field(default=None, ge=0)
    opening_status: Literal["confirmed_open", "confirmed_closed", "unknown"] = "unknown"
    booking_required: bool = False
    booking_status: Literal["confirmed", "not_confirmed", "unknown"] = "unknown"

    @model_validator(mode="after")
    def valid_interval(self):
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("活动时间必须带有时区")
        if self.end_at <= self.start_at:
            raise ValueError("活动结束时间必须晚于开始时间")
        return self


class ValidatePlanRequest(BaseModel):
    activities: list[Activity] = Field(min_length=1)
    budget: BudgetRequest | None = None
    max_walking_minutes_per_leg: int | None = Field(default=None, ge=0)
    return_deadline: datetime | None = None
    arrival_at_return_station: datetime | None = None
    locked_activities: list[Activity] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_metadata(self):
        ids = [a.id for a in self.activities]
        if len(ids) != len(set(ids)):
            raise ValueError("行程活动ID不得重复")
        for timestamp in (self.return_deadline, self.arrival_at_return_station):
            if timestamp is not None and timestamp.tzinfo is None:
                raise ValueError("返程时间必须带有时区")
        locked_ids = [a.id for a in self.locked_activities]
        if len(locked_ids) != len(set(locked_ids)):
            raise ValueError("锁定活动ID不得重复")
        return self


class Check(BaseModel):
    name: str
    status: Status
    detail: str


class ValidatePlanResult(BaseModel):
    overall: Status
    checks: list[Check]
    note: str = "仅验证请求中提供的约束与状态；外部事实真实性需单独核验。"
