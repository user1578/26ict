/** 纯内存 mock：接口形状、状态机与错误码尽量对齐 B 的 FastAPI，
 *  让 `?mode=mock` 时无需后端也能完整演示“创建 → 上报异常 → 候选 → 确认升版”。 */

import type {
  Budget,
  ConfirmDraftRequest,
  CreateDraftRequest,
  CreateTripRequest,
  DraftView,
  EventView,
  LockActivitiesRequest,
  PutEventRequest,
  TravelPlan,
  TripConstraints,
  TripView,
  Validation,
  VersionView,
} from '../types.ts'
import { ApiError } from './apiError.ts'
import type { TravelGuardApi } from './client.ts'
import { cnyFromCents, toCents } from './money.ts'
import { validatePlanLocally } from './localValidation.ts'

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function buildBudget(plan: TravelPlan, constraints: TripConstraints): Budget {
  const sum = (values: string[]) => values.reduce((total, value) => total + toCents(value), 0)
  const paid = sum(plan.charges.filter((charge) => charge.status === 'paid').map((charge) => charge.amount_cny))
  const planned = sum(plan.charges.filter((charge) => charge.status === 'planned').map((charge) => charge.amount_cny))
  const received = sum(plan.refunds.filter((refund) => refund.status === 'received').map((refund) => refund.amount_cny))
  const pending = sum(plan.refunds.filter((refund) => refund.status === 'pending').map((refund) => refund.amount_cny))
  const total = paid + planned - received
  const budget = toCents(constraints.budget_cny)
  return {
    budget_cny: constraints.budget_cny,
    paid_cny: cnyFromCents(paid),
    planned_cny: cnyFromCents(planned),
    received_refunds_cny: cnyFromCents(received),
    pending_refunds_cny: cnyFromCents(pending),
    conservative_total_cny: cnyFromCents(total),
    remaining_cny: cnyFromCents(budget - total),
    within_budget: total <= budget,
  }
}

interface MockTrip {
  view: TripView
  versions: VersionView[]
  drafts: Map<string, DraftView>
}

function requiredBookingPois(versions: VersionView[]): Set<string> {
  const pois = new Set<string>()
  for (const version of versions) {
    for (const activity of version.plan.activities) {
      if (activity.booking_required) pois.add(activity.poi_id)
    }
  }
  return pois
}

export class MockTravelGuardApi implements TravelGuardApi {
  readonly mode = 'mock' as const

  private trips = new Map<string, MockTrip>()

  private state(tripId: string): MockTrip {
    const state = this.trips.get(tripId)
    if (!state) throw new ApiError(404, 'trip_not_found', '旅行不存在')
    return state
  }

  async createTrip(body: CreateTripRequest): Promise<TripView> {
    if (this.trips.has(body.trip_id)) throw new ApiError(409, 'trip_exists', '旅行ID已存在')
    const constraints: TripConstraints = {
      budget_cny: body.budget_cny,
      max_walking_minutes_per_leg: body.max_walking_minutes_per_leg,
      return_deadline: body.return_deadline,
    }
    const validation = validatePlanLocally({
      plan: body.plan,
      constraints,
      events: [],
      lockedIds: [],
      previous: null,
      requiredBookingPois: new Set(),
    })
    if (validation.overall !== 'PASS') {
      throw new ApiError(422, 'verification_blocked', '必须通过全部必要核验才能建立正式版本', {
        validation,
      })
    }
    const version: VersionView = {
      trip_id: body.trip_id,
      version: 1,
      event_revision: 0,
      history_revision: 0,
      source_draft_id: null,
      plan: body.plan,
      budget: buildBudget(body.plan, constraints),
      validation,
      confirmation: null,
      created_at: new Date().toISOString(),
    }
    const view: TripView = {
      trip_id: body.trip_id,
      title: body.title,
      current_version: 1,
      event_revision: 0,
      history_revision: 0,
      city: body.city,
      party_size: body.party_size,
      start_date: body.start_date,
      end_date: body.end_date,
      preferences: body.preferences,
      constraints,
      locked_activity_ids: body.locked_activity_ids,
      current_plan: version,
      events: [],
    }
    this.trips.set(body.trip_id, { view, versions: [version], drafts: new Map() })
    return clone(view)
  }

