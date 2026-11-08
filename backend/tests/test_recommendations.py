from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.external_schemas import (Coordinates, Place, PlaceRules, RouteModeResult, RouteOption,
    RouteResponse, ToolResult, WeatherData)
from app.provider_http import ProviderHTTP, ProviderFailure, unknown
from app.recommendations import RecommendationInput, RecommendationEngine

TZ = timezone(timedelta(hours=8))


class MapFixture:
    def __init__(self, broken=False):
        self.queries = []
        self.routes = []
        self.broken = broken
        self.http = ProviderHTTP(None, data_type='simulated')

    def search_places(self, request):
        self.queries.append(request)
        data = [Place(poi_id=f'amap:fixture-{i}', name=request.city + ('博物馆' if i % 2 else '公园') + str(i),
            address=request.city, location=Coordinates(longitude=120+i/100, latitude=30+i/100),
            indoor=bool(i % 2)) for i in range(8)]
        if '站' in request.keywords:
            data = [Place(poi_id='amap:station', name=request.city+'站', location=Coordinates(longitude=120, latitude=30))]
        return ToolResult(status='PASS', code='ok', message='SIMULATED', evidence=self.http.evidence('amap','simulation:map'), data=data)

    def get_route_options(self, request):
        self.routes.append(request)
        results = []
        for mode in request.modes:
            seconds = 900 if mode == 'walking' else 600
            cost = Decimal('3.00') if mode == 'transit' else None
            data = None if self.broken else [RouteOption(duration_seconds=seconds, distance_meters=1000,
                walking_seconds=seconds if mode == 'walking' else 120, cost_cny=cost)]
            results.append(RouteModeResult(mode=mode, status='UNKNOWN' if self.broken else 'PASS', code='no_route' if self.broken else 'ok',
                message='SIMULATED', evidence=self.http.evidence('amap','simulation:route'), data=data))
        return RouteResponse(status='UNKNOWN' if self.broken else 'PASS', results=results)


class WeatherFixture:
    def get_weather_risk(self, request):
        start = datetime.combine(request.on_date, datetime.min.time(), TZ)
        return ToolResult(status='PASS', code='ok', message='SIMULATED',
            evidence=ProviderHTTP(None, data_type='simulated').evidence('qweather','simulation:weather'),
            data=WeatherData(on_date=request.on_date, forecast_start_at=start, forecast_end_at=start+timedelta(days=1),
                temperature_max_c=22, temperature_min_c=15, precipitation_mm=20, max_wind_speed_mps=2,
                conditions=['雨'], risk_check='FAIL', risk_factors=['precipitation']))


class RuleFixture:
    def __init__(self, known=True):
        self.known = known

    def get_place_rules(self, request):
        if not self.known:
            return unknown('local_rules', None, ProviderFailure('missing_rules_source','fixture missing'))
        return ToolResult(status='PASS', code='ok', message='SIMULATED test facts only',
            evidence=ProviderHTTP(None, data_type='simulated').evidence('local_rules','simulation:opening'),
            data=PlaceRules(poi_id=request.poi_id, opening_status='confirmed_open', booking_required=False,
                ticket_price_cny=Decimal('10'), valid_from=request.visit_start_at, valid_until=request.visit_end_at))


def request(city='杭州'):
    return RecommendationInput(origin_city='上海', city=city, arrival_station='杭州站', return_station='杭州站',
        start_date=date(2026,11,10), end_date=date(2026,11,11), budget_cny='1000', party_size=2,
        max_walking_minutes_per_leg=20, arrival_time='09:00', return_time='17:00', other_costs_cny='200')


def engine(known=True, broken=False):
    return RecommendationEngine(MapFixture(broken), WeatherFixture(), RuleFixture(known))


