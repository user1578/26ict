import { useCallback, useEffect, useMemo, useState } from 'react'
import { RecommendationPanel } from './components/RecommendationPanel.tsx'
import { recommend, readPlanning, savePlanning, type PlanningBundle, type PlanningInput, type Recommendation } from './services/recommendations.ts'
import { registerPlaces } from './services/dataset.ts'
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
  city: '杭州',
  originCity: '上海',
  arrivalStation: '杭州站',
  returnStation: '杭州站',
  arrivalTime: '09:00',
  keywords: '风景名胜',
  otherCosts: '',
  startDate: new Date(Date.now()+86400000).toLocaleDateString('sv-SE', {timeZone:'Asia/Shanghai'}),
  endDate: new Date(Date.now()+2*86400000).toLocaleDateString('sv-SE', {timeZone:'Asia/Shanghai'}),
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
  const [planning, setPlanning] = useState<PlanningBundle | null>(null)
  const [trip, setTrip] = useState<TripView | null>(null)
  const [drafts, setDrafts] = useState<DraftView[]>([])
  const [versions, setVersions] = useState<VersionView[]>([])
  const [trace, setTrace] = useState<TraceRun | null>(null)
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null)
  const [sheet, setSheet] = useState<Sheet>(null)
  const [restoring, setRestoring] = useState(false)

  const handleChange = (patch: Partial<TripFormValues>) => {
    setForm((previous) => ({ ...previous, ...(patch.city ? { arrivalStation: `${patch.city}站`, returnStation: `${patch.city}站` } : {}), ...patch }))
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
      setFormError('每次步行时长必须是非负整数')
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
      if (mode === 'real') {
        if (!form.originCity.trim() || !form.arrivalStation.trim() || !form.returnStation.trim() || !form.keywords.trim()) {
          setFormError('请填写出发地、抵达点、返程车站和景点关键词')
          return
        }
        const query: PlanningInput = { origin_city:form.originCity.trim(),city:input.city,
          arrival_station:form.arrivalStation.trim(),return_station:form.returnStation.trim(),keywords:form.keywords.trim(),
          start_date:input.startDate,end_date:input.endDate,party_size:input.partySize,budget_cny:input.budgetCny,
          max_walking_minutes_per_leg:input.walkingLimit,arrival_time:form.arrivalTime,return_time:input.returnTime,
          stay_together:input.stayTogether,other_costs_cny:form.otherCosts.trim() || null }
        const bundle = await recommend(query)
        registerPlaces(bundle.places)
        setPlanning(bundle)
        setNotice(`已完成地图与天气查询，取得 ${bundle.candidates.length} 条规则候选；请选择方案核对后保存。`)
        return
      }
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

  const handleSaveRecommendation = async (candidate: Recommendation) => {
    if (!planning || busy || candidate.validation.overall !== 'PASS') return
    setBusy(true)
    setError(null)
    try {
      const created = await api.createTrip({ ...planning.trip_request, request_id:newId('create'), trip_id:newId('trip'), plan:candidate.plan })
      setTrip(created)
      setDrafts([])
      setVersions([created.current_plan])
      setTrace(null)
      savePlanning(created.trip_id, planning)
      rememberTrip(created)
      setNotice('已按你的选择保存正式 V1；AgentArts 尚未接入。')
    } catch (caught) { await handleError(caught,null) }
    finally { setBusy(false) }
  }

  const updateRecommendations = async (fresh: TripView, context: PlanningBundle) => {
    const bundle = await recommend(context.input, fresh.trip_id)
    registerPlaces(bundle.places)
    const eligible = bundle.candidates.filter(c=>c.validation.overall==='PASS')
    const requests = buildDraftRequests(fresh, eligible.map(c=>({key:c.profile,label:c.label,description:c.reason,plan:c.plan})))
    for (const request of requests) await api.createDraft(fresh.trip_id,request)
    setPlanning(bundle)
    savePlanning(fresh.trip_id,bundle)
    await refresh(fresh.trip_id)
    setTrace(null)
    return { bundle, count:requests.length }
  }

  const handleRequery = async () => {
    if (!trip || !planning || busy) return
    setBusy(true)
    setError(null)
    try {
      const fresh=await api.getTrip(trip.trip_id)
      const result=await updateRecommendations(fresh,planning)
      setNotice(`已重新查询调整候选；${result.count} 份通过必要核验并保存为草案，其余仅供核对。`)
    } catch(caught) { await handleError(caught,trip.trip_id) }
    finally { setBusy(false) }
  }

  const reportEvent = async (
    build: (fresh: TripView) => ReturnType<typeof buildDelayEvent>,
    label: string,
    kind: EventKind,
  ) => {
    if (!trip || busy) return
    if (mode === 'real' && !planning) { setSheet(null); setError('本机缺少此旅行的规划上下文，请在原浏览器恢复资料或重新创建旅行；不会改用模拟方案。'); return }
    setBusy(true)
    setError(null)
    setErrorValidation(null)
    setSheet(null)
    try {
      const fresh = await api.getTrip(trip.trip_id)
      const eventId = nextEventId(fresh)
      await api.putEvent(fresh.trip_id, eventId, build(fresh))
      const updated = await api.getTrip(fresh.trip_id)
      if (mode === 'real' && planning) {
        const result=await updateRecommendations(updated,planning)
        setNotice(`${label}：已保存用户上报，生成 ${result.bundle.candidates.length} 份调整候选；${result.count} 份可供正式核验。未核实异常会阻止确认。`)
        return
      }
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
    const extra = planning?.candidates.find(c=>JSON.stringify(c.plan)===JSON.stringify(draft.plan))
    if (mode === 'real' && (!planning || !extra || extra.validation.overall!=='PASS')) { setError('天气、费用或路线证据不足，不能确认'); return }
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
      setTrace(mode === 'mock' || !planning ? confirmTrace(draft.draft_id, version.version) : null)
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
    setPlanning(null)
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
        const cached=readPlanning(tripId)
        if (cached) { registerPlaces(cached.places); setPlanning(cached) }
        setTrip(restoredTrip)
        setDrafts(restoredDrafts)
        setVersions(restoredVersions.length > 0 ? restoredVersions : [restoredTrip.current_plan])
        setTrace(null)
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
        <>
        <SetupScreen
          values={form}
          error={formError}
          busy={busy}
          mode={mode}
          onChange={handleChange}
          onSubmit={handleCreate}
        />
        {planning && <RecommendationPanel bundle={planning} busy={busy} formal={false} onSave={handleSaveRecommendation}/>}
        </>
      ) : (
        <>
          <BudgetRail trip={trip} />
          {planning && <><div className="form-actions"><button type="button" className="btn btn-ghost" disabled={busy} data-testid="refresh-recommendations" onClick={handleRequery}>重新查询调整候选</button></div><RecommendationPanel bundle={planning} busy={busy} formal onSave={handleSaveRecommendation}/></> }
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
              recommendationChecks={planning?.candidates ?? []}
              requireRecommendation={mode === 'real'}
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
          real={mode === 'real'}
          onClose={() => setSheet(null)}
          onReportDelay={() => void reportEvent(fresh=> mode === 'real' ? {...buildDelayEvent(fresh), source:'reported', verification_status:'unverified', evidence_ref:`user-report:${newId('delay')}`} : buildDelayEvent(fresh), '行程延误', 'train_delay')}
          onReportClosure={() => void reportEvent(fresh=> mode === 'real' ? {...buildClosureEvent(fresh), poi_id:fresh.current_plan.plan.activities.at(-1)!.poi_id, source:'reported', verification_status:'unverified', evidence_ref:`user-report:${newId('closure')}`} : buildClosureEvent(fresh), '地点关闭', 'poi_closed')}
        />
      )}
      {sheet === 'history' && trip && (
        <HistoryDrawer versions={versions} currentVersion={trip.current_version} onClose={() => setSheet(null)} />
      )}

      <footer className="footer">
        <span>TravelGuard · Live Agent Console · {apiModeLabel(mode)}</span>
        <span>{mode === 'mock' ? '模拟数据 · 自动化测试' : '地图与天气有来源标记 · 未知不当作通过 · AgentArts 尚未接入'}</span>
      </footer>
    </div>
  )
}
