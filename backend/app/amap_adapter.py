"""AMap v3 POI and route reference adapter; no booking or payment operations."""

from decimal import Decimal, InvalidOperation
from datetime import timedelta, timezone
import os

from pydantic import ValidationError

from .external_schemas import (
    Coordinates, Place, RouteModeResult, RouteOption, RouteRequest, RouteResponse,
    SearchPlacesRequest, ToolResult,
)
from .provider_http import ProviderFailure, ProviderHTTP, unknown

BASE = "https://restapi.amap.com/v3"


def integer(value) -> int:
    if isinstance(value, bool):
        raise ValueError("invalid integer")
    number = Decimal(str(value))
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise ValueError("invalid integer")
    return int(number)


def optional_text(value) -> str | None:
    # AMap documents [] for absent string values.
    if value in (None, "", []):
        return None
    if not isinstance(value, str):
        raise ValueError("invalid text")
    return value


class AmapAdapter:
    def __init__(self, http: ProviderHTTP):
        self.http = http

    def _get(self, path, params):
        key = os.getenv("AMAP_API_KEY", "").strip()
        if not key:
            raise ProviderFailure("missing_credentials", "尚未配置高德Web服务密钥AMAP_API_KEY")
        url = "https://restapi.amap.com" + path if path.startswith("/v4/") else BASE + path
        result = self.http.get(url, params={**params, "key": key, "output": "JSON"})
        success = type(result.get("errcode")) is int and result["errcode"] == 0 if path.startswith("/v4/") else result.get("status") == "1"
        if not success:
            raise ProviderFailure("provider_error", "高德未返回成功结果，请检查服务权限、配额或请求条件")
        return result

    def search_places(self, body: SearchPlacesRequest):
        path = "/place/around" if body.location else "/place/text"
        try:
            params = {"keywords": body.keywords, "city": body.city,
                      "citylimit": "true", "offset": body.limit, "page": 1}
            if body.location:
                params.update(location=body.location.amap_value(), radius=body.radius_meters, sortrule="distance")
            if body.types:
                params["types"] = body.types
            result = self._get(path, params)
            places = []
            rows = result["pois"]
            if not isinstance(rows, list):
                raise ValueError("invalid pois")
            for row in rows:
                if not isinstance(row["id"], str) or not row["id"].strip():
                    raise ValueError("missing poi id")
                position = optional_text(row.get("location"))
                location = None
                if position:
                    lon, lat = position.split(",")
                    location = Coordinates(longitude=lon, latitude=lat)
                places.append(Place(poi_id="amap:" + row["id"], name=row["name"],
                                    address=optional_text(row.get("address")), location=location,
                                    category=optional_text(row.get("type")),
                                    district=optional_text(row.get("adname")),
                                    indoor=True if "博物馆" in str(row.get("type", "")) else None))
            return ToolResult(status="PASS", code="ok", message="候选地点仅供选择；开放、票价和预约需另查规则",
                              evidence=self.http.evidence("amap", BASE + path), data=places[:body.limit])
        except ProviderFailure as failure:
            return unknown("amap", BASE + path, failure)
        except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation, ValidationError):
            return unknown("amap", BASE + path, ProviderFailure("invalid_provider_data", "高德地点数据不完整或格式错误"))

    def get_route_options(self, body: RouteRequest) -> RouteResponse:
        results = [self._route(body, mode) for mode in body.modes]
        return RouteResponse(status="PASS" if all(x.status == "PASS" for x in results) else "UNKNOWN",
                             results=results)

    def _route(self, body, mode):
        path = "/v4/direction/bicycling" if mode == "bicycling" else "/direction/" + ("transit/integrated" if mode == "transit" else mode)
        source = "https://restapi.amap.com" + path if mode == "bicycling" else BASE + path
        try:
            params = {"origin": body.origin.amap_value(), "destination": body.destination.amap_value()}
            if mode == "transit":
                params["city"] = body.city
                if body.departure_at:
                    departure = body.departure_at.astimezone(timezone(timedelta(hours=8)))
                    params["date"] = departure.date().isoformat()
                    params["time"] = departure.strftime("%H:%M")
                if body.destination_city:
                    params["cityd"] = body.destination_city
            result = self._get(path, params)
            rows = result["data"]["paths"] if mode == "bicycling" else result["route"]["transits" if mode == "transit" else "paths"]
            if not isinstance(rows, list):
                raise ValueError("invalid routes")
            options = []
            for row in rows[:3]:
                walking = integer(row["duration"]) if mode == "walking" else None
                if mode == "bicycling" and isinstance(row.get("steps"), list) and row["steps"]:
                    # Only explicit dismount/pushing sections count as walking. Bike availability is separate.
                    walking = sum(integer(s["duration"]) for s in row["steps"]
                                  if any(word in str(s.get("instruction", "")) for word in ("推行", "推车", "步行")))
                if mode == "transit":
                    # Missing walking durations stay unknown, never turn into zero.
                    segments = row.get("segments")
                    if isinstance(segments, list) and segments:
                        durations = [s.get("walking", {}).get("duration") for s in segments]
                        if all(d not in (None, "", []) for d in durations):
                            walking = sum(integer(d) for d in durations)
                cost = optional_text(row.get("cost")) if mode == "transit" else None
                options.append(RouteOption(duration_seconds=integer(row["duration"]),
                                           distance_meters=integer(row["distance"]),
                                           walking_seconds=walking, cost_cny=cost))
            if not options:
                raise ProviderFailure("no_route", "当前条件下未返回可用路线，不能推断交通耗时为零")
            return RouteModeResult(mode=mode, status="PASS", code="ok", message="查询时刻的路线估算；不保证未来班次和耗时",
                                   evidence=self.http.evidence("amap", source), data=options)
        except ProviderFailure as failure:
            result = unknown("amap", source, failure)
        except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation, ValidationError):
            result = unknown("amap", source, ProviderFailure("invalid_provider_data", "高德路线数据不完整或格式错误"))
        return RouteModeResult(mode=mode, **result.model_dump())
