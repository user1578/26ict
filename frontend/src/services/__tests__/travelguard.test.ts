import { describe, expect, it } from 'vitest'
import { ApiError } from '../apiError.ts'
import { POI } from '../dataset.ts'
import { validatePlanLocally } from '../localValidation.ts'
import { MockTravelGuardApi } from '../mockApi.ts'
import { formatCny, planTotalCny, sumCny, toCents } from '../money.ts'
import {
  buildCandidatePlans,
  buildClosureEvent,
  buildCreateTripRequest,
  buildDelayEvent,
  buildDraftRequests,
  buildInitialPlan,
  nextEventId,
  summarizePlanChange,
  type TripFormInput,
} from '../planner.ts'
import { addMinutes, formatDate, formatTime, toShanghaiIso } from '../time.ts'
import type { TripView } from '../../types.ts'

const FORM: TripFormInput = {
  city: '武汉',
  startDate: '2026-11-18',
  endDate: '2026-11-19',
  partySize: 3,
  budgetCny: '1300',
  walkingLimit: 20,
  returnTime: '17:00',
  stayTogether: true,
}

function constraintsOf(request: ReturnType<typeof buildCreateTripRequest>) {
  return {
    budget_cny: request.budget_cny,
    max_walking_minutes_per_leg: request.max_walking_minutes_per_leg,
    return_deadline: request.return_deadline,
  }
}

function validateDemoPlan(
  plan = buildInitialPlan(FORM),
  request: ReturnType<typeof buildCreateTripRequest> = buildCreateTripRequest(FORM),
) {
  return validatePlanLocally({
    plan,
    constraints: constraintsOf(request),
    events: [],
    lockedIds: [],
    previous: null,
    requiredBookingPois: new Set<string>(),
  })
}

describe('金额与时间工具', () => {
  it('金额按整数分计算，渲染保留两位小数', () => {
    expect(toCents('300.00')).toBe(30000)
    expect(toCents('-55.00')).toBe(-5500)
    expect(toCents('0.1')).toBe(10)
    expect(formatCny('1300.00')).toBe('¥1,300.00')
    expect(formatCny('-55.00')).toBe('-¥55.00')
    expect(sumCny(['0.10', '0.20', '1050.00'])).toBe('1050.30')
  })

  it('时间统一按 Asia/Shanghai 展示', () => {
    expect(toShanghaiIso('2026-11-18', '10:00')).toBe('2026-11-18T10:00:00+08:00')
    expect(addMinutes('2026-11-18T10:00:00+08:00', 45)).toBe('2026-11-18T10:45:00+08:00')
    // 服务端 UTC 时间在 +08:00 下应显示为 22:55
    expect(formatDate('2026-10-27T14:55:41Z')).toBe('2026-10-27')
    expect(formatTime('2026-10-27T14:55:41Z')).toBe('22:55')
  })
})