def test_real_input_drives_three_distinct_multiday_candidates_and_source_labels():
    subject = engine()
    result = subject.recommend(request())
    assert len(result['candidates']) == 3
    assert all(q.city == '杭州' for q in subject.amap.queries)
    assert {c['profile'] for c in result['candidates']} == {'balanced','less_walking','weather'}
    assert len({str(c['plan']) for c in result['candidates']}) == 3
    for c in result['candidates']:
        assert {a['start_at'][:10] for a in c['plan']['activities']} == {'2026-11-10','2026-11-11'}
        assert c['days'] and c['legs'] and c['unverified']
        assert c['known_cost_cny'] != '0.00'
        assert c['validation']['overall'] in ('PASS','FAIL','UNKNOWN')
    assert subject.amap.routes
    second = engine().recommend(request('南京'))
    assert all('南京' in p['name'] for p in second['places'] if p['poi_id'] != 'amap:station')


def test_missing_rules_or_routes_never_fabricate_pass_or_zero_travel_time():
    result = engine(known=False, broken=True).recommend(request())
    assert len(result['candidates']) == 3
    for c in result['candidates']:
        assert c['validation']['overall'] != 'PASS'
        assert any(a['opening_status'] == 'unknown' for a in c['plan']['activities'])
        assert any(leg['selected'] is None for leg in c['legs'])
        assert c['plan']['arrival_at_return_station'] is None


def test_fully_supplied_indoor_candidate_can_use_existing_formal_lifecycle(tmp_path, monkeypatch):
    from app.main import app
    from app.recommendation_api import recommendation_engine
    from app.travel_schemas import CreateTrip
    monkeypatch.setenv('TRAVELGUARD_DB_PATH', str(tmp_path / 'isolated.local.sqlite3'))
    monkeypatch.setenv('TRAVELGUARD_TOOL_API_KEY','integration-test')
    app.dependency_overrides[recommendation_engine] = engine
    try:
        with TestClient(app, headers={'X-Tool-Key':'integration-test'}) as client:
            body = request().model_dump(mode='json')
            response = client.post('/api/recommendations', json=body)
            assert response.status_code == 200
            bundle = response.json()
            candidate = next(c for c in bundle['candidates'] if c['validation']['overall'] == 'PASS')
            create = {**bundle['trip_request'], 'request_id':'create-fixture','trip_id':'fixture', 'plan':candidate['plan']}
            assert CreateTrip.model_validate(create)
            r = client.post('/api/trips',json=create)
            assert r.status_code == 201, r.text
            event = {'request_id':'event-fixture','expected_event_revision':0,'kind':'train_delay','active':True,
                'activity_id':candidate['plan']['activities'][0]['id'],
                'earliest_start_at': '2026-11-10T10:30:00+08:00','source':'simulation',
                'evidence_ref':'simulation:delay','verification_status':'verified'}
            assert client.put('/api/trips/fixture/events/E1',json=event).status_code == 200
            changed = client.post('/api/trips/fixture/recommendations',json=body)
            assert changed.status_code == 200, changed.text
            original_day2 = [a for a in candidate['plan']['activities'] if a['start_at'].startswith('2026-11-11')]
            candidate2 = next(c for c in changed.json()['candidates'] if c['validation']['overall'] == 'PASS')
            assert [a for a in candidate2['plan']['activities'] if a['start_at'].startswith('2026-11-11')] == original_day2
            draft = {'request_id':'draft-fixture','draft_id':'D1','base_version':1,'event_revision':1,'history_revision':0,
                'handled_event_ids':['E1'],'plan':candidate2['plan']}
            assert client.post('/api/trips/fixture/drafts',json=draft).status_code == 201
            confirm = {'request_id':'confirm-fixture','base_version':1,'event_revision':1,'history_revision':0,
                'user_confirmed':True,'confirmed_by':'fixture-user'}
            url='/api/trips/fixture/drafts/D1/confirm'
            assert client.post(url,json=confirm).json()['version'] == 2
            assert client.post(url,json=confirm).json()['version'] == 2
            assert len(client.get('/api/trips/fixture/versions').json()) == 2
            assert client.get('/api/trips/fixture').json()['current_version'] == 2
    finally:
        app.dependency_overrides.clear()


