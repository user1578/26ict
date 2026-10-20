import type {
  Activity,
  ActivityChange,
  Draft,
  DraftOption,
  Trip,
  TripEvent,
  VersionRecord,
} from '../types.ts'

export interface TripInput {
  city: string
  startDate: string
  endDate: string
  partySize: number
  budgetCny: number
  walkingLimit: number
  returnTime: string
}

const TZ = '+08:00'

const at = (date: string, time: string) => `${date}T${time}:00${TZ}`

const nowIso = () => new Date().toISOString()

const pad = (value: number) => String(value).padStart(2, '0')

function toIsoPlus8(date: Date): string {
  const shifted = new Date(date.getTime() + 8 * 3600 * 1000)
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(
    shifted.getUTCDate(),
  )}T${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:00${TZ}`
}

function shiftIso(iso: string, minutes: number): string {
  return toIsoPlus8(new Date(new Date(iso).getTime() + minutes * 60 * 1000))
}

export function buildTrip(input: TripInput): Trip {
  const activities: Activity[] = [
    {
      activity_id: 'a01',
      poi_id: 'WH01',
      name: '湖北省博物馆',
      day: 1,
      start_at: at(input.startDate, '14:00'),
      end_at: at(input.startDate, '16:30'),
      booking_required: true,
      booking_status: 'confirmed',
      booking_source_type: 'simulation',
      opening_status: 'unknown',
      rule_verification: 'UNKNOWN',
      est_cost_cny: 0,
      source_type: 'simulation',
      unknown_fields: ['opening_hours', 'reservation_rule'],
    },
    {
      activity_id: 'a02',
      poi_id: 'WH02',
      name: '东湖绿道',
      day: 1,
      start_at: at(input.startDate, '17:00'),
      end_at: at(input.startDate, '18:30'),
      booking_required: false,
      booking_status: 'none',
      booking_source_type: 'simulation',
      opening_status: 'confirmed_open',
      rule_verification: 'PASS',
      est_cost_cny: 0,
      source_type: 'simulation',
      unknown_fields: [],
    },
    {
      activity_id: 'a03',
      poi_id: 'WH03',
      name: '黄鹤楼',
      day: 2,
      start_at: at(input.endDate, '09:00'),
      end_at: at(input.endDate, '11:00'),
      booking_required: false,
      booking_status: 'none',
      booking_source_type: 'simulation',
      opening_status: 'unknown',
      rule_verification: 'UNKNOWN',
      est_cost_cny: 70,
      source_type: 'estimate',
      unknown_fields: ['opening_hours'],
    },
    {
      activity_id: 'a04',
      poi_id: 'WH04',
      name: '户部巷',
      day: 2,
      start_at: at(input.endDate, '12:00'),
      end_at: at(input.endDate, '13:30'),
      booking_required: false,
      booking_status: 'none',
      booking_source_type: 'simulation',
      opening_status: 'confirmed_open',
      rule_verification: 'PASS',
      est_cost_cny: 150,
      source_type: 'estimate',
      unknown_fields: [],
    },
  ]

  return {
    trip_id: 'trip_001',
    city: input.city,
    dates: [input.startDate, input.endDate],
    party_size: input.partySize,
    budget_cny: input.budgetCny,
    formal_version: 1,
    event_revision: 0,
    constraints: {
      max_walking_minutes_per_leg: input.walkingLimit,
      stay_together: true,
      return_deadline: at(input.endDate, input.returnTime),
    },
    activities,
    costs: [
      { id: 'c-transport', label: '市内交通（估算）', amount_cny: 320, status: 'planned' },
      { id: 'c-hotel', label: '住宿 2 晚（估算）', amount_cny: 520, status: 'planned' },
      { id: 'c-food', label: '餐饮（估算）', amount_cny: 140, status: 'planned' },
    ],
  }
}

/** 与后端 BudgetResult.conservative_total_cny 口径一致：已付 + 待付 - 已到账退款。 */
export function plannedTotalCny(trip: Trip): number {
  const charges = trip.costs.reduce((sum, item) => sum + item.amount_cny, 0)
  const tickets = trip.activities.reduce((sum, item) => sum + item.est_cost_cny, 0)
  return charges + tickets
}

export function createDelayDraft(
  trip: Trip,
  eventRevision: number,
): { event: TripEvent; draft: Draft } {
  const a01 = trip.activities.find((item) => item.activity_id === 'a01')
  const a02 = trip.activities.find((item) => item.activity_id === 'a02')
  if (!a01 || !a02) {
    throw new Error('演示数据缺少 a01 / a02 活动')
  }

  const option: DraftOption = {
    option_id: 'OPT_A',
    title: '推迟博物馆入场，压缩东湖绿道',
    description: '把省博物馆参观顺延 45 分钟，东湖绿道相应后移，避免与预约时间冲突。',
    feasibility: 'conditional',
    changed_activity_ids: ['a01', 'a02'],
    cost_delta_cny: 0,
    warnings: ['博物馆预约迟到规则尚未确认，可能需要重新预约'],
    requires_external_actions: ['核实原预约的入场条件'],
    unknown_fields: ['reservation_rule'],
    changes: [
      { activity_id: 'a01', start_at: shiftIso(a01.start_at, 45), end_at: shiftIso(a01.end_at, 45) },
      { activity_id: 'a02', start_at: shiftIso(a02.start_at, 45), end_at: shiftIso(a02.end_at, 45) },
    ],
  }

  const event: TripEvent = {
    event_id: 'E001',
    trip_id: trip.trip_id,
    type: 'transport_delay',
    status: 'active',
    source_type: 'simulation',
    confidence: 'scenario_assumed',
    affects_activity_ids: ['a01'],
    reported_at: nowIso(),
    detail: '火车晚点 45 分钟（模拟上报）',
  }

  const draft: Draft = {
    draft_id: 'D001',
    trip_id: trip.trip_id,
    base_version: trip.formal_version,
    event_revision: eventRevision,
    event_ids: ['E001'],
    status: 'awaiting_confirmation',
    official_version_unchanged: true,
    options: [option],
  }

  return { event, draft }
}

export function createClosureDraft(
  trip: Trip,
  eventRevision: number,
): { event: TripEvent; draft: Draft } {
  const replaceOption: DraftOption = {
    option_id: 'OPT_A',
    title: '把黄鹤楼换成辛亥革命博物院',
    description: '保留第二天上午的博物馆参观，把受闭馆影响的活动替换为同区域备选。',
    feasibility: 'conditional',
    changed_activity_ids: ['a03'],
    cost_delta_cny: 45,
    warnings: ['新地点开放状态与门票价格尚未核实'],
    requires_external_actions: ['核实辛亥革命博物院当日预约与入场要求'],
    unknown_fields: ['opening_hours', 'ticket_price'],
    changes: [
      {
        activity_id: 'a03',
        poi_id: 'WH05',
        name: '辛亥革命博物院',
        est_cost_cny: 45,
        opening_status: 'unknown',
        rule_verification: 'UNKNOWN',
        unknown_fields: ['opening_hours', 'ticket_price'],
      },
    ],
  }

  const freeOption: DraftOption = {
    option_id: 'OPT_B',
    title: '第二天上午改为自由活动',
    description: '直接删去受影响的景点，给团队留出机动时间，同时降低预算。',
    feasibility: 'feasible',
    changed_activity_ids: ['a03'],
    cost_delta_cny: -70,
    warnings: ['第二天上午没有固定安排，需要自行决定去向'],
    requires_external_actions: [],
    unknown_fields: [],
    changes: [{ activity_id: 'a03', remove: true }],
  }

  const event: TripEvent = {
    event_id: 'E002',
    trip_id: trip.trip_id,
    type: 'place_closure',
    status: 'active',
    source_type: 'simulation',
    confidence: 'scenario_assumed',
    affects_activity_ids: ['a03'],
    reported_at: nowIso(),
    detail: '黄鹤楼临时闭馆（模拟上报）',
  }

  const draft: Draft = {
    draft_id: 'D002',
    trip_id: trip.trip_id,
    base_version: trip.formal_version,
    event_revision: eventRevision,
    event_ids: ['E001', 'E002'],
    status: 'awaiting_confirmation',
    official_version_unchanged: true,
    options: [replaceOption, freeOption],
  }

  return { event, draft }
}

export function applyOption(
  trip: Trip,
  draft: Draft,
  option: DraftOption,
): { trip: Trip; version: VersionRecord } {
  const changes = new Map<string, ActivityChange>(option.changes.map((item) => [item.activity_id, item]))

  const activities = trip.activities
    .filter((activity) => !changes.get(activity.activity_id)?.remove)
    .map((activity) => {
      const change = changes.get(activity.activity_id)
      if (!change) {
        return activity
      }
      const next: Activity = { ...activity }
      if (change.poi_id !== undefined) next.poi_id = change.poi_id
      if (change.name !== undefined) next.name = change.name
      if (change.start_at !== undefined) next.start_at = change.start_at
      if (change.end_at !== undefined) next.end_at = change.end_at
      if (change.est_cost_cny !== undefined) next.est_cost_cny = change.est_cost_cny
      if (change.opening_status !== undefined) next.opening_status = change.opening_status
      if (change.rule_verification !== undefined) next.rule_verification = change.rule_verification
      if (change.booking_status !== undefined) next.booking_status = change.booking_status
      if (change.unknown_fields !== undefined) next.unknown_fields = change.unknown_fields
      return next
    })

  const version: VersionRecord = {
    formal_version: trip.formal_version + 1,
    created_at: nowIso(),
    note: `确认 ${draft.draft_id}/${option.option_id}（模拟）`,
  }

  return {
    trip: {
      ...trip,
      formal_version: version.formal_version,
      event_revision: Math.max(trip.event_revision, draft.event_revision),
      activities,
    },
    version,
  }
}
