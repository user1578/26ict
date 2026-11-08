"""Read-only lodging and meal suggestions from the same AMap adapter."""
from datetime import date
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from .external_schemas import Coordinates, Mode, Place, SearchPlacesRequest
from .recommendations import RecommendationInput, json_value, stamp
from .travel_schemas import Contract

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class GuideRequest(Contract):
    city: Text
    on_date: date
    visits: list[Place] = Field(min_length=1, max_length=6)
    next_day_first: Place | None = None
    next_day_date: date | None = None
    hotel_keyword: Text = '酒店'
    food_keyword: Text = '地方小吃'
    allowed_modes: list[Mode] = Field(default_factory=lambda: ['transit', 'walking'], min_length=1, max_length=4)
    max_walking_minutes_per_leg: int | None = Field(default=20, ge=0, le=240)

    @model_validator(mode='after')
    def usable_locations(self):
        if any(place.location is None for place in self.visits):
            raise ValueError('周边推荐必须提供景点坐标')
        if len(set(self.allowed_modes)) != len(self.allowed_modes):
            raise ValueError('出行方式不得重复')
        return self


def build_guide(body: GuideRequest, engine):
    center = Coordinates(
        longitude=sum(p.location.longitude for p in body.visits)/len(body.visits),
        latitude=sum(p.location.latitude for p in body.visits)/len(body.visits),
    )
    first, last = body.visits[0], body.visits[-1]
    hotels = engine.amap.search_places(SearchPlacesRequest(city=body.city, keywords=body.hotel_keyword,
        location=center, radius_meters=3000, types='100000', limit=3))
    context = RecommendationInput(origin_city=body.city, city=body.city, arrival_station=first.name,
        return_station=last.name, start_date=body.on_date, end_date=body.on_date, budget_cny='999999',
        allowed_modes=body.allowed_modes, max_walking_minutes_per_leg=body.max_walking_minutes_per_leg)

    def route(origin, destination, day, clock):
        departure = stamp(day, clock)
        response = engine.route(origin, destination, context, departure)
        return {'selected': engine.choose(response, 'balanced', context),
                'departure_at': departure.isoformat(), 'options': json_value(response) if response else None}

    hotel_routes = None
    if hotels.data:
        hotel = next((p for p in hotels.data if p.location), None)
        if hotel:
            hotel_routes = {'hotel_id': hotel.poi_id, 'to_hotel': route(last, hotel, body.on_date, '18:00'),
                            'next_morning': route(hotel, body.next_day_first, body.next_day_date, '08:30')
                            if body.next_day_first and body.next_day_date else None}
    meals = []
    for period, clock, anchor in [('lunch', '12:00–13:00', first), ('dinner', '18:00–19:00', last)]:
        result = engine.amap.search_places(SearchPlacesRequest(city=body.city, keywords=body.food_keyword,
            location=anchor.location, radius_meters=1500, types='050000', limit=3))
        nearby = next((p for p in result.data or [] if p.location), None)
        meals.append({'period': period, 'suggested_time': clock, 'anchor': json_value(anchor),
            'candidates': json_value(result), 'route': route(anchor, nearby, body.on_date, clock[:5]) if nearby else None,
            'price_cny': None, 'rating': None, 'opening_status': 'unknown',
            'note': '用餐时段供参考，未固定加入正式活动；请核对当天时间与营业状态。'})
    district = first.district or body.city
    return {'on_date': body.on_date.isoformat(),
        'area': {'name': f'{district} · {first.name}周边', 'center': json_value(center),
                 'basis': '按当天景点分布推导的住宿搜索区域，不是官方酒店评级。'},
        'hotels': json_value(hotels), 'hotel_routes': hotel_routes, 'meals': meals,
        'price_cny': None, 'rating': None, 'availability': 'unknown',
        'note': '酒店价格、评分、营业状态和房态未取得。选择住宿后会重新计算景点往返交通，不执行预订。'}