  async getTrip(tripId: string): Promise<TripView> {
    return clone(this.state(tripId).view)
  }

  async getVersions(tripId: string): Promise<VersionView[]> {
    return clone(this.state(tripId).versions)
  }

  async putEvent(tripId: string, eventId: string, body: PutEventRequest): Promise<EventView> {
    const state = this.state(tripId)
    if (body.expected_event_revision !== state.view.event_revision) {
      throw new ApiError(409, 'revision_conflict', '异常修订号已变化')
    }
    if (body.kind === 'train_delay' && body.active) {
      const exists = state.view.current_plan.plan.activities.some((activity) => activity.id === body.activity_id)
      if (!exists) throw new ApiError(422, 'invalid_event_target', '晚点异常必须引用当前正式行程中的活动')
    }
    const revision = state.view.event_revision + 1
    const event: EventView = {
      event_id: eventId,
      revision,
      kind: body.kind,
      active: body.active,
      activity_id: body.activity_id,
      earliest_start_at: body.earliest_start_at,
      poi_id: body.poi_id,
      effective_at: body.effective_at,
      source: body.source,
      evidence_ref: body.evidence_ref,
      verification_status: body.verification_status,
    }
    const existingIndex = state.view.events.findIndex((item) => item.event_id === eventId)
    if (existingIndex >= 0) {
      state.view.events[existingIndex] = event
    } else {
      state.view.events.push(event)
    }
    state.view.event_revision = revision
    for (const draft of state.drafts.values()) {
      if (draft.status === 'pending') draft.status = 'stale'
    }
    return clone(event)
  }

  private evaluate(state: MockTrip, plan: TravelPlan): Validation {
    return validatePlanLocally({
      plan,
      constraints: state.view.constraints,
      events: state.view.events,
      lockedIds: state.view.locked_activity_ids,
      previous: state.view.current_plan.plan,
      requiredBookingPois: requiredBookingPois(state.versions),
    })
  }

  async createDraft(tripId: string, body: CreateDraftRequest): Promise<DraftView> {
    const state = this.state(tripId)
    const view = state.view
    const tokensMatch =
      body.base_version === view.current_version &&
      body.event_revision === view.event_revision &&
      body.history_revision === view.history_revision
    if (!tokensMatch) {
      throw new ApiError(409, 'revision_conflict', '正式版本、有效异常或锁定历史已变化，请重新读取旅行状态')
    }
    const activeIds = view.events.filter((event) => event.active).map((event) => event.event_id).sort()
    if (JSON.stringify(activeIds) !== JSON.stringify([...body.handled_event_ids].sort())) {
      throw new ApiError(409, 'event_set_conflict', '草案必须声明当前全部有效异常，不能遗漏或带入无效异常')
    }
    if (state.drafts.has(body.draft_id)) {
      throw new ApiError(409, 'draft_exists', '草案ID已存在，请使用新ID')
    }
    const draft: DraftView = {
      trip_id: tripId,
      draft_id: body.draft_id,
      base_version: body.base_version,
      event_revision: body.event_revision,
      history_revision: body.history_revision,
      handled_event_ids: activeIds,
      status: 'pending',
      committed_version: null,
      plan: body.plan,
      validation: this.evaluate(state, body.plan),
      created_at: new Date().toISOString(),
    }
    state.drafts.set(draft.draft_id, draft)
    return clone(draft)
  }

  async getDrafts(tripId: string): Promise<DraftView[]> {
    const state = this.state(tripId)
    return [...state.drafts.values()].sort((left, right) => left.draft_id.localeCompare(right.draft_id)).map(clone)
  }

  async getDraft(tripId: string, draftId: string): Promise<DraftView> {
    const state = this.state(tripId)
    const draft = state.drafts.get(draftId)
    if (!draft) throw new ApiError(404, 'draft_not_found', '草案不存在')
    return clone(draft)
  }

