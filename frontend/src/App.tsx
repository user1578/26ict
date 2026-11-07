import { useCallback, useEffect, useMemo, useState } from 'react'
import { AgentRail } from './components/AgentRail.tsx'
import { BudgetRail } from './components/BudgetRail.tsx'
import { DecisionDock } from './components/DecisionDock.tsx'
import { HistoryDrawer } from './components/HistoryDrawer.tsx'
import { MissionBar } from './components/MissionBar.tsx'
import { RouteSpine } from './components/RouteSpine.tsx'
import { SetupScreen, type TripFormValues } from './components/SetupScreen.tsx'
import { SignalSheet } from './components/SignalSheet.tsx'
import { CheckList } from './components/ui.tsx'
import { useTheme } from './hooks/useTheme.ts'
import { readTripId, syncUrl } from './lib/url.ts'
import { ApiError, describeApiError } from './services/apiError.ts'
import {
  confirmTrace,
  createPlanTrace,
  reportEventTrace,
  restoreTrace,
  type TraceRun,
} from './services/agentTrace.ts'
import { apiModeLabel, createApi, resolveApiMode } from './services/client.ts'
import {
  buildCandidatePlans,
  buildClosureEvent,
  buildCreateTripRequest,
  buildDelayEvent,
  buildDraftRequests,
  newId,
  nextEventId,
  type TripFormInput,
} from './services/planner.ts'
import type { DraftView, EventKind, TripView, Validation, VersionView } from './types.ts'

const DEFAULT_FORM: TripFormValues = {
  city: '武汉',
  startDate: '2026-11-18',
  endDate: '2026-11-19',
  partySize: '3',
  budget: '1300',
  walkingLimit: '20',
  returnTime: '17:00',
  stayTogether: true,
}

const RECOVERABLE_CODES = new Set([
  'revision_conflict',
  'draft_token_conflict',
  'draft_stale',
  'event_set_conflict',
])

type Sheet = 'signal' | 'history' | null