def test_dropping_a_visit_requeries_new_neighbor_edge_and_preserves_locks():
    from app.travel_schemas import TripView
    subject=engine()
    bundle=subject.recommend(request())
    candidate=next(c for c in bundle['candidates'] if c['validation']['overall']=='PASS')
    plan=candidate['plan']
    # Make every historical duration visibly different from fresh route data.
    for a in plan['activities'][1:]:
        a['transport_minutes_from_previous']=99
        a['walking_minutes_from_previous']=19
    event={'event_id':'E1','revision':1,'kind':'poi_closed','active':True,
        'poi_id':plan['activities'][1]['poi_id'],'effective_at':'2026-11-10T08:00:00+08:00',
        'source':'simulation','evidence_ref':'simulation:closure','verification_status':'verified'}
    trip=TripView.model_validate({'trip_id':'fixture','title':'test','current_version':1,'event_revision':1,
        'history_revision':1,'city':'杭州','party_size':2,'start_date':'2026-11-10','end_date':'2026-11-11',
        'constraints':{'budget_cny':'1000','max_walking_minutes_per_leg':20,'return_deadline':'2026-11-11T17:00:00+08:00'},
        'locked_activity_ids':[plan['activities'][0]['id']],'events':[event],
        'current_plan':{'trip_id':'fixture','version':1,'event_revision':0,'history_revision':1,
            'source_draft_id':None,'plan':plan,'budget':{'budget_cny':'1000','paid_cny':'0','planned_cny':'0',
                'received_refunds_cny':'0','pending_refunds_cny':'0','conservative_total_cny':'0','remaining_cny':'1000','within_budget':True},
            'validation':{'overall':'PASS','checks':[],'note':'test'},'confirmation':None,'created_at':'2026-11-09T00:00:00Z'}})
    result=subject.recommend(request(),trip)
    dropped=next(c for c in result['candidates'] if c['profile']=='less_walking')
    assert dropped['plan']['activities'][0] == plan['activities'][0]
    first_day2=next(a for a in dropped['plan']['activities'] if a['start_at'].startswith('2026-11-11'))
    assert first_day2['transport_minutes_from_previous']==10
    assert first_day2['walking_minutes_from_previous']==2
    assert first_day2['start_at']=='2026-11-11T09:00:00+08:00'


def test_replan_preserves_external_charges_refunds_evidence_and_marks_reconciliation_unknown(tmp_path):
    from app.travel_store import TravelStore
    from app.travel_schemas import CreateTrip, TripView
    subject=engine()
    bundle=subject.recommend(request())
    candidate=next(c for c in bundle['candidates'] if c['validation']['overall']=='PASS')
    plan=candidate['plan']
    plan['charges']=[{'id':'estimate-recommendation','status':'paid','amount_cny':'100.00'},
        {'id':'insurance','status':'planned','amount_cny':'100.00'}]
    plan['refunds']=[{'id':'estimate-recommendation-next','status':'received','amount_cny':'5.00'}]
    plan['financial_evidence']={'estimate-recommendation':'simulation:payment',
        'insurance':'simulation:insurance','estimate-recommendation-next':'simulation:refund'}
    store=TravelStore(tmp_path/'finance.local.sqlite3');store.initialize()
    trip=TripView.model_validate(store.create_trip(CreateTrip.model_validate({**bundle['trip_request'],
        'request_id':'finance-create','trip_id':'finance','plan':plan})))
    result=subject.recommend(request(),trip)
    for candidate in result['candidates']:
        output=candidate['plan']
        assert plan['charges'][0] in output['charges']
        assert plan['charges'][1] in output['charges']
        assert output['refunds']==plan['refunds']
        for key,value in plan['financial_evidence'].items():
            assert output['financial_evidence'][key]==value
        ids=[x['id'] for x in output['charges']+output['refunds']]
        assert len(ids)==len(set(ids))
        assert candidate['cost_complete'] is False
        assert candidate['validation']['overall'] != 'PASS'
