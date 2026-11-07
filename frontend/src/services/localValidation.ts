/** 本地核验：按 B 端 travel_validation.py + logic.py 的规则实现，
 *  仅用于 mock 模式与规划器预检；真实模式一律以 B 返回的 validation 为准。 */

import type {
  Activity,
  EventView,
  TravelPlan,
  TripConstraints,
  Validation,
} from '../types.ts'
import { compareIso, minutesBetween } from './time.ts'
import { cnyFromCents, toCents } from './money.ts'

interface CheckDraft {
  name: string
  status: Validation['overall']
  detail: string
}

function activitySignature(activity: Activity): string {
  return JSON.stringify([
    activity.id,
    activity.poi_id,
    activity.start_at,
    activity.end_at,
    activity.transport_minutes_from_previous,
    activity.walking_minutes_from_previous,
    activity.opening_status,
    activity.booking_required,
    activity.booking_status,
  ])
}

function add(checks: CheckDraft[], name: string, status: Validation['overall'], detail: string) {
  checks.push({ name, status, detail })
}

export interface LocalValidationInput {
  plan: TravelPlan
  constraints: TripConstraints
  events: EventView[]
  lockedIds: string[]
  /** 当前正式版本方案（生成草案/确认时用于状态类检查）。 */
  previous: TravelPlan | null
  /** 全部正式历史里出现过 booking_required 的 POI 集合。 */
  requiredBookingPois: Set<string>
}

