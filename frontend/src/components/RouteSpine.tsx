import type { ReactNode } from 'react'
import type { Activity, EventView, TravelPlan, TripView } from '../types.ts'
import { poiName, ruleByPoiId } from '../services/dataset.ts'
import { formatCny } from '../services/money.ts'
import { formatDate, formatTime } from '../services/time.ts'
import { Icon, Badge } from './ui.tsx'

interface Props {
  trip: TripView
  candidatePlan: TravelPlan | null
  candidateLabel: string | null
}

interface DiffMaps {
  changed: Map<string, Activity>
  added: Activity[]
  removedIds: Set<string>
}

function buildDiff(base: TravelPlan, candidate: TravelPlan | null): DiffMaps {
  if (!candidate) return { changed: new Map(), added: [], removedIds: new Set() }
  const baseById = new Map(base.activities.map((activity) => [activity.id, activity]))
  const candidateById = new Map(candidate.activities.map((activity) => [activity.id, activity]))
  const changed = new Map<string, Activity>()
  for (const activity of candidate.activities) {
    const original = baseById.get(activity.id)
    if (original && JSON.stringify(original) !== JSON.stringify(activity)) {
      changed.set(activity.id, activity)
    }
  }
  const added = candidate.activities.filter((activity) => !baseById.has(activity.id))
  const removedIds = new Set(
    base.activities.filter((activity) => !candidateById.has(activity.id)).map((activity) => activity.id),
  )
  return { changed, added, removedIds }
}

function eventIso(event: EventView): string | null {
  return event.kind === 'poi_closed' ? event.effective_at : event.earliest_start_at
}

function eventDetail(event: EventView): string {
  if (event.kind === 'train_delay') {
    return `${poiName(event.poi_id ?? '') || event.activity_id || '受影响活动'} · 最早可开始 ${formatTime(
      event.earliest_start_at,
    )}`
  }
  return `${poiName(event.poi_id ?? '')} · ${formatTime(event.effective_at)} 起关闭`
}

function ActivityRow({
  activity,
  isAdded,
  removed,
  changedTo,
  locked,
}: {
  activity: Activity
  isAdded: boolean
  removed: boolean
  changedTo?: Activity
  locked: boolean
}) {
  const rule = ruleByPoiId.get(activity.poi_id)
  const flags: ReactNode[] = []
  const openTone = activity.opening_status === 'confirmed_open' ? 'pass' : activity.opening_status === 'confirmed_closed' ? 'fail' : 'unknown'
  flags.push(
    <Badge key="open" tone={openTone}>
      {activity.opening_status === 'confirmed_open'
        ? '开放已声明'
        : activity.opening_status === 'confirmed_closed'
          ? '已关闭'
          : '开放未核实'}
    </Badge>,
  )
  if (activity.booking_required) {
    flags.push(
      <Badge key="booking" tone={activity.booking_status === 'confirmed' ? 'pass' : activity.booking_status === 'not_confirmed' ? 'fail' : 'unknown'}>
        {activity.booking_status === 'confirmed' ? '预约已声明' : activity.booking_status === 'not_confirmed' ? '预约未确认' : '预约未知'}
      </Badge>,
    )
  }
  if (isAdded) flags.push(<Badge key="added" tone="pass">候选新增</Badge>)
  if (removed) flags.push(<Badge key="removed" tone="fail">候选移除</Badge>)
  if (changedTo) flags.push(<Badge key="changed" tone="warn">候选调整</Badge>)
  if (locked) {
    flags.push(
      <Badge key="locked" tone="neutral">
        <Icon name="lock" size={11} /> 已锁定
      </Badge>,
    )
  }

  return (
    <li
      className={`activity ${isAdded ? 'is-added' : ''} ${changedTo ? 'is-changed' : ''}`}
      data-testid="activity-row"
    >
      <div className="activity-time">
        {changedTo ? (
          <>
            <span className="prev-time">
              {formatTime(activity.start_at)}–{formatTime(activity.end_at)}
            </span>
            <span className="next-time">
              {formatTime(changedTo.start_at)}–{formatTime(changedTo.end_at)}
            </span>
          </>
        ) : (
          <>
            {formatTime(activity.start_at)}
            <br />
            {formatTime(activity.end_at)}
          </>
        )}
      </div>
      <div className="activity-body">
        <div className="activity-main">
          <span className="activity-name">{poiName(activity.poi_id)}</span>
          <span className="activity-id">{activity.id}</span>
        </div>
        <p className="activity-sub">
          {activity.poi_id}
          {rule ? ` · 规则票价 ${formatCny(rule.ticket_price_cny)}（${rule.verification_status}）` : ''}
        </p>
        <div className="activity-flags">{flags}</div>
        <p className="activity-note">
          交通{' '}
          {activity.transport_minutes_from_previous === null
            ? '首段/未知'
            : `${activity.transport_minutes_from_previous} 分钟`}{' '}
          · 步行{' '}
          {activity.walking_minutes_from_previous === null
            ? '首段/未知'
            : `${activity.walking_minutes_from_previous} 分钟`}
          {activity.booking_required ? ' · 需预约' : ''}
        </p>
      </div>
    </li>
  )
}

