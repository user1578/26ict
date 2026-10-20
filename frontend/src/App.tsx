import { useState } from 'react'
import './App.css'
import { SourceBadge } from './components/Badges.tsx'
import { BudgetPanel } from './components/BudgetPanel.tsx'
import { CreateTripForm } from './components/CreateTripForm.tsx'
import type { TripFormValues } from './components/CreateTripForm.tsx'
import { DraftPanel } from './components/DraftPanel.tsx'
import { Timeline } from './components/Timeline.tsx'
import { applyOption, buildTrip, createClosureDraft, createDelayDraft } from './services/demoApi.ts'
import type { Draft, DraftOption, Trip, TripEvent, VersionRecord } from './types.ts'

const DEFAULT_FORM: TripFormValues = {
  city: '武汉',
  startDate: '2026-11-18',
  endDate: '2026-11-19',
  partySize: '3',
  budget: '1300',
  walkingLimit: '20',
  returnTime: '17:00',
}

const eventLabels: Record<TripEvent['type'], string> = {
  transport_delay: '交通延误',
  weather: '天气异常',
  place_closure: '景区关闭',
}

export default function App() {
  const [form, setForm] = useState<TripFormValues>(DEFAULT_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [trip, setTrip] = useState<Trip | null>(null)
  const [events, setEvents] = useState<TripEvent[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [versions, setVersions] = useState<VersionRecord[]>([])
  const [notice, setNotice] = useState<string | null>(null)

  const handleChange = (patch: Partial<TripFormValues>) => {
    setForm((prev) => ({ ...prev, ...patch }))
    setFormError(null)
  }

  const handleCreate = () => {
    const partySize = Number(form.partySize)
    const budgetCny = Number(form.budget)
    const walkingLimit = Number(form.walkingLimit)

    if (!form.city.trim()) {
      setFormError('请填写城市')
      return
    }
    if (!form.startDate || !form.endDate) {
      setFormError('请选择出发与返回日期')
      return
    }
    if (form.endDate < form.startDate) {
      setFormError('返回日期不能早于出发日期')
      return
    }
    if (!Number.isFinite(partySize) || partySize < 1 || partySize > 10) {
      setFormError('同行人数应在 1～10 人之间')
      return
    }
    if (!Number.isFinite(budgetCny) || budgetCny <= 0) {
      setFormError('预算必须大于 0')
      return
    }
    if (!Number.isFinite(walkingLimit) || walkingLimit < 0) {
      setFormError('单段步行上限不能为负数')
      return
    }

    const created = buildTrip({
      city: form.city.trim(),
      startDate: form.startDate,
      endDate: form.endDate,
      partySize,
      budgetCny,
      walkingLimit,
      returnTime: form.returnTime,
    })

    setTrip(created)
    setEvents([])
    setDrafts([])
    setVersions([{ formal_version: 1, created_at: new Date().toISOString(), note: '生成初始正式行程（模拟）' }])
    setNotice('已生成模拟正式行程 V1；尚未连接 FastAPI 与 AgentArts。')
    setFormError(null)
  }

  const handleDelay = () => {
    if (!trip) return
    if (events.some((event) => event.type === 'transport_delay')) {
      setNotice('延误已经上报过了（E001）。')
      return
    }
    const revision = trip.event_revision + 1
    const result = createDelayDraft(trip, revision)
    setTrip({ ...trip, event_revision: revision })
    setEvents((prev) => [...prev, result.event])
    setDrafts((prev) => [...prev, result.draft])
    setNotice('已记录 E001（延误 45 分钟），生成候选 D001。')
  }

  const handleClosure = () => {
    if (!trip) return
    if (!events.some((event) => event.type === 'transport_delay')) {
      setNotice('请先上报延误，再上报闭馆，才能演示旧草案失效。')
      return
    }
    if (events.some((event) => event.type === 'place_closure')) {
      setNotice('闭馆已经上报过了（E002）。')
      return
    }
    const revision = trip.event_revision + 1
    const result = createClosureDraft(trip, revision)
    setTrip({ ...trip, event_revision: revision })
    setEvents((prev) => [...prev, result.event])
    setDrafts((prev) => [
      ...prev.map((draft) =>
        draft.status === 'awaiting_confirmation'
          ? { ...draft, status: 'superseded' as const, superseded_by: result.draft.draft_id }
          : draft,
      ),
      result.draft,
    ])
    setNotice('已记录 E002（景区闭馆）；旧候选 D001 失效，生成 D002。')
  }

  const handleConfirm = (draftId: string, option: DraftOption) => {
    if (!trip) return
    const target = drafts.find((draft) => draft.draft_id === draftId)
    if (!target || target.status !== 'awaiting_confirmation') return

    const result = applyOption(trip, target, option)
    setTrip(result.trip)
    setVersions((prev) => [...prev, result.version])
    setDrafts((prev) =>
      prev.map((draft) => {
        if (draft.draft_id === draftId) {
          return { ...draft, status: 'confirmed' as const }
        }
        if (draft.status === 'awaiting_confirmation') {
          return { ...draft, status: 'superseded' as const, superseded_by: draftId }
        }
        return draft
      }),
    )
    setNotice(`已确认 ${draftId} / ${option.option_id}，正式版本更新为 V${result.trip.formal_version}。`)
  }

  const handleReset = () => {
    setTrip(null)
    setEvents([])
    setDrafts([])
    setVersions([])
    setNotice(null)
    setFormError(null)
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <p className="eyebrow">TravelGuard · 旅途智盾</p>
          <h1>多事件约束感知与最小必要重规划</h1>
        </div>
        <div className="topbar-actions">
          <span className="badge badge-source-simulation">本地模拟数据</span>
          {trip && <span className="version-chip">正式版本 V{trip.formal_version}</span>}
          {trip && (
            <button type="button" className="ghost" onClick={handleReset}>
              重新开始
            </button>
          )}
        </div>
      </header>

      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}

      {!trip ? (
        <CreateTripForm values={form} error={formError} onChange={handleChange} onSubmit={handleCreate} />
      ) : (
        <div className="layout">
          <main className="main-column">
            <section className="card summary">
              <h2>
                {trip.city} · {trip.dates[0]} 至 {trip.dates[1]}
              </h2>
              <dl className="kv">
                <div>
                  <dt>同行人数</dt>
                  <dd>{trip.party_size} 人</dd>
                </div>
                <div>
                  <dt>预算</dt>
                  <dd>¥{trip.budget_cny}</dd>
                </div>
                <div>
                  <dt>单段步行上限</dt>
                  <dd>{trip.constraints.max_walking_minutes_per_leg} 分钟</dd>
                </div>
                <div>
                  <dt>返程截止</dt>
                  <dd>{trip.constraints.return_deadline.slice(11, 16)}</dd>
                </div>
                <div>
                  <dt>事件修订</dt>
                  <dd>#{trip.event_revision}</dd>
                </div>
              </dl>
            </section>

            <BudgetPanel trip={trip} />
            <Timeline activities={trip.activities} />
            <DraftPanel drafts={drafts} onConfirm={handleConfirm} />
          </main>

          <aside className="side-column">
            <section className="card">
              <h2>异常事件</h2>
              <div className="event-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={handleDelay}
                  disabled={events.some((event) => event.type === 'transport_delay')}
                >
                  上报交通延误 45 分钟
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={handleClosure}
                  disabled={events.some((event) => event.type === 'place_closure')}
                >
                  上报景区闭馆
                </button>
              </div>

              {events.length === 0 ? (
                <p className="hint">按“延误 → 闭馆”的顺序上报，可以看到旧草案失效与双异常重规划。</p>
              ) : (
                <ul className="event-list">
                  {events.map((event) => (
                    <li key={event.event_id}>
                      <div className="event-head">
                        <strong>
                          {event.event_id} · {eventLabels[event.type]}
                        </strong>
                        <SourceBadge value={event.source_type} />
                      </div>
                      <p className="meta">{event.detail}</p>
                      <p className="meta">
                        影响活动：{event.affects_activity_ids.join('、')} · 状态：{event.status}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card">
              <h2>版本历史</h2>
              <ul className="version-list">
                {versions.map((item) => (
                  <li key={item.formal_version}>
                    <strong>V{item.formal_version}</strong>
                    <span className="meta">{item.note}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="card muted">
              <h2>说明</h2>
              <p>本 Demo 全部使用本地模拟数据，未连接 FastAPI 与 AgentArts。</p>
              <p>
                真实接口接入后，把 <code>services/demoApi.ts</code> 换成 API 调用即可，页面组件不用重写。
              </p>
            </section>
          </aside>
        </div>
      )}

      <footer className="footer">TravelGuard 前端 Demo · 模拟数据 · 2026</footer>
    </div>
  )
}
