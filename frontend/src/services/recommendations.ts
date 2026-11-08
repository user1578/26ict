import type { CreateTripRequest, TravelPlan, Validation } from '../types.ts'

export interface PlanningInput {
  origin_city: string; city: string; arrival_station: string; return_station: string; keywords: string
  start_date: string; end_date: string; party_size: number; budget_cny: string
  max_walking_minutes_per_leg: number | null; arrival_time: string; return_time: string
  stay_together: boolean; other_costs_cny: string | null
  allowed_modes?: TransportMode[]
  lodging_poi_id?: string | null; lodging_name?: string | null
}
export type TransportMode = 'transit' | 'walking' | 'bicycling' | 'driving'
export interface Place { poi_id: string; name: string; address: string | null
  location: { longitude: number; latitude: number } | null; indoor: boolean | null; district?: string | null }
export interface Evidence { source: string; fetched_at: string; source_ref: string | null
  data_type: string; verification_status: string; attributions: string[] }
export interface ToolResult<T> { status: string; code: string; message: string; evidence: Evidence; data: T | null }
export interface Weather { on_date: string; temperature_min_c: number; temperature_max_c: number
  conditions: string[]; risk_check: string; risk_factors: string[]; note: string }
export interface SelectedRoute { mode: string; duration_minutes: number; walking_minutes: number | null
  distance_meters: number; cost_cny: string | null; evidence: Evidence }
export interface Recommendation {
  profile: string; label: string; reason: string; rank: number; recommended: boolean; score: number
  ranking_note: string; known_cost_cny: string; remaining_cny: string; cost_complete: boolean
  available_balance_cny: string | null; paid_cny: string; estimated_cny: string
  missing_costs: string[]; warnings: string[]; feasibility: 'feasible' | 'unverified' | 'infeasible'
  lodging: Place | null
  walking_minutes: number | null; transport_minutes: number | null; unverified: string[]; plan: TravelPlan; validation: Validation
  days: Array<{ date: string; activity_id: string; place: Place | null; rules: ToolResult<unknown>
    weather: ToolResult<Weather> | null; indoor_inferred: boolean | null; kind?: 'visit' | 'lodging' }>
  legs: Array<{ from_name: string; to_name: string; date: string; activity_id: string | null
    selected: SelectedRoute | null; options: { results: Array<ToolResult<Array<{duration_seconds: number; distance_meters: number; walking_seconds: number | null; cost_cny: string | null}>> & { mode: string }> } | null }>
}
export interface PlanningBundle {
  format_version?: number; needs_refresh?: boolean; distinct_shortfall?: number
  generator: string; agentarts_connected: false; input: PlanningInput; places: Place[]
  searches: Array<ToolResult<Place[]>>; arrival_candidates: Place[]; return_candidates: Place[]
  candidates: Recommendation[]
  trip_request: Omit<CreateTripRequest, 'request_id' | 'trip_id' | 'plan'>
}

export async function recommend(input: PlanningInput, tripId?: string): Promise<PlanningBundle> {
  const response = await fetch(tripId ? `/api/trips/${encodeURIComponent(tripId)}/recommendations` : '/api/recommendations', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  if (!response.ok) {
    if (response.status === 502) throw new Error('暂时无法连接行程服务，请确认本机后端已启动。')
    throw new Error(`路线查询未完成（HTTP ${response.status}），请检查输入或稍后重试。`)
  }
  return response.json() as Promise<PlanningBundle>
}

// This is display context only. Official state and confirmation always come from B.
export function savePlanning(tripId: string, bundle: PlanningBundle) {
  try { localStorage.setItem(`travelguard:planning:${tripId}`, JSON.stringify(bundle)) }
  catch { /* Browser storage may be disabled. The official trip remains on B. */ }
}
export function readPlanning(tripId: string): PlanningBundle | null {
  try {
    const value = JSON.parse(localStorage.getItem(`travelguard:planning:${tripId}`) ?? 'null') as PlanningBundle | null
    if (value?.generator !== 'rules-v1' || !value.input || !Array.isArray(value.places) || !Array.isArray(value.candidates)) return null
    const current = value.format_version === 2 && value.candidates.every(c =>
      typeof c.paid_cny === 'string' && typeof c.estimated_cny === 'string' &&
      Array.isArray(c.warnings) && Array.isArray(c.missing_costs))
    // Preserve old inputs and names for a manual requery; don't invent missing fees or trust old PASS labels.
    return current ? value : { ...value, candidates: [], needs_refresh: true }
  } catch { return null }
}