describe('本地规划器与核验', () => {
  it('初始 V1 方案在本地核验中 PASS，且金额口径与 B 一致', () => {
    const plan = buildInitialPlan(FORM)
    expect(planTotalCny(plan)).toBe('1050.00') // 70 已付 + 980 待付，pending 退款不抵扣
    const validation = validateDemoPlan(plan)
    expect(validation.overall).toBe('PASS')
    expect(validation.checks.map((check) => check.status)).not.toContain('FAIL')
  })

  it('未知开放状态会让整体变为 UNKNOWN，超预算会 FAIL', () => {
    const unknownPlan = buildInitialPlan(FORM)
    unknownPlan.activities[0].opening_status = 'unknown'
    expect(validateDemoPlan(unknownPlan).overall).toBe('UNKNOWN')

    const overBudget = buildCreateTripRequest({ ...FORM, budgetCny: '500' })
    expect(validateDemoPlan(overBudget.plan, overBudget).overall).toBe('FAIL')
  })

  it('晚点候选：顺延受影响活动并满足事件约束', () => {
    const request = buildCreateTripRequest(FORM)
    const plan = buildInitialPlan(FORM)
    const trip = buildFakeTrip(request, plan)
    const event = buildDelayEvent(trip)
    const eventId = nextEventId(trip)
    const withEvent: TripView = {
      ...trip,
      event_revision: 1,
      events: [{ ...event, event_id: eventId, revision: 1 }],
    }
    const candidates = buildCandidatePlans(withEvent)
    expect(candidates).toHaveLength(1)
    const delayed = candidates[0].plan.activities.find((activity) => activity.poi_id === POI.eastLakeGreenway)
    expect(delayed?.start_at).toBe('2026-11-18T14:45:00+08:00')
    const validation = validatePlanLocally({
      plan: candidates[0].plan,
      constraints: constraintsOf(request),
      events: withEvent.events,
      lockedIds: [],
      previous: plan,
      requiredBookingPois: new Set([POI.hubeiMuseum]),
    })
    expect(validation.overall).toBe('PASS')
  })

  it('闭馆候选：替换/删减都满足事件约束与资金/预约状态检查', () => {
    const request = buildCreateTripRequest(FORM)
    const plan = buildInitialPlan(FORM)
    const trip = buildFakeTrip(request, plan)
    const event = { ...buildClosureEvent(trip), event_id: 'E1', revision: 1 }
    const withEvent: TripView = { ...trip, event_revision: 1, events: [event] }
    const candidates = buildCandidatePlans(withEvent)
    expect(candidates).toHaveLength(2)
    for (const candidate of candidates) {
      const validation = validatePlanLocally({
        plan: candidate.plan,
        constraints: constraintsOf(request),
        events: withEvent.events,
        lockedIds: [],
        previous: plan,
        requiredBookingPois: new Set([POI.hubeiMuseum]),
      })
      expect(validation.overall).toBe('PASS')
      expect(
        candidate.plan.activities.some((activity) => activity.poi_id === POI.yellowCraneTower),
      ).toBe(false)
    }
    const summary = summarizePlanChange(plan, candidates[0].plan)
    expect(summary.removed.length + summary.changed.length + summary.added.length).toBeGreaterThan(0)
  })
})

