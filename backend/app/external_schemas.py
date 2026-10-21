"""External tools expose availability separately from business validation."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field, StringConstraints, model_validator

from .schemas import Status
from .travel_schemas import Contract, EvidenceRef, Identifier, require_timezone

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Mode = Literal["walking", "transit", "driving"]


class Coordinates(Contract):
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)

    def amap_value(self) -> str:
        return f"{self.longitude:.6f},{self.latitude:.6f}"


class SearchPlacesRequest(Contract):
    keywords: Text
    city: Text
    limit: int = Field(default=10, ge=1, le=25)


class Place(Contract):
    poi_id: Identifier
    name: Text
    address: str | None = None
    location: Coordinates | None = None
    coordinate_system: Literal["GCJ-02"] = "GCJ-02"


class RouteRequest(Contract):
    origin: Coordinates
    destination: Coordinates
    coordinate_system: Literal["GCJ-02"] = "GCJ-02"
    modes: list[Mode] = Field(default_factory=lambda: ["walking", "transit", "driving"], min_length=1, max_length=3)
    city: Text | None = None
    destination_city: Text | None = None

    @model_validator(mode="after")
    def valid_modes(self):
        if len(set(self.modes)) != len(self.modes):
            raise ValueError("交通方式不得重复")
        if "transit" in self.modes and self.city is None:
            raise ValueError("公交路线必须提供起点城市，跨城时还需destination_city")
        return self


class RouteOption(Contract):
    duration_seconds: int = Field(ge=0)
    distance_meters: int = Field(ge=0)
    walking_seconds: int | None = Field(default=None, ge=0)
    cost_cny: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class WeatherRequest(Contract):
    location: Coordinates
    coordinate_system: Literal["WGS84"] = "WGS84"
    on_date: date
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    activity_type: Literal["outdoor", "indoor"] = "outdoor"


class WeatherData(Contract):
    on_date: date
    forecast_start_at: datetime
    forecast_end_at: datetime
    temperature_max_c: float
    temperature_min_c: float
    precipitation_mm: float = Field(ge=0)
    max_wind_speed_mps: float = Field(ge=0)
    conditions: list[str]
    risk_check: Status
    risk_factors: list[str]
    risk_policy: str = "outdoor-v1"
    note: str = "逐日预报与本地阈值仅供活动筛选；未查询气象预警，不代表安全保证。"


class PlaceRulesRequest(Contract):
    poi_id: Identifier
    visit_start_at: datetime
    visit_end_at: datetime

    @model_validator(mode="after")
    def interval(self):
        require_timezone(self.visit_start_at)
        require_timezone(self.visit_end_at)
        if self.visit_end_at <= self.visit_start_at:
            raise ValueError("访问结束时间必须晚于开始时间")
        return self


class PlaceRules(Contract):
    poi_id: Identifier
    opening_status: Literal["confirmed_open", "confirmed_closed", "unknown"] = "unknown"
    booking_required: bool | None = None
    booking_note: Text | None = None
    ticket_price_cny: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    valid_from: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def validity(self):
        require_timezone(self.valid_from)
        require_timezone(self.valid_until)
        if self.valid_until <= self.valid_from:
            raise ValueError("规则有效期错误")
        return self


class RuleRecord(PlaceRules):
    source_ref: EvidenceRef
    retrieved_at: datetime
    data_type: Literal["real", "simulated"]
    verification_status: Literal["verified", "unverified"]

    @model_validator(mode="after")
    def evidence_time(self):
        require_timezone(self.retrieved_at)
        return self


class RuleBook(Contract):
    records: list[RuleRecord]


class Evidence(Contract):
    source: Literal["amap", "qweather", "local_rules"]
    source_ref: str | None = None
    fetched_at: datetime
    source_updated_at: datetime | None = None
    data_type: Literal["real", "simulated", "unknown"] = "unknown"
    verification_status: Literal["source_reported", "verified", "unverified"] = "unverified"
    attributions: list[str] = Field(default_factory=list)


T = TypeVar("T")


class ToolResult(Contract, Generic[T]):
    status: Literal["PASS", "UNKNOWN"]
    code: str
    message: str
    evidence: Evidence
    data: T | None = None


class RouteModeResult(ToolResult[list[RouteOption]]):
    mode: Mode


class RouteResponse(Contract):
    status: Literal["PASS", "UNKNOWN"]
    results: list[RouteModeResult]
