"""Provider calls use MockTransport only; no paid APIs or credentials."""

from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

KEY = {"X-Tool-Key": "external-test-key"}
client = TestClient(app)
NOW = datetime(2026, 10, 21, 2, tzinfo=timezone.utc)
SEARCH = {"keywords": "公园", "city": "武汉", "limit": 5}
ROUTE = {"origin": {"longitude": 114.30, "latitude": 30.50},
         "destination": {"longitude": 114.31, "latitude": 30.51},
         "modes": ["walking", "transit", "driving"], "city": "武汉"}
WEATHER = {"location": {"longitude": 114.30, "latitude": 30.50}, "on_date": "2026-10-21"}
RULES = {"poi_id": "amap:B-test", "visit_start_at": "2026-10-21T10:00:00+08:00",
         "visit_end_at": "2026-10-21T11:00:00+08:00"}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("TRAVELGUARD_TOOL_API_KEY", KEY["X-Tool-Key"])
    for name in ("AMAP_API_KEY", "QWEATHER_API_KEY", "QWEATHER_API_HOST", "TRAVELGUARD_RULES_PATH"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def provider(monkeypatch, settings):
    from app.external_api import provider_http
    from app.provider_http import ProviderHTTP
    for module in ("app.provider_http", "app.qweather_adapter", "app.place_rules"):
        monkeypatch.setattr(f"{module}.utc_now", lambda: NOW)
    state = {"requests": []}

    def dispatch(request):
        state["requests"].append(request)
        assert "handler" in state, "Unexpected network call"
        return state["handler"](request)

    with httpx.Client(transport=httpx.MockTransport(dispatch), timeout=5) as http:
        provider = ProviderHTTP(http, data_type="simulated")
        state["http"] = provider
        app.dependency_overrides[provider_http] = lambda: provider
        try:
            yield state
        finally:
            app.dependency_overrides.pop(provider_http)


def enable_provider(monkeypatch):
    monkeypatch.setenv("AMAP_API_KEY", "fake-amap-key")
    monkeypatch.setenv("QWEATHER_API_KEY", "fake-weather-key")
    monkeypatch.setenv("QWEATHER_API_HOST", "test.qweatherapi.com")


def weather_payload(**changes):
    period = {"condition": {"text": "模拟晴", "code": "100"},
              "wind": {"speed": {"value": 2, "unit": "m/s"}},
              "precipitation": {"amount": {"value": 0, "unit": "mm"}}}
    day = {"forecastStartTime": "2026-10-21T00:00:00+08:00",
           "forecastEndTime": "2026-10-22T00:00:00+08:00",
           "temperatureMax": {"value": 26, "unit": "°C"},
           "temperatureMin": {"value": 18, "unit": "°C"},
           "daytime": {**period, "forecastStartTime": "2026-10-21T07:00:00+08:00",
                       "forecastEndTime": "2026-10-21T19:00:00+08:00"},
           "nighttime": {**period, "forecastStartTime": "2026-10-21T19:00:00+08:00",
                         "forecastEndTime": "2026-10-22T07:00:00+08:00"}}
    day.update(changes)
    return {"metadata": {"attributions": ["https://developer.qweather.com/attribution.html"]},
            "days": [day]}


def rule_record(**changes):
    record = {"poi_id": RULES["poi_id"], "opening_status": "confirmed_open", "booking_required": True,
              "booking_note": "模拟预约依据", "ticket_price_cny": "20.00",
              "valid_from": "2026-10-21T09:00:00+08:00", "valid_until": "2026-10-21T17:00:00+08:00",
              "retrieved_at": NOW.isoformat(), "source_ref": "simulation:rule-source",
              "data_type": "simulated", "verification_status": "unverified"}
    record.update(changes)
    return record


def write_rules(tmp_path, monkeypatch, records):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("TRAVELGUARD_RULES_PATH", str(path))
    return path


def call(tool, body, headers=KEY):
    return client.post(f"/api/tools/{tool}", json=body, headers=headers)


@pytest.mark.parametrize("tool,body", [("search-places", SEARCH), ("get-route-options", ROUTE),
                                      ("get-weather-risk", WEATHER), ("get-place-rules", RULES)])
def test_missing_configuration_is_unknown_and_authenticated(tool, body):
    assert call(tool, body, {}).status_code == 401
    response = call(tool, body)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "UNKNOWN"
    if tool == "get-route-options":
        assert all(x["evidence"]["data_type"] == "unknown" for x in result["results"])
    else:
        assert result["evidence"]["data_type"] == "unknown"
        assert result["data"] is None


def test_search_mock_preserves_source_and_absent_location(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(200, json={"status": "1", "pois": [
        {"id": "B-test", "name": "模拟公园", "address": [], "location": "114.3,30.5"},
        {"id": "B-empty", "name": "模拟无坐标", "location": []}]})
    r = call("search-places", SEARCH)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["status"] == "PASS"
    assert result["data"][0]["poi_id"] == "amap:B-test"
    assert result["data"][0]["coordinate_system"] == "GCJ-02"
    assert result["data"][0]["address"] is None
    assert result["data"][1]["location"] is None
    assert result["evidence"]["data_type"] == "simulated"
    assert result["evidence"]["verification_status"] == "unverified"
    assert datetime.fromisoformat(result["evidence"]["fetched_at"].replace("Z", "+00:00")) == NOW
    request = provider["requests"][0]
    assert request.url.params["citylimit"] == "true"
    assert request.url.params["offset"] == "5"
    assert "fake-amap-key" not in r.text


def test_empty_search_is_a_known_empty_result(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(200, json={"status": "1", "pois": []})
    assert call("search-places", SEARCH).json()["data"] == []


@pytest.mark.parametrize("payload", [{"status": "1"}, {"status": "1", "pois": {}},
                                     {"status": "1", "pois": [{"id": "", "name": "x"}]},
                                     {"status": "1", "pois": [{"id": "x", "name": "x", "location": "NaN,1"}]}])
def test_malformed_poi_data_is_unknown(provider, monkeypatch, payload):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(200, json=payload)
    assert call("search-places", SEARCH).json()["code"] == "invalid_provider_data"


@pytest.mark.parametrize("failure,code", [("timeout", "provider_timeout"), ("connect", "provider_unavailable"),
                                        ("http", "provider_unavailable"), ("provider", "provider_error"),
                                        ("json", "invalid_provider_data"), ("stale", "stale_data"),
                                        ("redirect", "provider_unavailable")])
def test_provider_failures_are_unknown_without_leaking_credentials(provider, monkeypatch, failure, code):
    enable_provider(monkeypatch)

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-bearing-error-fake-amap-key", request=request)
        if failure == "connect":
            raise httpx.ConnectError("secret-bearing-error-fake-amap-key", request=request)
        if failure == "http":
            return httpx.Response(503, text="fake-amap-key")
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.invalid/?key=fake-amap-key"})
        if failure == "provider":
            return httpx.Response(200, json={"status": "0", "info": "fake-amap-key"})
        if failure == "json":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json={"status": "1", "pois": []}, headers={"Age": "3601"})

    provider["handler"] = handler
    r = call("search-places", SEARCH)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "UNKNOWN"
    assert r.json()["code"] == code
    assert r.json()["data"] is None
    assert "fake-amap-key" not in r.text
    assert len(provider["requests"]) == 1


def test_all_route_modes_mock_with_units_and_missing_walking(provider, monkeypatch):
    enable_provider(monkeypatch)

    def handler(request):
        if "transit" in request.url.path:
            assert request.url.params["city"] == "武汉"
            return httpx.Response(200, json={"status": "1", "route": {"transits": [
                {"distance": "2000", "duration": "1200", "cost": "2.00", "segments": [
                    {"walking": {"duration": "120"}}, {"walking": {"duration": "60"}}]}]}})
        return httpx.Response(200, json={"status": "1", "route": {"paths": [
            {"distance": "1000", "duration": "900"}]}})

    provider["handler"] = handler
    result = call("get-route-options", ROUTE).json()
    assert result["status"] == "PASS"
    walking, transit, driving = result["results"]
    assert walking["data"][0]["walking_seconds"] == 900
    assert transit["data"][0]["walking_seconds"] == 180
    assert transit["data"][0]["cost_cny"] == "2.00"
    assert driving["data"][0]["walking_seconds"] is None
    assert driving["data"][0]["cost_cny"] is None
    assert len(provider["requests"]) == 3


def test_partial_route_failure_and_no_route_are_not_zero_minutes(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["handler"] = lambda r: httpx.Response(200, json={"status": "1", "route": {
        "transits": [], "paths": [{"distance": "1000", "duration": "600"}]}})
    result = call("get-route-options", ROUTE).json()
    assert result["status"] == "UNKNOWN"
    assert result["results"][0]["status"] == "PASS"
    assert result["results"][1]["code"] == "no_route"
    assert result["results"][1]["data"] is None


def test_transit_missing_walking_is_not_assumed_zero(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(200, json={"status": "1", "route": {"transits": [
        {"distance": "1000", "duration": "600", "segments": [{"walking": {}}]}]}})
    result = call("get-route-options", {**ROUTE, "modes": ["transit"]}).json()
    assert result["results"][0]["data"][0]["walking_seconds"] is None


@pytest.mark.parametrize("duration", ["-1", "1.5", True, "NaN"])
def test_invalid_route_duration_is_unknown(provider, monkeypatch, duration):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(200, json={"status": "1", "route": {"paths": [
        {"distance": "1000", "duration": duration}]}})
    result = call("get-route-options", {**ROUTE, "modes": ["walking"]}).json()
    assert result["results"][0]["code"] == "invalid_provider_data"


def test_weather_mock_uses_v1_host_auth_units_and_attribution(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(200, json=weather_payload())
    response = call("get-weather-risk", WEATHER)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "PASS"
    assert result["data"]["risk_check"] == "PASS"
    assert result["data"]["temperature_max_c"] == 26
    assert result["evidence"]["data_type"] == "simulated"
    assert result["evidence"]["source_updated_at"] is None
    assert result["evidence"]["attributions"]
    request = provider["requests"][0]
    assert request.url.path == "/weather/v1/daily/30.500000/114.300000"
    assert request.headers["X-QW-Api-Key"] == "fake-weather-key"
    assert request.url.params["localTime"] == "true"
    assert "fake-weather-key" not in response.text


def test_weather_risk_policy_is_separate_from_data_availability(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(200, json=weather_payload(
        temperatureMax={"value": 36, "unit": "°C"}))
    result = call("get-weather-risk", WEATHER).json()
    assert result["status"] == "PASS"
    assert result["data"]["risk_check"] == "FAIL"
    assert "high_temperature" in result["data"]["risk_factors"]
    assert call("get-weather-risk", {**WEATHER, "activity_type": "indoor"}).json()["data"]["risk_check"] == "NOT_APPLICABLE"


@pytest.mark.parametrize("on_date", ["2026-10-20", "2026-10-28", "2026-11-18"])
def test_weather_outside_forecast_range_does_not_call_provider(provider, on_date):
    result = call("get-weather-risk", {**WEATHER, "on_date": on_date}).json()
    assert result["code"] == "forecast_out_of_range"
    assert result["data"] is None
    assert provider["requests"] == []


@pytest.mark.parametrize("kind", ["missing", "date_missing", "duplicate", "unit", "empty_conditions", "wrong_period"])
def test_incomplete_or_mismatched_weather_is_unknown(provider, monkeypatch, kind):
    enable_provider(monkeypatch)
    payload = weather_payload()
    day = payload["days"][0]
    if kind == "missing":
        day.pop("temperatureMax")
    elif kind == "date_missing":
        payload["days"] = []
    elif kind == "duplicate":
        payload["days"] *= 2
    elif kind == "unit":
        day["temperatureMax"]["unit"] = "°F"
    elif kind == "empty_conditions":
        day["daytime"]["condition"]["text"] = ""
    else:
        day["forecastEndTime"] = "2026-10-20T00:00:00+08:00"
    provider["handler"] = lambda _: httpx.Response(200, json=payload)
    result = call("get-weather-risk", WEATHER).json()
    assert result["status"] == "UNKNOWN"
    assert result["data"] is None


def test_weather_host_cannot_send_key_to_arbitrary_destination(provider, monkeypatch):
    enable_provider(monkeypatch)
    monkeypatch.setenv("QWEATHER_API_HOST", "127.0.0.1:8000")
    assert call("get-weather-risk", WEATHER).json()["code"] == "invalid_configuration"
    assert not provider["requests"]


def test_weather_service_unavailable_has_no_forecast(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(503, text="fake-weather-key")
    response = call("get-weather-risk", WEATHER)
    assert response.json()["code"] == "provider_unavailable"
    assert response.json()["data"] is None
    assert "fake-weather-key" not in response.text


@pytest.mark.parametrize("code", [None, "unknown", "999", "199"])
def test_unknown_weather_condition_does_not_pass(provider, monkeypatch, code):
    enable_provider(monkeypatch)
    payload = weather_payload()
    payload["days"][0]["daytime"]["condition"]["code"] = code
    provider["handler"] = lambda _: httpx.Response(200, json=payload)
    assert call("get-weather-risk", WEATHER).json()["status"] == "UNKNOWN"


def test_daytime_cannot_lie_outside_forecast_period(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["handler"] = lambda _: httpx.Response(200, json=weather_payload(
        forecastStartTime="2026-10-19T00:00:00+08:00", forecastEndTime="2026-10-20T00:00:00+08:00"))
    assert call("get-weather-risk", WEATHER).json()["status"] == "UNKNOWN"


@pytest.mark.parametrize("kind", ["old_night", "next_night", "missing_end", "reversed_end", "long_day"])
def test_weather_periods_must_match_the_requested_day(provider, monkeypatch, kind):
    enable_provider(monkeypatch)
    payload = weather_payload()
    day = payload["days"][0]
    if kind == "old_night":
        day["nighttime"]["forecastStartTime"] = "2026-10-19T19:00:00+08:00"
    elif kind == "next_night":
        day["nighttime"]["forecastStartTime"] = "2026-10-22T19:00:00+08:00"
    elif kind == "missing_end":
        day["nighttime"].pop("forecastEndTime")
    elif kind == "reversed_end":
        day["nighttime"]["forecastEndTime"] = "2026-10-21T06:00:00+08:00"
    else:
        day["forecastStartTime"] = "2026-10-20T00:00:00+08:00"
        day["forecastEndTime"] = "2026-10-23T00:00:00+08:00"
    provider["handler"] = lambda _: httpx.Response(200, json=payload)
    assert call("get-weather-risk", WEATHER).json()["status"] == "UNKNOWN"


def test_real_provider_marker_is_source_reported_not_independently_verified(provider, monkeypatch):
    enable_provider(monkeypatch)
    provider["http"].data_type = "real"  # still MockTransport; exercise production provenance branch
    provider["handler"] = lambda _: httpx.Response(200, json={"status": "1", "pois": []})
    evidence = call("search-places", SEARCH).json()["evidence"]
    assert evidence["data_type"] == "real"
    assert evidence["verification_status"] == "source_reported"


def test_verified_local_rule_with_evidence_covers_entire_visit(tmp_path, monkeypatch):
    write_rules(tmp_path, monkeypatch, [rule_record(data_type="real", verification_status="verified",
                                                  source_ref="https://example.invalid/official-rule")])
    result = call("get-place-rules", RULES).json()
    assert result["status"] == "PASS"
    assert result["data"]["booking_required"] is True
    assert result["data"]["ticket_price_cny"] == "20.00"
    assert "booking_status" not in result["data"]
    assert result["evidence"]["source_ref"] == "https://example.invalid/official-rule"
    assert result["evidence"]["verification_status"] == "verified"


@pytest.mark.parametrize("changes,code", [
    ({}, "unverified_rules"),
    ({"data_type": "real"}, "unverified_rules"),
    ({"data_type": "real", "verification_status": "verified", "booking_required": None}, "incomplete_rules"),
    ({"data_type": "real", "verification_status": "verified", "booking_note": None}, "incomplete_rules"),
    ({"data_type": "real", "verification_status": "verified", "ticket_price_cny": None}, "incomplete_rules"),
    ({"retrieved_at": (NOW - timedelta(days=8)).isoformat()}, "stale_rules"),
    ({"retrieved_at": (NOW + timedelta(days=1)).isoformat()}, "stale_rules"),
    ({"valid_until": "2026-10-21T10:30:00+08:00"}, "rules_not_found"),
    ({"source_ref": " "}, "invalid_rules_data"),
    ({"retrieved_at": "2026-10-21T00:00:00"}, "invalid_rules_data"),
])
def test_unreliable_rules_are_unknown_without_confirmed_facts(tmp_path, monkeypatch, changes, code):
    write_rules(tmp_path, monkeypatch, [rule_record(**changes)])
    result = call("get-place-rules", RULES).json()
    assert result["status"] == "UNKNOWN"
    assert result["code"] == code
    assert result["data"] is None


def test_conflicting_and_missing_rule_source(tmp_path, monkeypatch):
    path = write_rules(tmp_path, monkeypatch, [rule_record(), rule_record()])
    assert call("get-place-rules", RULES).json()["code"] == "rules_conflict"
    monkeypatch.setenv("TRAVELGUARD_RULES_PATH", str(path.with_name("missing.json")))
    assert call("get-place-rules", RULES).json()["code"] == "rules_unavailable"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setenv("TRAVELGUARD_RULES_PATH", str(path))
    assert call("get-place-rules", RULES).json()["code"] == "invalid_rules_data"


def test_partially_overlapping_closure_rule_blocks_open_rule(tmp_path, monkeypatch):
    opened = rule_record(data_type="real", verification_status="verified",
                         source_ref="https://example.invalid/open")
    closure = {**opened, "opening_status": "confirmed_closed",
               "valid_from": "2026-10-21T10:30:00+08:00", "source_ref": "https://example.invalid/closed"}
    write_rules(tmp_path, monkeypatch, [opened, closure])
    result = call("get-place-rules", RULES).json()
    assert result["status"] == "UNKNOWN"
    assert result["code"] == "rules_conflict"
    assert result["data"] is None


@pytest.mark.parametrize("tool,body", [
    ("search-places", {**SEARCH, "keywords": " "}),
    ("search-places", {**SEARCH, "limit": 26}),
    ("search-places", {**SEARCH, "api_key": "not-accepted"}),
    ("get-route-options", {**ROUTE, "origin": {"longitude": 181, "latitude": 0}}),
    ("get-route-options", {**ROUTE, "city": None}),
    ("get-route-options", {**ROUTE, "modes": ["walking", "walking"]}),
    ("get-route-options", {**ROUTE, "coordinate_system": "WGS84"}),
    ("get-weather-risk", {**WEATHER, "on_date": "invalid"}),
    ("get-weather-risk", {**WEATHER, "coordinate_system": "GCJ-02"}),
    ("get-weather-risk", {**WEATHER, "timezone": "UTC"}),
    ("get-place-rules", {**RULES, "visit_start_at": "2026-10-21T10:00:00"}),
    ("get-place-rules", {**RULES, "visit_end_at": RULES["visit_start_at"]}),
])
def test_invalid_input_is_422_without_network(provider, tool, body):
    assert call(tool, body).status_code == 422
    assert not provider["requests"]


def test_openapi_tool_names_and_existing_contracts_remain_available():
    paths = client.get("/openapi.json").json()["paths"]
    for tool in ("search-places", "get-place-rules", "get-route-options", "get-weather-risk"):
        assert paths[f"/api/tools/{tool}"]["post"]["operationId"] == tool.replace("-", "_")
    assert "/api/tools/calculate-budget" in paths
    assert "/api/tools/validate-plan" in paths
    assert "/api/trips/{trip_id}/drafts/{draft_id}/confirm" in paths
