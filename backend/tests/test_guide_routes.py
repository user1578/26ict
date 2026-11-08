from decimal import Decimal

import httpx
import pytest

from app.amap_adapter import AmapAdapter
from app.external_schemas import Coordinates, RouteRequest, SearchPlacesRequest
from app.provider_http import ProviderHTTP
from app.recommendations import RecommendationEngine
from test_recommendations import engine, request


@pytest.mark.parametrize('payload,expected', [
    ({'errcode': 0, 'errmsg': 'OK', 'data': {'paths': [{'distance': 1500, 'duration': 450}]}}, 'PASS'),
    ({'errcode': 0, 'errmsg': 'OK', 'data': {'paths': []}}, 'UNKNOWN'),
    ({'errcode': 10001, 'errmsg': 'ERROR'}, 'UNKNOWN'),
    ({'errcode': 0, 'data': {'paths': [{'distance': 100, 'duration': -1}]}}, 'UNKNOWN'),
])
def test_bicycling_uses_official_v4_and_retains_unknown_prices(monkeypatch, payload, expected):
    monkeypatch.setenv('AMAP_API_KEY', 'fixture-not-real')
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = AmapAdapter(ProviderHTTP(client, data_type='simulated')).get_route_options(RouteRequest(
            origin=Coordinates(longitude=120.15, latitude=30.25),
            destination=Coordinates(longitude=120.16, latitude=30.26), modes=['bicycling']))
    assert calls[0].url.path == '/v4/direction/bicycling'
    assert calls[0].url.scheme == 'https'
    assert result.results[0].status == expected
    if expected == 'PASS':
        assert result.results[0].data[0].duration_seconds == 450
        assert result.results[0].data[0].cost_cny is None
    assert 'fixture-not-real' not in result.model_dump_json()


