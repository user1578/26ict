/** TravelGuard 数据模型 —— 严格按 B 端《API 契约·第五阶段》与 /openapi.json 定义。
 *  金额一律为十进制字符串（如 "300.00"），时间一律为带时区 ISO；展示分别走 money.ts / time.ts。 */

export type CheckStatus = 'PASS' | 'FAIL' | 'UNKNOWN' | 'NOT_APPLICABLE'

export type OpeningStatus = 'confirmed_open' | 'confirmed_closed' | 'unknown'

export type BookingStatus = 'confirmed' | 'not_confirmed' | 'unknown'

export type EventKind = 'poi_closed' | 'train_delay'

export type EventSource = 'simulation' | 'reported'

export type EventVerification = 'verified' | 'unverified'

export type DraftStatus = 'pending' | 'stale' | 'committed'

export interface Check {
  name: string
  status: CheckStatus
  detail: string
}

export interface Validation {
  overall: CheckStatus
  checks: Check[]
  note: string
}

/** 预算快照；与 B 的 BudgetResult 一致，pending 退款不抵扣。 */
export interface Budget {
  budget_cny: string
  paid_cny: string
  planned_cny: string
  received_refunds_cny: string
  pending_refunds_cny: string
  conservative_total_cny: string
  remaining_cny: string
  within_budget: boolean
}

export interface Activity {
  id: string
  poi_id: string
  start_at: string
  end_at: string
  transport_minutes_from_previous: number | null
  walking_minutes_from_previous: number | null
  opening_status: OpeningStatus
  booking_required: boolean
  booking_status: BookingStatus
}

export interface Charge {
  id: string
  amount_cny: string
  status: 'paid' | 'planned'
}

export interface Refund {
  id: string
  amount_cny: string
  status: 'received' | 'pending'
}

export interface TravelPlan {
  activities: Activity[]
  charges: Charge[]
  refunds: Refund[]
  arrival_at_return_station: string | null
  activity_evidence: Record<string, string>
  financial_evidence: Record<string, string>
}

export interface TripConstraints {
  budget_cny: string
  max_walking_minutes_per_leg: number | null
  return_deadline: string | null
}

export interface TripPreferences {
  stay_together: boolean | null
}

export interface EventFacts {
  kind: EventKind
  active: boolean
  activity_id: string | null
  earliest_start_at: string | null
  poi_id: string | null
  effective_at: string | null
  source: EventSource
  evidence_ref: string
  verification_status: EventVerification
}

export interface EventView extends EventFacts {
  event_id: string
  revision: number
}

export interface Confirmation {
  request_id: string
  confirmed_by: string
  confirmed_at: string
}

export interface VersionView {
  trip_id: string
  version: number
  event_revision: number
  history_revision: number
  source_draft_id: string | null
  plan: TravelPlan
  budget: Budget
  validation: Validation
  confirmation: Confirmation | null
  created_at: string
}

export interface TripView {
  trip_id: string
  title: string
  current_version: number
  event_revision: number
  history_revision: number
  city: string | null
  party_size: number | null
  start_date: string | null
  end_date: string | null
  preferences: TripPreferences
  constraints: TripConstraints
  locked_activity_ids: string[]
  current_plan: VersionView
  events: EventView[]
}

export interface DraftView {
  trip_id: string
  draft_id: string
  base_version: number
  event_revision: number
  history_revision: number
  handled_event_ids: string[]
  status: DraftStatus
  committed_version: number | null
  plan: TravelPlan
  validation: Validation
  created_at: string
}

// ---- 请求体 ----

export interface CreateTripRequest {
  request_id: string
  trip_id: string
  title: string
  city: string
  party_size: number | null
  start_date: string | null
  end_date: string | null
  preferences: TripPreferences
  budget_cny: string
  max_walking_minutes_per_leg: number | null
  return_deadline: string | null
  locked_activity_ids: string[]
  plan: TravelPlan
}

export interface PutEventRequest extends EventFacts {
  request_id: string
  expected_event_revision: number
}

export interface CreateDraftRequest {
  request_id: string
  draft_id: string
  base_version: number
  event_revision: number
  history_revision: number
  handled_event_ids: string[]
  plan: TravelPlan
}

export interface ConfirmDraftRequest {
  request_id: string
  base_version: number
  event_revision: number
  history_revision: number
  user_confirmed: true
  confirmed_by: string
}

export interface LockActivitiesRequest {
  request_id: string
  base_version: number
  history_revision: number
  activity_ids: string[]
}
