/** 演示用“本地规划器”：B 端没有 /plan、/replan 接口，首版由 C 在前端生成
 *  模拟方案（初始 V1 与异常后的候选），再通过 B 的真实接口落库/核验。
 *  所有方案都带 simulation 证据引用，页面必须标注“模拟”。 */

import type {
  Activity,
  CreateDraftRequest,
  CreateTripRequest,
  EventView,
  PutEventRequest,
  TravelPlan,
  TripView,
} from '../types.ts'
import { cnyFromCents, planTotalCny, toCents } from './money.ts'
import { addMinutes, compareIso, toShanghaiIso } from './time.ts'
import { EVIDENCE, POI, poiName } from './dataset.ts'

export interface TripFormInput {
  city: string
  startDate: string
  endDate: string
  partySize: number
  budgetCny: string
  walkingLimit: number | null
  returnTime: string
  stayTogether: boolean
}

const OPENING_EVIDENCE_BY_POI: Record<string, string> = {
  [POI.hubeiMuseum]: EVIDENCE.openingHubeiMuseum,
  [POI.eastLakeGreenway]: EVIDENCE.openingEastLake,
  [POI.yellowCraneTower]: EVIDENCE.openingYellowCrane,
  [POI.hubuxiang]: EVIDENCE.openingHubuxiang,
  [POI.xinhaiMuseum]: EVIDENCE.openingXinhaiMuseum,
}

export function newId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `${prefix}-${uuid.slice(0, 8)}`
}

function initialActivities(input: TripFormInput): Activity[] {
  const first = input.startDate
  const second = input.endDate
  return [
    {
      id: 'visit-1',
      poi_id: POI.hubeiMuseum,
      start_at: toShanghaiIso(first, '10:00'),
      end_at: toShanghaiIso(first, '11:30'),
      transport_minutes_from_previous: null,
      walking_minutes_from_previous: null,
      opening_status: 'confirmed_open',
      booking_required: true,
      booking_status: 'confirmed',
    },
    {
      id: 'visit-2',
      poi_id: POI.eastLakeGreenway,
      start_at: toShanghaiIso(first, '14:00'),
      end_at: toShanghaiIso(first, '16:00'),
      transport_minutes_from_previous: 25,
      walking_minutes_from_previous: 10,
      opening_status: 'confirmed_open',
      booking_required: false,
      booking_status: 'unknown',
    },
    {
      id: 'visit-3',
      poi_id: POI.yellowCraneTower,
      start_at: toShanghaiIso(second, '09:00'),
      end_at: toShanghaiIso(second, '11:00'),
      transport_minutes_from_previous: 20,
      walking_minutes_from_previous: 12,
      opening_status: 'confirmed_open',
      booking_required: false,
      booking_status: 'unknown',
    },
    {
      id: 'visit-4',
      poi_id: POI.hubuxiang,
      start_at: toShanghaiIso(second, '12:00'),
      end_at: toShanghaiIso(second, '13:30'),
      transport_minutes_from_previous: 15,
      walking_minutes_from_previous: 5,
      opening_status: 'confirmed_open',
      booking_required: false,
      booking_status: 'unknown',
    },
  ]
}

export function buildInitialPlan(input: TripFormInput): TravelPlan {
  const activities = initialActivities(input)
  return {
    activities,
    charges: [
      { id: 'charge-ticket-yellow-crane', amount_cny: '70.00', status: 'paid' },
      { id: 'charge-transport', amount_cny: '320.00', status: 'planned' },
      { id: 'charge-hotel', amount_cny: '520.00', status: 'planned' },
      { id: 'charge-food', amount_cny: '140.00', status: 'planned' },
    ],
    refunds: [{ id: 'refund-transport', amount_cny: '35.00', status: 'pending' }],
    arrival_at_return_station: addMinutes(toShanghaiIso(input.endDate, input.returnTime), -30),
    activity_evidence: {
      'visit-1': EVIDENCE.openingHubeiMuseum,
      'visit-2': EVIDENCE.openingEastLake,
      'visit-3': EVIDENCE.openingYellowCrane,
      'visit-4': EVIDENCE.openingHubuxiang,
    },
    financial_evidence: {
      'charge-ticket-yellow-crane': EVIDENCE.paidYellowCraneTicket,
    },
  }
}