def test_nearby_search_uses_real_location_and_keeps_unavailable_commercial_facts_unknown(monkeypatch):
    monkeypatch.setenv('AMAP_API_KEY', 'fixture-not-real')
    def handler(req):
        assert req.url.path == '/v3/place/around'
        assert req.url.params['location'] == '120.150000,30.250000'
        assert req.url.params['keywords'] == '火锅'
        return httpx.Response(200, json={'status':'1','pois':[
            {'id':'food-1','name':'测试餐厅','location':'120.16,30.26','address':'测试路','adname':'上城区'}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=AmapAdapter(ProviderHTTP(client,data_type='simulated')).search_places(SearchPlacesRequest(
            city='杭州',keywords='火锅',location=Coordinates(longitude=120.15,latitude=30.25),limit=3))
    assert result.status == 'PASS'
    assert result.data[0].district == '上城区'
    assert result.data[0].name == '测试餐厅'


def test_transport_preferences_exclude_disallowed_and_known_walking_violations():
    subject=engine()
    body=request().model_copy(update={'allowed_modes':['walking'], 'max_walking_minutes_per_leg':10})
    response=subject.amap.get_route_options(RouteRequest(origin=Coordinates(longitude=120,latitude=30),
        destination=Coordinates(longitude=120.01,latitude=30.01),city='杭州'))
    # Fixture walking is 15 minutes; transit is shorter walking but is not permitted.
    assert subject.choose(response,'balanced',body) is None
    body=body.model_copy(update={'allowed_modes':['transit','walking']})
    assert subject.choose(response,'balanced',body)['mode']=='transit'


def test_candidates_use_allowed_modes_and_accurate_relative_labels():
    subject=engine()
    body=request().model_copy(update={'allowed_modes':['walking'], 'max_walking_minutes_per_leg':None})
    bundle=subject.recommend(body)
    assert all(r.modes == ['walking'] for r in subject.amap.routes)
    assert all(l['selected'] is None or l['selected']['mode']=='walking'
               for c in bundle['candidates'] for l in c['legs'])
    for c in bundle['candidates']:
        if '少步行' in c['label']:
            assert c['walking_minutes'] is not None
            assert c['walking_minutes'] == min(x['walking_minutes'] for x in bundle['candidates'] if x['walking_minutes'] is not None)


def test_no_feasible_route_is_not_recommended_as_usable():
    result=engine().recommend(request().model_copy(update={'allowed_modes':['walking'], 'max_walking_minutes_per_leg':0}))
    assert all(not c['recommended'] for c in result['candidates'])
    assert all(c['feasibility'] == 'infeasible' for c in result['candidates'])
    assert all(c['validation']['overall'] != 'PASS' for c in result['candidates'])


def test_lodging_is_included_in_evening_and_morning_routes_without_inventing_availability():
    subject=engine()
    body=request().model_copy(update={'lodging_poi_id':'amap:hotel-0','lodging_name':'杭州测试酒店0'})
    result=subject.recommend(body)
    for candidate in result['candidates']:
        stay=next(a for a in candidate['plan']['activities'] if a['id'].endswith('-stay'))
        assert stay['poi_id']=='amap:hotel-0'
        assert stay['opening_status']=='unknown'
        assert stay['booking_status']=='unknown'
        assert any(l['activity_id']==stay['id'] and l['selected'] for l in candidate['legs'])
        assert any(l['from_name']=='杭州测试酒店0' and l['selected'] for l in candidate['legs'])
        assert candidate['validation']['overall']!='PASS'


def test_guide_uses_daily_locations_and_retains_unknown_hotel_and_food_prices():
    from app.travel_guide import GuideRequest, build_guide
    subject=engine()
    result=subject.recommend(request())
    visits=[day['place'] for day in result['candidates'][0]['days'] if day['date']=='2026-11-10']
    guide=build_guide(GuideRequest(city='杭州',on_date='2026-11-10',visits=visits,
                                 hotel_keyword='酒店',food_keyword='火锅'),subject)
    assert guide['hotels']['data'][0]['poi_id']=='amap:hotel-0'
    assert guide['hotel_routes']['to_hotel']['selected']
    assert guide['availability']=='unknown'
    assert guide['price_cny'] is None and guide['rating'] is None
    assert {m['period'] for m in guide['meals']}=={'lunch','dinner'}
    assert all(m['route']['selected'] for m in guide['meals'])
    assert all(m['price_cny'] is None and m['opening_status']=='unknown' for m in guide['meals'])


def test_nearby_http_requires_auth_and_invalid_coordinates_cannot_reach_provider(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.recommendation_api import recommendation_engine
    monkeypatch.setenv('TRAVELGUARD_DB_PATH',str(tmp_path/'guide.local.sqlite3'))
    monkeypatch.setenv('TRAVELGUARD_TOOL_API_KEY','guide-test')
    app.dependency_overrides[recommendation_engine]=engine
    body={'city':'杭州','on_date':'2026-11-10','visits':[
        {'poi_id':'amap:1','name':'景点','location':{'longitude':120.1,'latitude':30.2}}]}
    try:
        with TestClient(app) as client:
            assert client.post('/api/guide/nearby',json=body).status_code==401
            good=client.post('/api/guide/nearby',json=body,headers={'X-Tool-Key':'guide-test'})
            assert good.status_code==200
            assert good.json()['hotels']['evidence']['data_type']=='simulated'
            body['visits'][0]['location']=None
            assert client.post('/api/guide/nearby',json=body,headers={'X-Tool-Key':'guide-test'}).status_code==422
    finally:
        app.dependency_overrides.clear()


def test_bicycling_network_timeout_is_unknown(monkeypatch):
    monkeypatch.setenv('AMAP_API_KEY','fixture-not-real')
    def fail(req):
        raise httpx.ReadTimeout('fixture timeout',request=req)
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        result=AmapAdapter(ProviderHTTP(client)).get_route_options(RouteRequest(
            origin=Coordinates(longitude=120.1,latitude=30.2),
            destination=Coordinates(longitude=120.2,latitude=30.3),modes=['bicycling']))
    assert result.results[0].code=='provider_timeout'
    assert result.results[0].data is None


def test_transit_departure_uses_trip_day_and_china_local_time(monkeypatch):
    from datetime import datetime
    monkeypatch.setenv('AMAP_API_KEY','fixture-not-real')
    def handler(req):
        assert req.url.params['date']=='2026-11-10'
        assert req.url.params['time']=='09:00'
        return httpx.Response(200,json={'status':'1','route':{'transits':[]}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response=AmapAdapter(ProviderHTTP(client)).get_route_options(RouteRequest(
            origin=Coordinates(longitude=120,latitude=30),destination=Coordinates(longitude=120.01,latitude=30.01),
            modes=['transit'],city='杭州',departure_at=datetime.fromisoformat('2026-11-10T01:00:00+00:00')))
    assert response.results[0].code=='no_route'


def test_replan_changed_transport_refreshes_future_durations_and_does_not_invent_distinct_options(tmp_path):
    from app.travel_schemas import CreateTrip, TripView
    from app.travel_store import TravelStore
    subject=engine()
    bundle=subject.recommend(request())
    chosen=next(c for c in bundle['candidates'] if c['validation']['overall']=='PASS')
    store=TravelStore(tmp_path/'preference.local.sqlite3');store.initialize()
    trip=TripView.model_validate(store.create_trip(CreateTrip.model_validate({**bundle['trip_request'],
        'request_id':'pref-create','trip_id':'pref','plan':chosen['plan']})))
    result=subject.recommend(request().model_copy(update={'allowed_modes':['walking']}),trip)
    for candidate in result['candidates']:
        assert all(a['transport_minutes_from_previous']==15 for a in candidate['plan']['activities'][1:])
        assert all(l['selected']['mode']=='walking' for l in candidate['legs'] if l['selected'])
        assert '每天减少' not in candidate['reason']
    signatures=[[(a['poi_id'],a['start_at'],a['end_at']) for a in c['plan']['activities']] for c in result['candidates']]
    assert len(signatures)==len({str(s) for s in signatures})