export function RouteSpine({ trip, candidatePlan, candidateLabel }: Props) {
  const plan = trip.current_plan.plan
  const diff = buildDiff(plan, candidatePlan)

  const dates = new Set<string>()
  for (const activity of plan.activities) dates.add(formatDate(activity.start_at))
  for (const activity of diff.added) dates.add(formatDate(activity.start_at))
  for (const event of trip.events) {
    const iso = eventIso(event)
    if (iso) dates.add(formatDate(iso))
  }
  const sortedDates = [...dates].filter(Boolean).sort()

  return (
    <section className="spine" aria-label="任务脊柱">
      <div className="section-head">
        <div>
          <p className="section-kicker">Mission Spine</p>
          <h2 className="section-title">
            任务脊柱 <Badge tone="neutral">V{trip.current_version}</Badge>
          </h2>
        </div>
        <div className="section-head-right">
          <div className="legend">
            <span className="legend-item">
              <Badge tone={plan.activities.some(a=>a.poi_id.startsWith('amap:'))?'neutral':'sim'}>{plan.activities.some(a=>a.poi_id.startsWith('amap:'))?'地图地点':'模拟'}</Badge> 来源单独标注
            </span>
            <span className="legend-item">
              <Badge tone="unknown">未知</Badge> 不当作通过
            </span>
            <span className="legend-item">
              <Badge tone="warn">信号</Badge> 异常事件
            </span>
          </div>
        </div>
      </div>

      {candidatePlan && candidateLabel && (
        <div className="preview-note">
          <Icon name="arrow" size={14} />
          正在预览候选 {candidateLabel} 的差异：{diff.changed.size} 处调整 · {diff.added.length} 项新增 ·{' '}
          {diff.removedIds.size} 项移除（不会改变正式版本）
        </div>
      )}

      {sortedDates.length === 0 && <p className="form-hint">还没有活动；请先创建行程。</p>}

      {sortedDates.map((date, dayIndex) => {
        type Item =
          | { kind: 'activity'; iso: number; activity: Activity; added: boolean }
          | { kind: 'event'; iso: number; event: EventView }
        const items: Item[] = []
        for (const activity of plan.activities) {
          if (formatDate(activity.start_at) !== date) continue
          items.push({ kind: 'activity', iso: Date.parse(activity.start_at), activity, added: false })
        }
        for (const activity of diff.added) {
          if (formatDate(activity.start_at) !== date) continue
          items.push({ kind: 'activity', iso: Date.parse(activity.start_at), activity, added: true })
        }
        for (const event of trip.events) {
          const iso = eventIso(event)
          if (!iso || formatDate(iso) !== date) continue
          items.push({ kind: 'event', iso: Date.parse(iso), event })
        }
        items.sort((left, right) => left.iso - right.iso)

        return (
          <article className="day" key={date}>
            <div className="day-head">
              <span className="day-label">Day {String(dayIndex + 1).padStart(2, '0')}</span>
              <span className="day-date">{date}</span>
              <span className="day-rule" />
            </div>
            <ol className="day-list" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {items.map((item) => {
                if (item.kind === 'event') {
                  const tone = item.event.verification_status === 'verified' ? 'pass' : 'unknown'
                  return (
                    <li className="signal-row" key={`event-${item.event.event_id}`}>
                      <div className="signal-time">{formatTime(eventIso(item.event))}</div>
                      <div className="signal-card" data-testid="event-row">
                        <div className="signal-head">
                          <span className="signal-kind">
                            {item.event.kind === 'train_delay' ? 'SIGNAL · 晚点' : 'SIGNAL · 闭馆'}
                          </span>
                          <span className="signal-title">
                            {item.event.event_id} · {eventDetail(item.event)}
                          </span>
                          <Badge tone="warn">{item.event.active ? 'active' : '已解除'}</Badge>
                          <Badge tone={tone}>
                            {item.event.verification_status === 'verified' ? item.event.source === 'simulation' ? '模拟已核实' : '有核实记录' : '未核实'}
                          </Badge>
                        </div>
                        <p className="signal-detail">
                          来源 {item.event.source} · {item.event.evidence_ref}
                        </p>
                        <div className="signal-meta">
                          <span>revision {item.event.revision}</span>
                          <span>B 事件修订 #{trip.event_revision}</span>
                        </div>
                      </div>
                    </li>
                  )
                }
                const { activity } = item
                return (
                  <ActivityRow
                    key={`${activity.id}-${item.added ? 'added' : 'base'}`}
                    activity={activity}
                    isAdded={item.added}
                    removed={!item.added && diff.removedIds.has(activity.id)}
                    changedTo={!item.added ? diff.changed.get(activity.id) : undefined}
                    locked={trip.locked_activity_ids.includes(activity.id)}
                  />
                )
              })}
            </ol>
          </article>
        )
      })}

      {diff.removedIds.size > 0 && (
        <div>
          {[...diff.removedIds].map((id) => (
            <div className="ghost-row" key={`removed-${id}`}>
              <Icon name="close" size={13} /> 候选将移除：{id} · {poiName(plan.activities.find((a) => a.id === id)?.poi_id ?? '')}
            </div>
          ))}
        </div>
      )}

      {plan.activities.length > 0 && (
        <p className="activity-note" style={{ marginTop: 'var(--s3)' }}>
          金额口径 {formatCny(trip.current_plan.budget.conservative_total_cny)}（已付 + 待付 − 已到账退款）；
          {plan.activities.some(a=>a.poi_id.startsWith('amap:'))?'路线与天气来源见推荐详情，费用为计划估算。':'当前规则与证据来自模拟测试，不构成现实事实。'}
        </p>
      )}
    </section>
  )
}