export function validatePlanLocally(input: LocalValidationInput): Validation {
  const { plan, constraints, events, lockedIds, previous, requiredBookingPois } = input
  const checks: CheckDraft[] = []
  const activities = plan.activities

  // ---- time_check ----
  const outOfOrder = activities.some(
    (activity, index) => index > 0 && compareIso(activity.start_at, activities[index - 1].start_at) < 0,
  )
  const overlaps = activities.some(
    (activity, index) => index > 0 && compareIso(activity.start_at, activities[index - 1].end_at) < 0,
  )
  const tooShort = activities.some((activity, index) => {
    if (index === 0 || activity.transport_minutes_from_previous === null) return false
    return minutesBetween(activities[index - 1].end_at, activity.start_at) < activity.transport_minutes_from_previous
  })
  const missingTransport = activities.slice(1).some((activity) => activity.transport_minutes_from_previous === null)
  if (outOfOrder) {
    add(checks, 'time_check', 'FAIL', '活动未按时间先后排列')
  } else if (overlaps) {
    add(checks, 'time_check', 'FAIL', '存在活动时间重叠')
  } else if (tooShort) {
    add(checks, 'time_check', 'FAIL', '活动间隔不足以完成已知交通时间')
  } else if (activities.length > 1 && missingTransport) {
    add(checks, 'time_check', 'UNKNOWN', '缺少部分活动之间的交通耗时')
  } else {
    add(checks, 'time_check', 'PASS', '已知活动时段与交通耗时没有冲突')
  }

  // ---- opening_check ----
  if (activities.some((activity) => activity.opening_status === 'confirmed_closed')) {
    add(checks, 'opening_check', 'FAIL', '包含已知关闭的地点')
  } else if (activities.some((activity) => activity.opening_status === 'unknown')) {
    add(checks, 'opening_check', 'UNKNOWN', '部分地点开放信息未核实')
  } else {
    add(checks, 'opening_check', 'PASS', '输入的地点开放状态均为已核实开放')
  }

  // ---- booking_check ----
  const bookings = activities.filter((activity) => activity.booking_required).map((activity) => activity.booking_status)
  if (bookings.length === 0) {
    add(checks, 'booking_check', 'NOT_APPLICABLE', '没有要求核验的预约')
  } else if (bookings.includes('not_confirmed')) {
    add(checks, 'booking_check', 'FAIL', '存在未确认的必需预约')
  } else if (bookings.includes('unknown')) {
    add(checks, 'booking_check', 'UNKNOWN', '存在状态未知的必需预约')
  } else {
    add(checks, 'booking_check', 'PASS', '输入的必需预约均已确认')
  }

  // ---- budget_check ----
  const paid = plan.charges
    .filter((charge) => charge.status === 'paid')
    .reduce((total, charge) => total + toCents(charge.amount_cny), 0)
  const planned = plan.charges
    .filter((charge) => charge.status === 'planned')
    .reduce((total, charge) => total + toCents(charge.amount_cny), 0)
  const received = plan.refunds
    .filter((refund) => refund.status === 'received')
    .reduce((total, refund) => total + toCents(refund.amount_cny), 0)
  const total = paid + planned - received
  const budget = toCents(constraints.budget_cny)
  add(
    checks,
    'budget_check',
    total <= budget ? 'PASS' : 'FAIL',
    `保守预计总支出 ${cnyFromCents(total)} 元，预算 ${constraints.budget_cny} 元`,
  )

  // ---- walking_check ----
  const legs = activities.slice(1)
  if (constraints.max_walking_minutes_per_leg === null) {
    add(checks, 'walking_check', 'NOT_APPLICABLE', '未设置单段步行硬限制')
  } else if (
    legs.some(
      (activity) =>
        activity.walking_minutes_from_previous !== null &&
        activity.walking_minutes_from_previous > (constraints.max_walking_minutes_per_leg ?? 0),
    )
  ) {
    add(checks, 'walking_check', 'FAIL', '部分步行路段超过限制')
  } else if (legs.some((activity) => activity.walking_minutes_from_previous === null)) {
    add(checks, 'walking_check', 'UNKNOWN', '部分步行路段耗时未知')
  } else {
    add(checks, 'walking_check', 'PASS', '已提供的步行路段均满足限制')
  }

  // ---- return_check / return_timeline_check ----
  if (constraints.return_deadline === null) {
    add(checks, 'return_check', 'NOT_APPLICABLE', '未设置返程硬截止时间')
  } else if (plan.arrival_at_return_station === null) {
    add(checks, 'return_check', 'UNKNOWN', '缺少到达返程车站的预计时间')
  } else if (compareIso(plan.arrival_at_return_station, constraints.return_deadline) <= 0) {
    add(checks, 'return_check', 'PASS', '返程到站时间符合截止要求')
  } else {
    add(checks, 'return_check', 'FAIL', '预计抵达返程车站超过截止时间')
  }
  if (plan.arrival_at_return_station !== null) {
    const latestEnd = activities.reduce(
      (latest, activity) => (compareIso(activity.end_at, latest) > 0 ? activity.end_at : latest),
      activities[0].end_at,
    )
    add(
      checks,
      'return_timeline_check',
      compareIso(plan.arrival_at_return_station, latestEnd) >= 0 ? 'PASS' : 'FAIL',
      compareIso(plan.arrival_at_return_station, latestEnd) >= 0
        ? '返程到站时间不早于行程结束'
        : '返程到站时间早于行程结束',
    )
  }

  // ---- state_check（历史锁定活动不可改）----
  if (previous && lockedIds.length > 0) {
    const indexed = new Map(activities.map((activity) => [activity.id, activity]))
    const changed = previous.activities
      .filter((activity) => lockedIds.includes(activity.id))
      .filter((activity) => {
        const current = indexed.get(activity.id)
        return !current || activitySignature(current) !== activitySignature(activity)
      })
      .map((activity) => activity.id)
    add(
      checks,
      'state_check',
      changed.length > 0 ? 'FAIL' : 'PASS',
      changed.length > 0 ? `锁定活动被删除或修改：${changed.join(',')}` : '锁定活动保持不变',
    )
  } else {
    add(checks, 'state_check', 'NOT_APPLICABLE', '未提供不可修改的历史活动')
  }

  // ---- evidence_check（持久化接口新增）----
  const missingEvidence: string[] = []
  for (const activity of activities) {
    const needsEvidence =
      activity.opening_status === 'confirmed_open' ||
      (activity.booking_required && activity.booking_status === 'confirmed')
    if (needsEvidence && !plan.activity_evidence[activity.id]) {
      missingEvidence.push(activity.id)
    }
  }
  for (const flow of [...plan.charges, ...plan.refunds]) {
    if ((flow.status === 'paid' || flow.status === 'received') && !plan.financial_evidence[flow.id]) {
      missingEvidence.push(flow.id)
    }
  }
  add(
    checks,
    'evidence_check',
    missingEvidence.length === 0 ? 'PASS' : 'UNKNOWN',
    missingEvidence.length === 0
      ? '声明的已核实事实均有调用方提供的证据引用'
      : `缺少事实证据引用：${missingEvidence.join(',')}`,
  )

  if (previous) {
    // ---- financial_state_check ----
    const oldFacts = [...previous.charges, ...previous.refunds].filter(
      (flow) => flow.status === 'paid' || flow.status === 'received',
    )
    const newFacts = [...plan.charges, ...plan.refunds].filter(
      (flow) => flow.status === 'paid' || flow.status === 'received',
    )
    const sameFacts =
      JSON.stringify(oldFacts.map((flow) => [flow.id, flow.amount_cny, flow.status]).sort()) ===
      JSON.stringify(newFacts.map((flow) => [flow.id, flow.amount_cny, flow.status]).sort())
    const sameEvidence = oldFacts.every(
      (flow) => plan.financial_evidence[flow.id] === previous.financial_evidence[flow.id],
    )
    add(
      checks,
      'financial_state_check',
      sameFacts && sameEvidence ? 'PASS' : 'FAIL',
      sameFacts && sameEvidence
        ? '已支付费用和已到账退款保持不变；方案不会执行资金操作'
        : '草案不得新增、删除或修改已支付/已到账事实及证据',
    )

    // ---- locked_evidence_check ----
    const lockedEvidenceOk = lockedIds.every(
      (id) => plan.activity_evidence[id] === previous.activity_evidence[id],
    )
    add(
      checks,
      'locked_evidence_check',
      lockedEvidenceOk ? 'PASS' : 'FAIL',
      lockedEvidenceOk ? '锁定历史活动证据保持不变' : '锁定历史活动证据被修改',
    )

    // ---- booking_state_check ----
    const priorById = new Map(previous.activities.map((activity) => [activity.id, activity]))
    const bookingClaims: string[] = []
    for (const activity of activities) {
      if (activity.booking_status !== 'confirmed') continue
      const original = priorById.get(activity.id)
      const changed =
        !original ||
        original.booking_status !== 'confirmed' ||
        original.poi_id !== activity.poi_id ||
        original.start_at !== activity.start_at ||
        original.end_at !== activity.end_at ||
        plan.activity_evidence[activity.id] !== previous.activity_evidence[activity.id]
      if (changed) bookingClaims.push(activity.id)
    }
    const downgraded = activities
      .filter((activity) => requiredBookingPois.has(activity.poi_id) && !activity.booking_required)
      .map((activity) => activity.id)
    add(
      checks,
      'booking_state_check',
      bookingClaims.length > 0 || downgraded.length > 0 ? 'FAIL' : 'PASS',
      bookingClaims.length > 0 || downgraded.length > 0
        ? '草案不能宣称新预约/改期已完成，或降低已知地点预约要求'
        : '未新增预约完成事实，保留已知预约要求；未执行取消或改签',
    )
  }

  // ---- 异常事件检查 ----
  const indexed = new Map(activities.map((activity) => [activity.id, activity]))
  for (const event of events) {
    if (!event.active) continue
    if (event.verification_status !== 'verified') {
      add(checks, `event:${event.event_id}:evidence`, 'UNKNOWN', '异常事实尚未核实')
    }
    if (event.kind === 'train_delay') {
      const target = event.activity_id ? indexed.get(event.activity_id) : undefined
      let satisfied =
        target !== undefined &&
        event.earliest_start_at !== null &&
        compareIso(target.start_at, event.earliest_start_at) >= 0
      if (previous && target) {
        const original = previous.activities.find((activity) => activity.id === event.activity_id)
        satisfied = satisfied && original !== undefined && original.poi_id === target.poi_id
      }
      add(
        checks,
        `event:${event.event_id}`,
        satisfied ? 'PASS' : 'FAIL',
        satisfied ? '已遵守晚点后的最早开始时间' : '晚点活动被删除、替换或安排过早',
      )
    } else {
      const conflicts = activities
        .filter(
          (activity) =>
            activity.poi_id === event.poi_id &&
            event.effective_at !== null &&
            compareIso(activity.end_at, event.effective_at) > 0,
        )
        .map((activity) => activity.id)
      add(
        checks,
        `event:${event.event_id}`,
        conflicts.length > 0 ? 'FAIL' : 'PASS',
        conflicts.length > 0
          ? `关闭生效后仍安排该地点：${conflicts.join(',')}`
          : '关闭生效后未安排该地点',
      )
    }
  }

  const statuses = new Set(checks.map((check) => check.status))
  const overall: Validation['overall'] = statuses.has('FAIL')
    ? 'FAIL'
    : statuses.has('UNKNOWN')
      ? 'UNKNOWN'
      : 'PASS'
  return {
    overall,
    checks,
    note: '本地模拟核验：仅用于离线演示，真实模式以 B 端返回的 validation 为准。',
  }
}