export default function App() {
  const [mode] = useState(() => resolveApiMode())
  const api = useMemo(() => createApi(mode), [mode])
  const { theme, toggle: toggleTheme } = useTheme()

  const [form, setForm] = useState<TripFormValues>(DEFAULT_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errorValidation, setErrorValidation] = useState<Validation | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [trip, setTrip] = useState<TripView | null>(null)
  const [drafts, setDrafts] = useState<DraftView[]>([])
  const [versions, setVersions] = useState<VersionView[]>([])
  const [trace, setTrace] = useState<TraceRun | null>(null)
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null)
  const [sheet, setSheet] = useState<Sheet>(null)
  const [restoring, setRestoring] = useState(false)

  const handleChange = (patch: Partial<TripFormValues>) => {
    setForm((previous) => ({ ...previous, ...patch }))
    setFormError(null)
  }

  const refresh = useCallback(
    async (tripId: string) => {
      const [nextTrip, nextDrafts, nextVersions] = await Promise.all([
        api.getTrip(tripId),
        api.getDrafts(tripId),
        api.getVersions(tripId),
      ])
      setTrip(nextTrip)
      setDrafts(nextDrafts)
      setVersions(nextVersions.length > 0 ? nextVersions : [nextTrip.current_plan])
      return nextTrip
    },
    [api],
  )

  const handleError = useCallback(
    async (caught: unknown, tripId: string | null) => {
      const apiError = caught instanceof ApiError ? caught : null
      setError(describeApiError(caught))
      setErrorValidation(apiError?.validation ?? null)
      if (apiError && tripId && RECOVERABLE_CODES.has(apiError.code)) {
        try {
          await refresh(tripId)
          setNotice('服务端状态已变化，已刷新最新版本与候选；请重新对比后再操作。')
        } catch {
          // 刷新失败时保留原始错误
        }
      }
    },
    [refresh],
  )

  const rememberTrip = useCallback(
    (nextTrip: TripView) => {
      if (mode === 'real') syncUrl(nextTrip.trip_id, mode)
    },
    [mode],
  )

  const handleCreate = async () => {
    const partySize = Number(form.partySize)
    const walkingLimit = form.walkingLimit.trim() === '' ? null : Number(form.walkingLimit)
    const budget = form.budget.trim()

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
    if (!Number.isInteger(partySize) || partySize < 1 || partySize > 10) {
      setFormError('同行人数必须是 1～10 的整数')
      return
    }
    if (!/^\d+(\.\d{1,2})?$/.test(budget) || Number(budget) <= 0) {
      setFormError('预算必须是大于 0、最多两位小数的数字')
      return
    }
    if (walkingLimit !== null && (!Number.isInteger(walkingLimit) || walkingLimit < 0)) {
      setFormError('单段步行上限必须是非负整数')
      return
    }

    const input: TripFormInput = {
      city: form.city.trim(),
      startDate: form.startDate,
      endDate: form.endDate,
      partySize,
      budgetCny: budget,
      walkingLimit,
      returnTime: form.returnTime,
      stayTogether: form.stayTogether,
    }

    setBusy(true)
    setFormError(null)
    setError(null)
    setErrorValidation(null)
    try {
      const created = await api.createTrip(buildCreateTripRequest(input))
      setTrip(created)
      setDrafts([])
      setVersions([created.current_plan])
      setTrace(createPlanTrace(created))
      setSelectedDraftId(null)
      setNotice(
        `已创建正式版本 V1（${apiModeLabel(mode)}），核验 ${created.current_plan.validation.overall}。初始方案由前端演示规划器生成，证据为模拟数据。`,
      )
      rememberTrip(created)
    } catch (caught) {
      await handleError(caught, null)
    } finally {
      setBusy(false)
    }
  }

  const reportEvent = async (
    build: (fresh: TripView) => ReturnType<typeof buildDelayEvent>,
    label: string,
    kind: EventKind,
  ) => {
    if (!trip || busy) return
    setBusy(true)
    setError(null)
    setErrorValidation(null)
    setSheet(null)
    try {
      const fresh = await api.getTrip(trip.trip_id)
      const eventId = nextEventId(fresh)
      await api.putEvent(fresh.trip_id, eventId, build(fresh))
      const updated = await api.getTrip(fresh.trip_id)
      const candidates = buildCandidatePlans(updated)
      const draftRequests = buildDraftRequests(updated, candidates)
      for (const draftRequest of draftRequests) {
        await api.createDraft(updated.trip_id, draftRequest)
      }
      const refreshed = await refresh(fresh.trip_id)
      setTrace(reportEventTrace(refreshed ?? updated, kind, eventId))
      setSelectedDraftId(null)
      setNotice(
        `${label}：已记录 ${eventId}（模拟上报），生成 ${draftRequests.length} 份候选草案；请在决策坞对比后确认。`,
      )
      rememberTrip(updated)
    } catch (caught) {
      await handleError(caught, trip.trip_id)
    } finally {
      setBusy(false)
    }
  }

  const handleConfirm = async (draft: DraftView) => {
    if (!trip || busy) return
    setBusy(true)
    setError(null)
    setErrorValidation(null)
    try {
      const version = await api.confirmDraft(trip.trip_id, draft.draft_id, {
        request_id: newId('confirm'),
        base_version: draft.base_version,
        event_revision: draft.event_revision,
        history_revision: draft.history_revision,
        user_confirmed: true,
        confirmed_by: 'demo-user',
      })
      const refreshed = await refresh(trip.trip_id)
      setTrace(confirmTrace(draft.draft_id, version.version))
      setSelectedDraftId(null)
      setNotice(
        `已确认 ${draft.draft_id}，正式版本升级为 V${version.version}；其他候选自动失效，核验结果以 B 端返回为准。`,
      )
      if (refreshed) rememberTrip(refreshed)
    } catch (caught) {
      await handleError(caught, trip.trip_id)
    } finally {
      setBusy(false)
    }
  }

  const handleReset = () => {
    setTrip(null)
    setDrafts([])
    setVersions([])
    setTrace(null)
    setSelectedDraftId(null)
    setNotice(null)
    setError(null)
    setErrorValidation(null)
    setFormError(null)
    setSheet(null)
    if (mode === 'real') syncUrl(null, mode)
  }

  // 恢复：真实模式下按 ?trip= 重新拉取正式状态（刷新不丢）
  useEffect(() => {
    const tripId = readTripId()
    if (!tripId) return
    if (mode === 'mock') {
      setNotice('本地模拟模式无法按链接恢复；请重新创建行程。')
      return
    }
    let cancelled = false
    setRestoring(true)
    void (async () => {
      try {
        const [restoredTrip, restoredDrafts, restoredVersions] = await Promise.all([
          api.getTrip(tripId),
          api.getDrafts(tripId),
          api.getVersions(tripId),
        ])
        if (cancelled) return
        setTrip(restoredTrip)
        setDrafts(restoredDrafts)
        setVersions(restoredVersions.length > 0 ? restoredVersions : [restoredTrip.current_plan])
        setTrace(restoreTrace(restoredTrip))
        setNotice(`已恢复 ${tripId} · 正式版本 V${restoredTrip.current_version}`)
      } catch (caught) {
        if (cancelled) return
        if (caught instanceof ApiError && caught.status === 404) {
          syncUrl(null, mode)
          setNotice('链接中的行程不存在，已回到创建页。')
        } else {
          setError(describeApiError(caught))
          setErrorValidation(caught instanceof ApiError ? caught.validation ?? null : null)
        }
      } finally {
        if (!cancelled) setRestoring(false)
      }
    })()
    return () => {
      cancelled = true
    }
    // 仅首次挂载恢复
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 创建/确认后回到顶部，避免移动端停在长页中部
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [trip?.trip_id, trip?.current_version])

  const pendingDrafts = drafts.filter((draft) => draft.status === 'pending')
  const selectedDraft =
    drafts.find((draft) => draft.draft_id === selectedDraftId && draft.status === 'pending') ??
    pendingDrafts[0] ??
    null
  const hasDock = pendingDrafts.length > 0

  return (
    <div className={`app ${hasDock ? 'has-dock' : ''}`}>
      <MissionBar
        mode={mode}
        trip={trip}
        busy={busy}
        hasTrace={trace !== null}
        theme={theme}
        hasDrafts={hasDock}
        onToggleTheme={toggleTheme}
        onOpenHistory={() => setSheet('history')}
        onOpenSignal={() => setSheet('signal')}
        onReset={handleReset}
      />

      {notice && (
        <div className="notice-bar" role="status">
          <strong>Notice</strong>
          <span>{notice}</span>
          <button type="button" className="dismiss" onClick={() => setNotice(null)} aria-label="关闭提示">
            ×
          </button>
        </div>
      )}

      {error && (
        <section className="error-panel" role="alert">
          <h2>操作未完成</h2>
          <p>{error}</p>
          {errorValidation && <CheckList checks={errorValidation.checks} />}
        </section>
      )}

      {restoring ? (
        <div className="loading-screen" aria-live="polite">
          <span className="badge badge-neutral">RESTORE · 读取正式状态</span>
          <div className="skeleton wide" />
          <div className="skeleton skeleton tall" />
          <div className="skeleton wide" />
          <p className="form-hint">正在从 B 端恢复 trip / drafts / versions…</p>
        </div>
      ) : !trip ? (
        <SetupScreen
          values={form}
          error={formError}
          busy={busy}
          mode={mode}
          onChange={handleChange}
          onSubmit={handleCreate}
        />
      ) : (
        <>
          <BudgetRail trip={trip} />
          <div className="console">
            <RouteSpine
              trip={trip}
              candidatePlan={selectedDraft?.plan ?? null}
              candidateLabel={selectedDraft?.draft_id ?? null}
            />
            <aside className="rail-col">
              <AgentRail trace={trace} running={busy} />
            </aside>
          </div>
          {hasDock && (
            <DecisionDock
              trip={trip}
              drafts={drafts}
              busy={busy}
              selectedDraftId={selectedDraft?.draft_id ?? null}
              onSelect={setSelectedDraftId}
              onConfirm={handleConfirm}
            />
          )}
        </>
      )}

      {sheet === 'signal' && trip && (
        <SignalSheet
          trip={trip}
          busy={busy}
          onClose={() => setSheet(null)}
          onReportDelay={() => void reportEvent(buildDelayEvent, '列车晚点（东湖绿道段）', 'train_delay')}
          onReportClosure={() => void reportEvent(buildClosureEvent, '景区闭馆（黄鹤楼）', 'poi_closed')}
        />
      )}
      {sheet === 'history' && trip && (
        <HistoryDrawer versions={versions} currentVersion={trip.current_version} onClose={() => setSheet(null)} />
      )}

      <footer className="footer">
        <span>TravelGuard · Live Agent Console · {apiModeLabel(mode)}</span>
        <span>模拟数据 · 核验与版本以 B 端返回为准 · AgentArts 未接入前为本地演示轨迹</span>
      </footer>
    </div>
  )
}
