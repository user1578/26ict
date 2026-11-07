/** 前端演示轨迹：A 的 AgentArts 尚未接入，这里按「控制器 → 工具 → 候选」的时序
 *  生成只读展示数据，并始终标注 simulated。接入 A 的真实 trace 后替换本文件即可。 */

import type { EventKind, TripView } from '../types.ts'

export type TraceStatus = 'ok' | 'run' | 'unknown' | 'fail'

export type TraceActor = 'controller' | 'planner' | 'replanner' | 'budget' | 'verify' | 'system'

export interface TraceStep {
  id: string
  actor: TraceActor
  kind: string
  node: string
  tool?: string
  status: TraceStatus
  summary: string
  durationMs?: number
  evidenceRefs?: string[]
}

export interface TraceRun {
  id: string
  intent: string
  simulated: boolean
  steps: TraceStep[]
}

let sequence = 0

function step(
  actor: TraceActor,
  kind: string,
  node: string,
  status: TraceStatus,
  summary: string,
  options: { tool?: string; durationMs?: number; evidenceRefs?: string[] } = {},
): TraceStep {
  sequence += 1
  return { id: `t${sequence}`, actor, kind, node, status, summary, ...options }
}

function run(intent: string, steps: TraceStep[]): TraceRun {
  sequence += 1
  return { id: `run${sequence}`, intent, simulated: true, steps }
}

export function createPlanTrace(trip: TripView): TraceRun {
  const activities = trip.current_plan.plan.activities
  const first = activities[0]
  const last = activities[activities.length - 1]
  return run('CREATE_PLAN', [
    step('controller', 'ROUTE', '控制器识别意图', 'ok', 'CREATE_PLAN · 规划意图 · 置信度 0.94'),
    step(
      'planner',
      'ROUTE',
      'WF_Plan · 读取任务简报',
      'ok',
      `${trip.city ?? '武汉'} · ${trip.start_date ?? '?'} 至 ${trip.end_date ?? '?'} · ${
        trip.party_size ?? '?'
      } 人`,
    ),
    step('planner', 'TOOL', 'search_places', 'ok', '检索候选地点（模拟 POI）', {
      tool: 'search_places',
      durationMs: 620,
    }),
    step('planner', 'TOOL', 'get_place_rules', 'unknown', '5 条规则均为 simulated / unverified', {
      tool: 'get_place_rules',
      durationMs: 380,
      evidenceRefs: first ? [trip.current_plan.plan.activity_evidence[first.id] ?? 'simulation:opening'] : [],
    }),
    step('planner', 'TOOL', 'get_route_options', 'ok', `${activities.length - 1} 段交通耗时已生成`, {
      tool: 'get_route_options',
      durationMs: 940,
    }),
    step('planner', 'TOOL', 'get_weather_risk', 'ok', '逐日预报 + outdoor-v1 阈值（模拟）', {
      tool: 'get_weather_risk',
      durationMs: 410,
    }),
    step('budget', 'BUDGET', 'calculate_budget', 'ok', '已付 / 待付 / 待到账退款按整数分计算', {
      tool: 'calculate_budget',
      durationMs: 120,
    }),
    step('verify', 'VERIFY', 'validate_plan', 'ok', 'PASS · 无 FAIL / UNKNOWN（模拟证据）', {
      tool: 'validate_plan',
      durationMs: 140,
    }),
    step('system', 'WRITE', 'POST /api/trips', 'ok', 'B 端写入正式版本 V1（只接受 PASS）', {
      durationMs: 180,
    }),
    step('system', 'DONE', 'V1 已就绪', 'ok', last ? `末段活动 ${last.id} · 等待异常事件` : '等待异常事件', {
      durationMs: 40,
    }),
  ])
}

export function reportEventTrace(trip: TripView, kind: EventKind, eventId: string): TraceRun {
  const intent = 'REPORT_DISRUPTION'
  const kindLabel = kind === 'train_delay' ? '列车晚点' : '景区闭馆'
  const locked = trip.locked_activity_ids.length
  return run(intent, [
    step('controller', 'ROUTE', '控制器识别意图', 'ok', `${intent} · ${kindLabel} · simulation`),
    step('system', 'TOOL', 'GET /api/trips/{id}', 'ok', `读取最新 event_revision = #${trip.event_revision}`, {
      tool: 'get_trip',
      durationMs: 60,
    }),
    step('system', 'WRITE', `PUT /events/${eventId}`, 'ok', '事件已写入 B（乐观锁 expected_event_revision）', {
      durationMs: 90,
    }),
    step('system', 'TOOL', 'GET /api/trips/{id}', 'ok', '刷新 active events 与三修订号', {
      tool: 'get_trip',
      durationMs: 55,
    }),
    step('replanner', 'ROUTE', 'WF_Replan · 差异分析', 'ok', `锁定 ${locked} 项；只改动受影响段`, {
      durationMs: 380,
      evidenceRefs: ['simulation:event:poi-closure'],
    }),
    step('replanner', 'TOOL', 'get_route_options', 'ok', '重算受影响路段（模拟路线）', {
      tool: 'get_route_options',
      durationMs: 720,
    }),
    step('budget', 'BUDGET', 'calculate_budget', 'ok', '逐候选复算预算增量（pending 退款不抵扣）', {
      tool: 'calculate_budget',
      durationMs: 110,
    }),
    step('verify', 'VERIFY', 'validate_plan', 'ok', '候选核验完成：PASS / UNKNOWN 分开呈现', {
      tool: 'validate_plan',
      durationMs: 150,
    }),
    step('system', 'WRITE', 'POST /drafts', 'ok', '候选已作为草案写入 B，等待你确认', {
      durationMs: 170,
    }),
  ])
}

export function confirmTrace(draftId: string, version: number): TraceRun {
  return run('CONFIRM_DRAFT', [
    step('system', 'WRITE', `POST /drafts/${draftId}/confirm`, 'ok', 'user_confirmed: true · 三修订号绑定', {
      durationMs: 90,
    }),
    step('verify', 'VERIFY', '事务内重新核验', 'ok', 'PASS · 失败则整体回滚', {
      durationMs: 120,
    }),
    step('system', 'DONE', `正式版本 V${version} 生效`, 'ok', '旧候选自动失效，版本账本已更新', {
      durationMs: 40,
    }),
  ])
}

export function restoreTrace(trip: TripView): TraceRun {
  return run('RESTORE_STATE', [
    step('system', 'TOOL', 'GET /api/trips/{id}', 'ok', `读取 ${trip.trip_id}`, {
      tool: 'get_trip',
      durationMs: 70,
    }),
    step('system', 'TOOL', 'GET /drafts + /versions', 'ok', '恢复当前版本、候选与历史', {
      durationMs: 80,
    }),
    step('system', 'DONE', '状态已恢复', 'ok', '刷新页面不会丢失正式版本', { durationMs: 20 }),
  ])
}