  async confirmDraft(tripId: string, draftId: string, body: ConfirmDraftRequest): Promise<VersionView> {
    const state = this.state(tripId)
    const view = state.view
    const draft = state.drafts.get(draftId)
    if (!draft) throw new ApiError(404, 'draft_not_found', '草案不存在')

    const tokensMatchDraft =
      body.base_version === draft.base_version &&
      body.event_revision === draft.event_revision &&
      body.history_revision === draft.history_revision
    if (!tokensMatchDraft) {
      throw new ApiError(409, 'draft_token_conflict', '确认参数与草案绑定的版本/修订号不一致')
    }
    if (draft.status === 'committed') {
      const version = state.versions.find((item) => item.version === draft.committed_version)
      if (!version) throw new ApiError(404, 'version_not_found', '正式版本不存在')
      if (version.confirmation?.confirmed_by !== body.confirmed_by) {
        throw new ApiError(409, 'confirmation_conflict', '不能改写已保存的用户确认')
      }
      return clone(version)
    }
    const tokensMatchTrip =
      body.base_version === view.current_version &&
      body.event_revision === view.event_revision &&
      body.history_revision === view.history_revision
    if (!tokensMatchTrip) {
      throw new ApiError(409, 'revision_conflict', '正式版本、有效异常或锁定历史已变化，请重新读取旅行状态')
    }
    if (draft.status !== 'pending') {
      throw new ApiError(409, 'draft_stale', '草案已失效，必须根据最新状态重新生成')
    }
    const activeIds = view.events.filter((event) => event.active).map((event) => event.event_id).sort()
    if (JSON.stringify(activeIds) !== JSON.stringify([...draft.handled_event_ids].sort())) {
      throw new ApiError(409, 'event_set_conflict', '有效异常集合已改变')
    }
    const validation = this.evaluate(state, draft.plan)
    if (validation.overall !== 'PASS') {
      throw new ApiError(422, 'verification_blocked', '必须通过全部必要核验才能建立正式版本', {
        validation,
      })
    }
    const nextVersion = view.current_version + 1
    const version: VersionView = {
      trip_id: tripId,
      version: nextVersion,
      event_revision: view.event_revision,
      history_revision: view.history_revision,
      source_draft_id: draft.draft_id,
      plan: draft.plan,
      budget: buildBudget(draft.plan, view.constraints),
      validation,
      confirmation: {
        request_id: body.request_id,
        confirmed_by: body.confirmed_by,
        confirmed_at: new Date().toISOString(),
      },
      created_at: new Date().toISOString(),
    }
    state.versions.push(version)
    view.current_version = nextVersion
    view.current_plan = version
    draft.status = 'committed'
    draft.committed_version = nextVersion
    for (const other of state.drafts.values()) {
      if (other.draft_id !== draft.draft_id && other.status === 'pending') other.status = 'stale'
    }
    return clone(version)
  }

  async lockActivities(tripId: string, body: LockActivitiesRequest): Promise<TripView> {
    const state = this.state(tripId)
    const view = state.view
    if (body.base_version !== view.current_version || body.history_revision !== view.history_revision) {
      throw new ApiError(409, 'revision_conflict', '正式版本或历史修订号已变化')
    }
    const currentIds = new Set(view.current_plan.plan.activities.map((activity) => activity.id))
    if (body.activity_ids.some((id) => !currentIds.has(id))) {
      throw new ApiError(422, 'invalid_lock', '只能锁定当前正式行程中的活动')
    }
    const merged = new Set([...view.locked_activity_ids, ...body.activity_ids])
    const updated = [...merged].sort()
    if (updated.length !== view.locked_activity_ids.length) {
      view.locked_activity_ids = updated
      view.history_revision += 1
      for (const draft of state.drafts.values()) {
        if (draft.status === 'pending') draft.status = 'stale'
      }
    }
    return clone(view)
  }
}
