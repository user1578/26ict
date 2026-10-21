from typing import Annotated

from fastapi import APIRouter, Depends
import httpx

from .amap_adapter import AmapAdapter
from .external_schemas import (
    Place, PlaceRules, PlaceRulesRequest, RouteRequest, RouteResponse, SearchPlacesRequest,
    ToolResult, WeatherData, WeatherRequest,
)
from .place_rules import LocalRuleStore
from .provider_http import ProviderHTTP
from .qweather_adapter import QWeatherAdapter

router = APIRouter(prefix="/api/tools", tags=["外部数据工具"])


def provider_http():
    # No retries, redirects, or implicit proxy credentials. At most three route calls.
    with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
        yield ProviderHTTP(client)


HTTP = Annotated[ProviderHTTP, Depends(provider_http)]


@router.post("/search-places", response_model=ToolResult[list[Place]], operation_id="search_places")
def search_places(body: SearchPlacesRequest, http: HTTP):
    return AmapAdapter(http).search_places(body)


@router.post("/get-place-rules", response_model=ToolResult[PlaceRules], operation_id="get_place_rules")
def get_place_rules(body: PlaceRulesRequest):
    return LocalRuleStore().get_place_rules(body)


@router.post("/get-route-options", response_model=RouteResponse, operation_id="get_route_options")
def get_route_options(body: RouteRequest, http: HTTP):
    return AmapAdapter(http).get_route_options(body)


@router.post("/get-weather-risk", response_model=ToolResult[WeatherData], operation_id="get_weather_risk")
def get_weather_risk(body: WeatherRequest, http: HTTP):
    return QWeatherAdapter(http).get_weather_risk(body)
