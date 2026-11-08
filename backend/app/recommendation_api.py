"""Read-only planning boundary, replaceable by a future AgentArts planner."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from .amap_adapter import AmapAdapter
from .qweather_adapter import QWeatherAdapter
from .place_rules import LocalRuleStore
from .external_api import HTTP
from .recommendations import RecommendationEngine, RecommendationInput, stamp
from .travel_api import Store, PathId
from .travel_schemas import TripView

router = APIRouter(tags=['规则推荐'])


def recommendation_engine(http: HTTP):
    return RecommendationEngine(AmapAdapter(http), QWeatherAdapter(http), LocalRuleStore())


Engine = Annotated[RecommendationEngine, Depends(recommendation_engine)]


@router.post('/api/recommendations')
def recommend(body: RecommendationInput, engine: Engine):
    return engine.recommend(body)


@router.post('/api/trips/{trip_id}/recommendations')
def replan(trip_id: PathId, body: RecommendationInput, state: Store, engine: Engine):
    trip = TripView.model_validate(state.get_trip(trip_id))
    if (trip.city != body.city or trip.start_date != body.start_date or trip.end_date != body.end_date
            or trip.constraints.budget_cny != body.budget_cny
            or trip.constraints.max_walking_minutes_per_leg != body.max_walking_minutes_per_leg
            or trip.constraints.return_deadline is None
            or trip.constraints.return_deadline.isoformat() != stamp(body.end_date,body.return_time).isoformat()):
        raise HTTPException(409, detail={'code':'planning_context_conflict','message':'旅行与规划输入不一致，不能更改正式约束'})
    return engine.recommend(body, trip)
