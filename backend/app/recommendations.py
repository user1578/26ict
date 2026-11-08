"""Explainable, bounded rule recommendations. No AgentArts calls or store writes.

All source adapters are shared with /api/tools. A request-scoped cache prevents
repeated provider calls. Missing evidence is retained, never filled with fixtures.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from math import ceil, cos, radians
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from .external_schemas import Mode, PlaceRulesRequest, RouteRequest, SearchPlacesRequest, WeatherRequest
from .schemas import Check, Status
from .travel_schemas import Contract, TravelPlan, TripConstraints
from .travel_validation import validate_snapshot

TZ = timezone(timedelta(hours=8))
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Clock = Annotated[str, StringConstraints(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')]
PROFILES = [('balanced', '均衡路线', '平衡交通时间、步行、已知费用与天气风险'),
            ('less_walking', '少步行备选', '优先较少步行，可能增加交通费用或减少游览'),
            ('weather', '天气友好备选', '优先室内候选；室内属性推断与天气未知均单独标明')]




class RecommendationInput(Contract):
    origin_city: Text
    city: Text
    arrival_station: Text
    return_station: Text
    keywords: Text = '风景名胜'
    start_date: date
    end_date: date
    party_size: int = Field(default=1, ge=1, le=10, strict=True)
    budget_cny: Decimal = Field(ge=0, decimal_places=2)
    max_walking_minutes_per_leg: int | None = Field(default=20, ge=0, le=240)
    arrival_time: Clock = '09:00'
    return_time: Clock = '17:00'
    stay_together: bool = True
    other_costs_cny: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    allowed_modes: list[Mode] = Field(default_factory=lambda: ['transit','walking'], min_length=1, max_length=4)
    lodging_poi_id: Text | None = None
    lodging_name: Text | None = None

    @model_validator(mode='after')
    def dates(self):
        if len(set(self.allowed_modes)) != len(self.allowed_modes):
            raise ValueError('出行方式不得重复')
        if (self.lodging_poi_id is None) != (self.lodging_name is None):
            raise ValueError('住宿选择必须同时提供地点ID与名称')
        if not 0 <= (self.end_date-self.start_date).days < 7:
            raise ValueError('旅行须为1至7日，结束不早于开始日期')
        if self.start_date == self.end_date and self.arrival_time >= self.return_time:
            raise ValueError('当天抵达时间必须早于到达返程站的截止时间')
        return self


def stamp(day, clock):
    return datetime.combine(day, time.fromisoformat(clock), TZ)


def json_value(value):
    return value.model_dump(mode='json')


class RecommendationEngine:
    def __init__(self, amap, weather, rules):
        self.amap, self.weather, self.rules = amap, weather, rules
        self.route_cache = {}
        self.weather_cache = {}

    def route(self, origin, destination, body, departure_at=None):
        if not origin or not destination or not origin.location or not destination.location:
            return None
        departure_at=departure_at or stamp(body.start_date,body.arrival_time)
        key = (origin.poi_id, destination.poi_id, departure_at.isoformat())
        if key not in self.route_cache:
            self.route_cache[key] = self.amap.get_route_options(RouteRequest(origin=origin.location,
                destination=destination.location, city=body.city, modes=body.allowed_modes, departure_at=departure_at))
        return self.route_cache[key]

    def weather_on(self, day, place):
        if not place or not place.location:
            return None
        key = (day, place.poi_id)
        if key not in self.weather_cache:
            self.weather_cache[key] = self.weather.get_weather_risk(WeatherRequest(
                location=place.location, coordinate_system='GCJ-02', on_date=day, activity_type='outdoor'))
        return self.weather_cache[key]

    def choose(self, response, profile, body):
        choices = []
        if response:
            for result in response.results:
                if result.status != 'PASS' or result.mode not in body.allowed_modes:
                    continue
                for route in result.data or []:
                    walking = route.walking_seconds
                    walking = ceil(walking/60) if walking is not None else None
                    if body.max_walking_minutes_per_leg is not None and walking is not None and walking > body.max_walking_minutes_per_leg:
                        continue
                    duration = ceil(route.duration_seconds/60)
                    cost = route.cost_cny
                    score = duration + (walking if walking is not None else 100)* (6 if profile == 'less_walking' else 2)
                    score += float(cost or 0) * (2 if profile == 'balanced' else .5)
                    if cost is None:
                        score += 100
                    if walking is None and body.max_walking_minutes_per_leg is not None:
                        score += 10000
                    choices.append((score, {'mode':result.mode, **json_value(route),
                        'duration_minutes':duration, 'walking_minutes':walking,
                        'cost_cny':format(cost, '.2f') if cost is not None else None,
                        'evidence':json_value(result.evidence)}))
        return min(choices, key=lambda x:x[0])[1] if choices else None

    @staticmethod
    def distance_order(origin, place):
        # Geographic proximity only orders search candidates. Never used as a travel-time estimate.
        if not origin or not origin.location or not place.location:
            return float('inf')
        a,b=origin.location,place.location
        return (a.latitude-b.latitude)**2+((a.longitude-b.longitude)*cos(radians(a.latitude)))**2

    def initial_activities(self, pool, days, arrival, lodging, profile, body):
        available=list(pool)
        activities=[]
        previous=arrival
        per_day=1 if profile=='less_walking' else 2
        for day_index,day in enumerate(days):
            if day_index and lodging:
                previous=lodging
            for slot in range(per_day):
                ranked=sorted(available,key=lambda p:(p.indoor is not True if profile=='weather' else False,
                                                     self.distance_order(previous,p),p.poi_id))
                # Bound real provider requests. Try nearby alternatives before retaining an unknown/conflict.
                options=[]
                for place in ranked[:3]:
                    departure=(datetime.fromisoformat(activities[-1]['end_at']) if activities and datetime.fromisoformat(activities[-1]['end_at']).date()==day else stamp(day,body.arrival_time if day_index==0 else '08:30'))
                    route=self.choose(self.route(previous,place,body,departure),profile,body)
                    if route:
                        score=route['duration_minutes']+(route['walking_minutes'] or 0)*(6 if profile=='less_walking' else 1)
                        if profile=='weather' and place.indoor is not True:
                            score+=1000
                        options.append((score,place))
                place=min(options,key=lambda x:x[0])[1] if options else (ranked[0] if ranked else None)
                if not place:
                    break
                available.remove(place)
                start=stamp(day,body.arrival_time if day_index==0 else '09:00')+timedelta(hours=slot*5)
                activities.append({'id':f'd{day_index+1}-visit{slot+1}','poi_id':place.poi_id,
                    'start_at':start.isoformat(),'end_at':(start+timedelta(minutes=90)).isoformat(),
                    'transport_minutes_from_previous':None,'walking_minutes_from_previous':None,
                    'opening_status':'unknown','booking_required':True,'booking_status':'unknown'})
                previous=place
            if lodging and day_index<len(days)-1:
                activities.append({'id':f'd{day_index+1}-stay','poi_id':lodging.poi_id,
                    'start_at':stamp(day,'18:00').isoformat(),'end_at':stamp(day+timedelta(days=1),'08:30').isoformat(),
                    'transport_minutes_from_previous':None,'walking_minutes_from_previous':None,
                    'opening_status':'unknown','booking_required':True,'booking_status':'unknown'})
                previous=lodging
        return activities

    @staticmethod
    def route_conflict(response, body):
        known=[r for result in response.results for r in (result.data or [])
               if result.mode in body.allowed_modes and result.status=='PASS'] if response else []
        return bool(known) and body.max_walking_minutes_per_leg is not None and all(
            r.walking_seconds is not None and ceil(r.walking_seconds/60)>body.max_walking_minutes_per_leg for r in known)

    def recommend(self, body, trip=None):
        # A fresh engine is used for each request; maps and rules aren't persisted as trusted facts.
        self.route_cache.clear()
        self.weather_cache.clear()
        searches = [self.amap.search_places(SearchPlacesRequest(city=body.city, keywords=body.keywords, limit=12)),
                    self.amap.search_places(SearchPlacesRequest(city=body.city, keywords='博物馆', limit=8))]
        places = {}
        for result in searches:
            for place in result.data or []:
                if place.location:
                    places[place.poi_id] = place
        stations = []
        for query in (body.arrival_station, body.return_station):
            result = self.amap.search_places(SearchPlacesRequest(city=body.city, keywords=query, limit=3))
            searches.append(result)
            stations.append((result.data or [None])[0])
        arrival, returning = stations
        lodging=None
        if body.lodging_poi_id and body.lodging_name:
            stay=self.amap.search_places(SearchPlacesRequest(city=body.city,keywords=body.lodging_name,limit=10))
            lodging=next((p for p in stay.data or [] if p.poi_id==body.lodging_poi_id and p.location),None)
        pool = list(places.values())[:18]
        if lodging:
            places[lodging.poi_id]=lodging
        days = [body.start_date+timedelta(days=i) for i in range((body.end_date-body.start_date).days+1)]
        candidates = []
        for index, (profile, label, reason) in enumerate(PROFILES):
            if trip:
                plan = json_value(trip.current_plan.plan)
                active = [e for e in trip.events if e.active]
                locked = set(trip.locked_activity_ids)
                used = {a['poi_id'] for a in plan['activities']}
                closed = {e.poi_id for e in active if e.kind == 'poi_closed'}
                for event in active:
                    if event.kind == 'poi_closed':
                        for activity in list(plan['activities']):
                            if activity['poi_id'] != event.poi_id or datetime.fromisoformat(activity['end_at']) <= event.effective_at:
                                continue
                            if activity['id'] in locked:
                                continue  # validator records the conflict; history remains immutable
                            alternatives = [p for p in pool if p.poi_id not in used | closed]
                            if index == 1 or not alternatives:
                                plan['activities'].remove(activity)
                                plan['activity_evidence'].pop(activity['id'], None)
                            else:
                                replacement = sorted(alternatives, key=lambda p:(p.indoor is not True, p.poi_id))[0 if index == 2 else -1]
                                old_id = activity['id']
                                activity['id'] = old_id[:100]+'-alt-'+str(index)
                                activity['poi_id'] = replacement.poi_id
                                activity['booking_status'] = 'unknown'
                                activity['opening_status'] = 'unknown'
                                activity['transport_minutes_from_previous'] = None
                                activity['walking_minutes_from_previous'] = None
                                plan['activity_evidence'].pop(old_id, None)
                                used.add(replacement.poi_id)
                    else:
                        for activity in plan['activities']:
                            if activity['id'] == event.activity_id and activity['id'] not in locked:
                                start = datetime.fromisoformat(activity['start_at'])
                                if start < event.earliest_start_at:
                                    duration = datetime.fromisoformat(activity['end_at'])-start
                                    activity['start_at'] = event.earliest_start_at.isoformat()
                                    activity['end_at'] = (event.earliest_start_at+duration).isoformat()
                delays = [e for e in active if e.kind == 'train_delay']
                if delays:
                    target = next((a for a in plan['activities'] if a['id']==delays[0].activity_id), None)
                    if target:
                        day = datetime.fromisoformat(target['start_at']).astimezone(TZ).date()
                        if index == 1:
                            optional = [a for a in plan['activities'] if a['id'] != target['id']
                                and a['id'] not in locked and a['booking_status'] != 'confirmed'
                                and datetime.fromisoformat(a['start_at']).astimezone(TZ).date()==day]
                            if optional:
                                removed=optional[-1]
                                plan['activities'].remove(removed)
                                plan['activity_evidence'].pop(removed['id'],None)
                        if index == 2 and target['id'] not in locked and target['booking_status'] != 'confirmed':
                            start=datetime.fromisoformat(target['start_at'])
                            target['end_at']=min(datetime.fromisoformat(target['end_at']),start+timedelta(minutes=60)).isoformat()
                activities = plan['activities']
                if lodging:
                    for stay in activities:
                        if stay['id'].endswith('-stay') and stay['id'] not in locked:
                            stay['poi_id']=lodging.poi_id
                    for day_index, day in enumerate(days[:-1]):
                        current=[a for a in activities if datetime.fromisoformat(a['start_at']).astimezone(TZ).date()==day]
                        if current and not any(a['id'].endswith('-stay') for a in current):
                            last_today=current[-1]
                            activities.insert(activities.index(last_today)+1, {
                                'id':f'd{day_index+1}-stay','poi_id':lodging.poi_id,
                                'start_at':stamp(day,'18:00').isoformat(),
                                'end_at':stamp(day+timedelta(days=1),'08:30').isoformat(),
                                'transport_minutes_from_previous':None,'walking_minutes_from_previous':None,
                                'opening_status':'unknown','booking_required':True,'booking_status':'unknown'})
            else:
                activities=self.initial_activities(pool,days,arrival,lodging,profile,body)
                plan = {'activities':activities, 'charges':[], 'refunds':[], 'activity_evidence':{},
                        'financial_evidence':{}, 'arrival_at_return_station':None}
            unverified = ['开放、预约及票价以对应访问时段的规则为准；路线是查询时刻估算，不保证未来班次。',
                f'{body.origin_city}至{body.city}的长途交通及住宿需自行核实；第一天从目的地抵达点约定时间开始。',
                '室内属性来自地点分类推断，尚未核实；未取得真实预约或付款凭证。']
            legs, day_views = [], []
            known = Decimal(0)
            incomplete_cost = body.other_costs_cny is None
            uncertain = False
            dangerous = False
            last = None
            walking_total = duration_total = 0
            weather_penalty = 0
            if body.lodging_poi_id and not lodging:
                uncertain=True
                unverified.append('所选住宿地点未能重新取得，住宿往返路线未知。')
            for activity in activities:
                original = None
                if trip:
                    original = next((a for a in trip.current_plan.plan.activities if a.id == activity['id']), None)
                place = places.get(activity['poi_id'])
                start = datetime.fromisoformat(activity['start_at'])
                end = datetime.fromisoformat(activity['end_at'])
                duration = end-start
                origin = places.get(last['poi_id']) if last else arrival
                departure=datetime.fromisoformat(last['end_at']) if last else stamp(body.start_date,body.arrival_time)
                if last and departure.astimezone(TZ).date()!=start.astimezone(TZ).date():
                    departure=stamp(start.astimezone(TZ).date(),'08:30')
                response = self.route(origin, place, body, departure)
                selected = self.choose(response, profile, body)
                leg = {'from_name':origin.name if origin else '坐标未知', 'to_name':place.name if place else activity['poi_id'],
                       'activity_id':activity['id'], 'selected':selected,
                       'options':json_value(response) if response else None, 'date':start.date().isoformat(), 'departure_at':departure.isoformat()}
                legs.append(leg)
                if selected:
                    travel = selected['duration_minutes']
                    incoming_walk=selected['walking_minutes']
                    earliest = departure+timedelta(minutes=travel)
                    if start < earliest:
                        if not trip or activity['id'] not in trip.locked_activity_ids:
                            start = earliest
                            if activity['id'].endswith('-stay'):
                                if start >= end:
                                    end=start+timedelta(minutes=1)
                                    dangerous=True
                            else:
                                end=start+duration
                            activity['start_at'],activity['end_at'] = start.isoformat(),end.isoformat()
                        else:
                            dangerous=True
                            unverified.append('当前交通估算与锁定活动的固定时间冲突；历史活动保持原样。')
                    if not trip or activity['id'] not in trip.locked_activity_ids:
                        activity['transport_minutes_from_previous'] = travel if last else None
                        activity['walking_minutes_from_previous'] = incoming_walk if last else None
                    walking_total += selected['walking_minutes'] or 0
                    duration_total += travel
                    if selected['walking_minutes'] is None:
                        uncertain = True
                    elif body.max_walking_minutes_per_leg is not None and selected['walking_minutes'] > body.max_walking_minutes_per_leg:
                        dangerous = True
                    if selected['cost_cny'] is None:
                        incomplete_cost = True
                    else:
                        known += Decimal(selected['cost_cny'])*body.party_size
                else:
                    uncertain = True
                    if self.route_conflict(response,body):
                        dangerous=True
                        unverified.append('此路段在允许的出行方式内未找到符合步行限制的路线：'+leg['from_name']+'→'+leg['to_name'])
                    if not trip or activity['id'] not in trip.locked_activity_ids:
                        activity['transport_minutes_from_previous'] = None
                        activity['walking_minutes_from_previous'] = None
                # Locked and unchanged booked facts must not be fabricated or changed by refreshed rules.
                rule = self.rules.get_place_rules(PlaceRulesRequest(poi_id=activity['poi_id'], visit_start_at=start, visit_end_at=end))
                if not trip or activity['id'] not in trip.locked_activity_ids:
                    activity['opening_status'] = rule.data.opening_status if rule.status=='PASS' and rule.data else 'unknown'
                    activity['booking_required'] = rule.data.booking_required is not False if rule.data else True
                    if not (original and original.booking_status=='confirmed' and original.poi_id==activity['poi_id'] and original.start_at==start and original.end_at==end):
                        activity['booking_status'] = 'unknown'
                    if original and original.booking_status=='confirmed' and original.start_at==start and original.end_at==end:
                        pass
                    elif rule.status=='PASS' and rule.data:
                        plan['activity_evidence'][activity['id']] = rule.evidence.source_ref or 'unknown:rule-source'
                    else:
                        plan['activity_evidence'].pop(activity['id'],None)
                is_stay=activity['id'].endswith('-stay')
                if is_stay and (not trip or activity['id'] not in trip.locked_activity_ids):
                    activity['opening_status']='unknown'
                    activity['booking_required']=True
                    activity['booking_status']='unknown'
                    incomplete_cost=True
                if not is_stay and rule.data and rule.data.ticket_price_cny is not None:
                    known += rule.data.ticket_price_cny*body.party_size
                else:
                    incomplete_cost = True
                forecast = self.weather_on(start.date(), place)
                risk = forecast.data.risk_check if forecast and forecast.data else 'UNKNOWN'
                if risk=='UNKNOWN':
                    uncertain = True
                elif risk=='FAIL':
                    weather_penalty += 0 if place and place.indoor is True else 30
                    # Even inferred indoor places require an honest property caveat, not an outdoor safety claim.
                    if not place or place.indoor is not True:
                        dangerous = True
                    elif forecast.evidence.data_type == 'real':
                        uncertain = True
                day_views.append({'date':start.date().isoformat(), 'activity_id':activity['id'],
                    'place':json_value(place) if place else None, 'rules':json_value(rule),
                    'weather':json_value(forecast) if forecast else None,
                    'indoor_inferred':place.indoor if place else None,'kind':'lodging' if is_stay else 'visit'})
                if end.time() > time(18):
                    dangerous = True
                    unverified.append(activity['id']+'超出每日18:00游览窗口')
                last = activity
            arrival_at = None
            if last:
                response = self.route(places.get(last['poi_id']), returning, body, datetime.fromisoformat(last['end_at']))
                selected = self.choose(response, profile, body)
                legs.append({'from_name':places[last['poi_id']].name if last['poi_id'] in places else last['poi_id'],
                    'to_name':returning.name if returning else body.return_station, 'activity_id':None,
                    'selected':selected,'options':json_value(response) if response else None,'date':body.end_date.isoformat()})
                if selected:
                    arrival_at = datetime.fromisoformat(last['end_at'])+timedelta(minutes=selected['duration_minutes'])
                    walking_total += selected['walking_minutes'] or 0
                    duration_total += selected['duration_minutes']
                    if selected['walking_minutes'] is None:
                        uncertain = True
                    elif body.max_walking_minutes_per_leg is not None and selected['walking_minutes'] > body.max_walking_minutes_per_leg:
                        dangerous = True
                    if selected['cost_cny'] is None:
                        incomplete_cost = True
                    else:
                        known += Decimal(selected['cost_cny'])*body.party_size
                else:
                    uncertain = True
                    dangerous=dangerous or self.route_conflict(response,body)
                    if self.route_conflict(response,body):
                        unverified.append('到达返程站的末段路线超过所选步行限制。')
            plan['arrival_at_return_station'] = arrival_at.isoformat() if arrival_at else None
            known += body.other_costs_cny or Decimal(0)
            # Replace only this engine's tagged planned estimate. External ledgers are preserved.
            marker='rules-v1:aggregate-estimate'
            preserved=[c for c in plan['charges'] if not (c['status']=='planned'
                and plan['financial_evidence'].get(c['id'])==marker)]
            if preserved:
                incomplete_cost=True
                unverified.append('已有支付或其他费用与本次全量估算的覆盖关系未知；原流水已保留，需对账后才能确认，不能推断重复项已消除。')
            used_ids={c['id'] for c in preserved+plan['refunds']}
            estimate_id='estimate-recommendation'
            suffix=1
            while estimate_id in used_ids:
                estimate_id='estimate-recommendation-'+str(suffix)
                suffix+=1
            plan['charges']=preserved+[{'id':estimate_id,'status':'planned','amount_cny':format(known,'.2f')}]
            retained_ids={x['id'] for x in plan['charges']+plan['refunds']}
            plan['financial_evidence']={k:v for k,v in plan['financial_evidence'].items() if k in retained_ids}
            plan['financial_evidence'][estimate_id]=marker
            known+=sum((Decimal(c['amount_cny']) for c in preserved),Decimal(0))
            known-=sum((Decimal(r['amount_cny']) for r in plan['refunds'] if r['status']=='received'),Decimal(0))
            constraints = trip.constraints if trip else TripConstraints(budget_cny=body.budget_cny,
                max_walking_minutes_per_leg=body.max_walking_minutes_per_leg, return_deadline=stamp(body.end_date,body.return_time))
            if not activities:
                # Empty provider search is a genuine failure, never a seeded Wuhan itinerary.
                continue
            typed = TravelPlan.model_validate(plan)
            validation = validate_snapshot(typed,constraints,trip.events if trip else [],trip.locked_activity_ids if trip else [],
                trip.current_plan.plan if trip else None)
            covered = {datetime.fromisoformat(a['start_at']).date() for a in activities}
            if covered != set(days):
                uncertain = True
                unverified.append('缺少部分日期的候选地点；不以重复景点填充完整行程')
            validation.checks += [Check(name='recommendation_data',status=Status.UNKNOWN if uncertain or incomplete_cost else Status.PASS,
                detail='部分路线、天气、费用或日期覆盖未知' if uncertain or incomplete_cost else '查询数据完整；费用为计划估算'),
                Check(name='recommendation_risk',status=Status.FAIL if dangerous else Status.PASS,
                detail='存在天气、步行或每日时间窗口冲突' if dangerous else '已知首段、末段和每日窗口未发现冲突')]
            statuses={c.status for c in validation.checks}
            validation.overall=Status.FAIL if Status.FAIL in statuses else Status.UNKNOWN if Status.UNKNOWN in statuses else Status.PASS
            if incomplete_cost:
                unverified.append('费用不完整：下列金额仅为已知小计，缺失票价、交通或食宿/长途费用不得当作0元')
            score = round(walking_total*.7+duration_total*.2+float(known)*.03+weather_penalty,2)
            candidates.append({'profile':profile,'label':label,'reason':reason+('；延误后减少一项未预约游览以减少步行' if trip and index==1 else '；延误时将受影响游览缩短至最多60分钟，增加缓冲' if trip and index==2 else ''),'score':score,
                'ranking_note':'有限候选排序，非全局最优；先比较硬约束与证据，再比较步行×0.7+交通×0.2+已知费用×0.03+户外天气风险每处30分',
                'plan':json_value(typed),'days':day_views,'legs':legs,'known_cost_cny':format(known,'.2f'),
                'cost_complete':not incomplete_cost,'remaining_cny':format(body.budget_cny-known,'.2f'),
                'available_balance_cny':None if incomplete_cost else format(body.budget_cny-known,'.2f'),
                'paid_cny':format(sum((Decimal(c['amount_cny']) for c in plan['charges'] if c['status']=='paid'),Decimal(0)),'.2f'),
                'estimated_cny':format(sum((Decimal(c['amount_cny']) for c in plan['charges'] if c['status']=='planned'),Decimal(0)),'.2f'),
                'missing_costs':['部分门票、交通、住宿或餐饮尚无完整价格'] if incomplete_cost else [],
                'lodging':json_value(lodging) if lodging else None,
                'walking_minutes':None if any(not l['selected'] or l['selected']['walking_minutes'] is None for l in legs) else walking_total,
                'transport_minutes':None if any(not l['selected'] for l in legs) else duration_total,
                'unverified':unverified,'validation':json_value(validation)})
        distinct=[]
        seen=set()
        for candidate in candidates:
            signature=(tuple((a['poi_id'],a['start_at'],a['end_at']) for a in candidate['plan']['activities']),
                tuple((l['selected']['mode'],l['selected']['duration_minutes'],l['selected']['walking_minutes']) if l['selected'] else None for l in candidate['legs']))
            if signature not in seen:
                seen.add(signature)
                distinct.append(candidate)
        candidates=distinct
        candidates.sort(key=lambda c:({'PASS':0,'UNKNOWN':1,'FAIL':2}[c['validation']['overall']],c['score']))
        for rank,c in enumerate(candidates):
            c['rank']=rank+1
            c['feasibility']='infeasible' if c['validation']['overall']=='FAIL' else 'unverified' if c['validation']['overall']=='UNKNOWN' else 'feasible'
            c['recommended']=rank==0 and c['feasibility']!='infeasible' and all(l['selected'] for l in c['legs'])
            c['label']={'balanced':'均衡游览','less_walking':'轻松游览','weather':'室内优先'}[c['profile']]
            if c['profile']=='less_walking':
                old_count=sum(not a.id.endswith('-stay') for a in trip.current_plan.plan.activities) if trip else len(days)*2
                count=sum(not a['id'].endswith('-stay') for a in c['plan']['activities'])
                c['reason']=f'减少{old_count-count}项游览，留出休息与交通缓冲；取舍是景点较少。' if count<old_count else '保留景点安排，比较当前允许方式的实际交通与步行时间。'
            other=[x['walking_minutes'] for x in candidates if x is not c and x['walking_minutes'] is not None]
            if c['walking_minutes'] is not None and other and c['walking_minutes']<min(other):
                c['label']='少步行 · '+c['label']
            c['warnings']=[check['detail'] for check in c['validation']['checks'] if check['status'] in ('FAIL','UNKNOWN')]
        return {'generator':'rules-v1','format_version':2,'distinct_shortfall':max(0,3-len(candidates)),'agentarts_connected':False,'input':json_value(body),
            'places':[json_value(p) for p in places.values()], 'searches':[json_value(r) for r in searches],
            'arrival_candidates':[json_value(p) for p in (searches[-2].data or [])],
            'return_candidates':[json_value(p) for p in (searches[-1].data or [])],
            'candidates':candidates, 'trip_request':{'title':f'{body.city} · {body.start_date} 至 {body.end_date}',
                'city':body.city,'party_size':body.party_size,'start_date':body.start_date.isoformat(),'end_date':body.end_date.isoformat(),
                'preferences':{'stay_together':body.stay_together},'budget_cny':str(body.budget_cny),
                'max_walking_minutes_per_leg':body.max_walking_minutes_per_leg,
                'return_deadline':stamp(body.end_date,body.return_time).isoformat(),'locked_activity_ids':[]}}
