export type SourceType = 'real' | 'simulation' | 'estimate'

export type VerificationStatus = 'PASS' | 'FAIL' | 'UNKNOWN' | 'NOT_APPLICABLE'

export type OpeningStatus = 'confirmed_open' | 'confirmed_closed' | 'unknown'

export type BookingStatus = 'confirmed' | 'pending' | 'none' | 'unknown'

export type EventType = 'transport_delay' | 'weather' | 'place_closure'

export type EventStatus = 'active' | 'resolved' | 'superseded'

export type DraftStatus = 'awaiting_confirmation' | 'superseded' | 'confirmed'

export type Feasibility = 'feasible' | 'conditional' | 'infeasible' | 'unknown'

export interface Activity {
  activity_id: string
  poi_id: string
  name: string
  day: number
  start_at: string
  end_at: string
  booking_required: boolean
  booking_status: BookingStatus
  booking_source_type: SourceType
  opening_status: OpeningStatus
  rule_verification: VerificationStatus
  est_cost_cny: number
  source_type: SourceType
  unknown_fields: string[]
}

export interface CostItem {
  id: string
  label: string
  amount_cny: number
  status: 'paid' | 'planned'
}

export interface TripConstraints {
  max_walking_minutes_per_leg: number
  stay_together: boolean
  return_deadline: string
}

export interface Trip {
  trip_id: string
  city: string
  dates: [string, string]
  party_size: number
  budget_cny: number
  formal_version: number
  event_revision: number
  constraints: TripConstraints
  activities: Activity[]
  costs: CostItem[]
}

export interface TripEvent {
  event_id: string
  trip_id: string
  type: EventType
  status: EventStatus
  source_type: SourceType
  confidence: 'verified' | 'scenario_assumed' | 'unknown'
  affects_activity_ids: string[]
  reported_at: string
  detail: string
}

export interface ActivityChange {
  activity_id: string
  remove?: boolean
  name?: string
  poi_id?: string
  start_at?: string
  end_at?: string
  est_cost_cny?: number
  opening_status?: OpeningStatus
  rule_verification?: VerificationStatus
  booking_status?: BookingStatus
  unknown_fields?: string[]
}

export interface DraftOption {
  option_id: string
  title: string
  description: string
  feasibility: Feasibility
  changed_activity_ids: string[]
  cost_delta_cny: number
  warnings: string[]
  requires_external_actions: string[]
  unknown_fields: string[]
  changes: ActivityChange[]
}

export interface Draft {
  draft_id: string
  trip_id: string
  base_version: number
  event_revision: number
  event_ids: string[]
  status: DraftStatus
  official_version_unchanged: boolean
  superseded_by?: string
  options: DraftOption[]
}

export interface VersionRecord {
  formal_version: number
  created_at: string
  note: string
}