export function buildCreateTripRequest(input: TripFormInput): CreateTripRequest {
  const budget = cnyFromCents(toCents(input.budgetCny))
  return {
    request_id: newId('create'),
    trip_id: newId('trip'),
    title: `${input.city} · ${input.startDate} 至 ${input.endDate}`,
    city: input.city,
    party_size: input.partySize,
    start_date: input.startDate,
    end_date: input.endDate,
    preferences: { stay_together: input.stayTogether },
    budget_cny: budget,
    max_walking_minutes_per_leg: input.walkingLimit,
    return_deadline: toShanghaiIso(input.endDate, input.returnTime),
    locked_activity_ids: [],
    plan: buildInitialPlan(input),
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function ensureEvidence(plan: TravelPlan) {
  for (const activity of plan.activities) {
    if (activity.opening_status === 'confirmed_open' && !plan.activity_evidence[activity.id]) {
      const ref = OPENING_EVIDENCE_BY_POI[activity.poi_id]
      if (ref) plan.activity_evidence[activity.id] = ref
    }
  }
  for (const key of Object.keys(plan.activity_evidence)) {
    if (!plan.activities.some((activity) => activity.id === key)) {
      delete plan.activity_evidence[key]
    }
  }
}

function applyDelay(plan: TravelPlan, event: EventView) {
  if (event.kind !== 'train_delay' || !event.activity_id || !event.earliest_start_at) return
  const index = plan.activities.findIndex((activity) => activity.id === event.activity_id)
  if (index < 0) return
  const target = plan.activities[index]
  if (compareIso(target.start_at, event.earliest_start_at) >= 0) return
  const deltaMinutes = Math.round((Date.parse(event.earliest_start_at) - Date.parse(target.start_at)) / 60_000)
  for (let cursor = index; cursor < plan.activities.length; cursor += 1) {
    const activity = plan.activities[cursor]
    activity.start_at = addMinutes(activity.start_at, deltaMinutes)
    activity.end_at = addMinutes(activity.end_at, deltaMinutes)
  }
}

function applyClosure(plan: TravelPlan, event: EventView, mode: 'replace' | 'drop') {
  if (event.kind !== 'poi_closed' || !event.poi_id || !event.effective_at) return
  const conflicting = plan.activities.filter(
    (activity) =>
      activity.poi_id === event.poi_id &&
      compareIso(activity.end_at, event.effective_at as string) > 0,
  )
  if (mode === 'replace') {
    const usedPois = new Set(plan.activities.map((activity) => activity.poi_id))
    for (const activity of conflicting) {
      if (usedPois.has(POI.xinhaiMuseum)) continue
      const originalId = activity.id
      activity.id = `${originalId}-alt`
      activity.poi_id = POI.xinhaiMuseum
      activity.opening_status = 'confirmed_open'
      activity.booking_required = false
      activity.booking_status = 'unknown'
      delete plan.activity_evidence[originalId]
      plan.activity_evidence[activity.id] = EVIDENCE.openingXinhaiMuseum
      usedPois.add(POI.xinhaiMuseum)
    }
  } else {
    const removedIds = new Set(conflicting.map((activity) => activity.id))
    plan.activities = plan.activities.filter((activity) => !removedIds.has(activity.id))
    for (const id of removedIds) delete plan.activity_evidence[id]
  }
  plan.activities.sort((left, right) => compareIso(left.start_at, right.start_at))
}

export interface CandidatePlan {
  key: string
  label: string
  description: string
  plan: TravelPlan
}

/** 根据当前正式方案 + 全部 active 异常，生成演示候选（一个候选 = 一份完整 plan = 一个草案）。 */
export function buildCandidatePlans(trip: TripView): CandidatePlan[] {
  const active = trip.events.filter((event) => event.active)
  if (active.length === 0) return []
  const hasClosure = active.some((event) => event.kind === 'poi_closed')
  const hasDelay = active.some((event) => event.kind === 'train_delay')
  const modes: Array<'replace' | 'drop' | 'none'> = hasClosure ? ['replace', 'drop'] : ['none']
  const candidates: CandidatePlan[] = []

  for (const mode of modes) {
    const plan = clone(trip.current_plan.plan)
    for (const event of active) {
      applyDelay(plan, event)
    }
    if (mode !== 'none') {
      for (const event of active) {
        applyClosure(plan, event, mode)
      }
    }
    ensureEvidence(plan)
    if (plan.activities.length === 0) continue
    const labels =
      mode === 'replace'
        ? {
            key: 'replace',
            label: '替换闭馆地点',
            description: '把受闭馆影响的活动替换为辛亥革命博物院（模拟地点，模拟证据）。',
          }
        : mode === 'drop'
          ? {
              key: 'drop',
              label: '删减受影响活动',
              description: '移除受闭馆影响的活动，保留其余安排与已付费用事实。',
            }
          : {
              key: 'shift',
              label: '顺延受影响活动',
              description: '按晚点后的最早开始时间顺延活动，其余安排保持不变。',
            }
    const suffix = hasDelay && hasClosure ? '（含晚点顺延）' : ''
    candidates.push({ ...labels, description: labels.description + suffix, plan })
  }
  return candidates
}

export function buildDraftRequests(trip: TripView, candidates: CandidatePlan[]): CreateDraftRequest[] {
  const handled = trip.events.filter((event) => event.active).map((event) => event.event_id).sort()
  return candidates.map((candidate) => ({
    request_id: newId('draft'),
    draft_id: newId('D'),
    base_version: trip.current_version,
    event_revision: trip.event_revision,
    history_revision: trip.history_revision,
    handled_event_ids: handled,
    plan: candidate.plan,
  }))
}

export function nextEventId(trip: TripView): string {
  const used = trip.events
    .map((event) => Number.parseInt(event.event_id.replace(/^E/i, ''), 10))
    .filter((value) => Number.isFinite(value))
  const next = (used.length > 0 ? Math.max(...used) : 0) + 1
  return `E${next}`
}

/** 演示场景 1：东湖绿道段交通延误 45 分钟（模拟上报）。 */
export function buildDelayEvent(trip: TripView): PutEventRequest {
  const target =
    trip.current_plan.plan.activities.find((activity) => activity.poi_id === POI.eastLakeGreenway) ??
    trip.current_plan.plan.activities[1] ??
    trip.current_plan.plan.activities[0]
  return {
    request_id: newId('event'),
    expected_event_revision: trip.event_revision,
    kind: 'train_delay',
    active: true,
    activity_id: target.id,
    earliest_start_at: addMinutes(target.start_at, 45),
    poi_id: null,
    effective_at: null,
    source: 'simulation',
    evidence_ref: 'simulation:event:train-delay-45',
    verification_status: 'verified',
  }
}

/** 演示场景 2：黄鹤楼临时闭馆（模拟上报，生效时间为行程最后一天 08:00）。 */
export function buildClosureEvent(trip: TripView): PutEventRequest {
  const endDate = trip.end_date ?? trip.current_plan.plan.activities.at(-1)?.start_at.slice(0, 10) ?? ''
  return {
    request_id: newId('event'),
    expected_event_revision: trip.event_revision,
    kind: 'poi_closed',
    active: true,
    activity_id: null,
    earliest_start_at: null,
    poi_id: POI.yellowCraneTower,
    effective_at: toShanghaiIso(endDate, '08:00'),
    source: 'simulation',
    evidence_ref: 'simulation:event:poi-closure',
    verification_status: 'verified',
  }
}

export interface PlanChangeSummary {
  changed: string[]
  added: string[]
  removed: string[]
  activityCount: number
  budgetDeltaCny: string
}

export function summarizePlanChange(base: TravelPlan, candidate: TravelPlan): PlanChangeSummary {
  const baseById = new Map(base.activities.map((activity) => [activity.id, activity]))
  const candidateById = new Map(candidate.activities.map((activity) => [activity.id, activity]))
  const added = candidate.activities.filter((activity) => !baseById.has(activity.id)).map((activity) => activity.id)
  const removed = base.activities.filter((activity) => !candidateById.has(activity.id)).map((activity) => activity.id)
  const changed = candidate.activities
    .filter((activity) => {
      const original = baseById.get(activity.id)
      if (!original) return false
      return JSON.stringify(original) !== JSON.stringify(activity)
    })
    .map((activity) => activity.id)
  return {
    changed,
    added,
    removed,
    activityCount: candidate.activities.length,
    budgetDeltaCny: cnyFromCents(toCents(planTotalCny(candidate)) - toCents(planTotalCny(base))),
  }
}

export function describeActivity(activity: Activity): string {
  return `${activity.id} · ${poiName(activity.poi_id)}`
}