describe('mock 客户端状态机', () => {
  it('创建 → 晚点 → 候选 → 确认 → 闭馆 → 候选 → 确认', async () => {
    const api = new MockTravelGuardApi()
    const request = buildCreateTripRequest(FORM)
    const created = await api.createTrip(request)
    expect(created.current_version).toBe(1)
    expect(created.current_plan.validation.overall).toBe('PASS')

    // 晚点
    const delay = buildDelayEvent(created)
    await api.putEvent(created.trip_id, nextEventId(created), delay)
    const afterDelay = await api.getTrip(created.trip_id)
    expect(afterDelay.event_revision).toBe(1)
    const delayDrafts = await createDrafts(api, afterDelay)
    expect(delayDrafts).toHaveLength(1)
    expect(delayDrafts[0].validation.overall).toBe('PASS')

    const v2 = await confirm(api, afterDelay, delayDrafts[0])
    expect(v2.version).toBe(2)
    const draftsAfterConfirm = await api.getDrafts(created.trip_id)
    expect(draftsAfterConfirm[0].status).toBe('committed')

    // 闭馆（基于 V2）
    const current = await api.getTrip(created.trip_id)
    const closure = buildClosureEvent(current)
    await api.putEvent(created.trip_id, nextEventId(current), closure)
    const afterClosure = await api.getTrip(created.trip_id)
    expect(afterClosure.event_revision).toBe(2)
    const drafts = await api.getDrafts(created.trip_id)
    // 已确认的旧草案保持 committed；没有 pending 残留
    expect(drafts.find((draft) => draft.status === 'committed')).toBeTruthy()
    expect(drafts.some((draft) => draft.status === 'pending')).toBe(false)

    const closureDrafts = await createDrafts(api, afterClosure)
    expect(closureDrafts).toHaveLength(2)
    for (const draft of closureDrafts) {
      expect(draft.validation.overall).toBe('PASS')
      expect(draft.handled_event_ids).toEqual(['E1', 'E2'])
    }
    const v3 = await confirm(api, afterClosure, closureDrafts[0])
    expect(v3.version).toBe(3)
    expect((await api.getVersions(created.trip_id)).map((version) => version.version)).toEqual([1, 2, 3])
  })

  it('乐观锁与冲突码与 B 对齐', async () => {
    const api = new MockTravelGuardApi()
    const created = await api.createTrip(buildCreateTripRequest(FORM))

    await expect(
      api.putEvent(created.trip_id, 'E1', { ...buildDelayEvent(created), expected_event_revision: 2 }),
    ).rejects.toMatchObject({ code: 'revision_conflict' })

    await api.putEvent(created.trip_id, 'E1', buildDelayEvent(created))
    const afterDelay = await api.getTrip(created.trip_id)
    const candidates = buildCandidatePlans(afterDelay)
    const requests = buildDraftRequests(afterDelay, candidates)
    const draft = await api.createDraft(afterDelay.trip_id, requests[0])

    // 同 draft_id + 新 request_id → draft_exists（业务 409）
    await expect(
      api.createDraft(afterDelay.trip_id, { ...requests[0], request_id: 'another-request' }),
    ).rejects.toMatchObject({ code: 'draft_exists' })

    // 事件集合变化后，旧草案的令牌过期 → revision_conflict（B 的实际行为：先于 draft_stale）
    await api.putEvent(afterDelay.trip_id, 'E2', buildClosureEvent(afterDelay))
    await expect(
      api.confirmDraft(afterDelay.trip_id, draft.draft_id, {
        request_id: 'confirm-old',
        base_version: draft.base_version,
        event_revision: draft.event_revision,
        history_revision: draft.history_revision,
        user_confirmed: true,
        confirmed_by: 'demo-user',
      }),
    ).rejects.toBeInstanceOf(ApiError)

    const drafts = await api.getDrafts(afterDelay.trip_id)
    expect(drafts.find((item) => item.draft_id === draft.draft_id)?.status).toBe('stale')
  })
})

// ---- helpers ----

function buildFakeTrip(
  request: ReturnType<typeof buildCreateTripRequest>,
  plan: ReturnType<typeof buildInitialPlan>,
): TripView {
  return {
    trip_id: request.trip_id,
    title: request.title,
    current_version: 1,
    event_revision: 0,
    history_revision: 0,
    city: request.city,
    party_size: request.party_size,
    start_date: request.start_date,
    end_date: request.end_date,
    preferences: request.preferences,
    constraints: constraintsOf(request),
    locked_activity_ids: [],
    current_plan: {
      trip_id: request.trip_id,
      version: 1,
      event_revision: 0,
      history_revision: 0,
      source_draft_id: null,
      plan,
      budget: {
        budget_cny: '1300.00',
        paid_cny: '70.00',
        planned_cny: '980.00',
        received_refunds_cny: '0.00',
        pending_refunds_cny: '35.00',
        conservative_total_cny: '1050.00',
        remaining_cny: '250.00',
        within_budget: true,
      },
      validation: validateDemoPlan(plan),
      confirmation: null,
      created_at: '2026-10-30T00:00:00Z',
    },
    events: [],
  }
}

async function createDrafts(api: MockTravelGuardApi, trip: TripView) {
  const candidates = buildCandidatePlans(trip)
  const requests = buildDraftRequests(trip, candidates)
  const drafts = []
  for (const request of requests) drafts.push(await api.createDraft(trip.trip_id, request))
  return drafts
}

async function confirm(api: MockTravelGuardApi, trip: TripView, draft: Awaited<ReturnType<typeof createDrafts>>[number]) {
  return api.confirmDraft(trip.trip_id, draft.draft_id, {
    request_id: `confirm-${draft.draft_id}`,
    base_version: draft.base_version,
    event_revision: draft.event_revision,
    history_revision: draft.history_revision,
    user_confirmed: true,
    confirmed_by: 'demo-user',
  })
}
