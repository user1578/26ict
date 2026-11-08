import { useState } from 'react'
import type { PlanningBundle, Recommendation, Place } from '../services/recommendations.ts'
import { mapLink, routeText, statusText } from '../services/guide.ts'
import { formatCny } from '../services/money.ts'
import { formatDateTime, formatTime } from '../services/time.ts'
import { Badge, CheckList } from './ui.tsx'
import { StayFoodPanel } from './StayFoodPanel.tsx'

export function RecommendationPanel({ bundle, busy, formal, onSave, onChooseStay }: {
  bundle: PlanningBundle; busy: boolean; formal: boolean
  onSave: (candidate: Recommendation) => void; onChooseStay: (place: Place) => void
}) {
  const [selected, setSelected] = useState(0)
  const candidate = bundle.candidates[selected] ?? bundle.candidates[0]
  const hasRecommendation = bundle.candidates.some(c => c.recommended)
  const isDemo = bundle.searches.some(s => s.evidence.data_type === 'simulated')
  const dates = [...new Set(candidate?.days.map(d => d.date) ?? [])]
  const bike = candidate?.legs.some(l => l.selected?.mode === 'bicycling')
  const driving = candidate?.legs.some(l => l.selected?.mode === 'driving')

  return <section className="spine recommendation-panel" data-testid="recommendations">
    <div className="section-head">
      <div><p className="section-kicker">Your Travel Guide</p><h2 className="section-title">你的旅行攻略</h2></div>
      {isDemo && <Badge tone="sim">演示数据</Badge>}
    </div>
    <p className="guide-overview">{bundle.input.origin_city} → {bundle.input.city} · {bundle.input.start_date} 至 {bundle.input.end_date} · {bundle.input.party_size} 人 · 总预算 {formatCny(bundle.input.budget_cny)}</p>
    <p className="activity-note">地点与路线：高德地图 · 天气：<a href="https://developer.qweather.com/attribution.html" target="_blank" rel="noreferrer">和风天气</a></p>
    {!candidate ? <p role="alert">{bundle.needs_refresh ? '此前保存的攻略需要更新，请点击“重新查询调整候选”。已保存的正式行程未改变。' : '暂未取得可用地点，请调整目的地或关键词后重试。'}</p> : <>
      {!!bundle.distinct_shortfall && <p className="activity-note">当前找到 {bundle.candidates.length} 条有实际区别的建议，未用重复行程凑足数量。</p>}
      {!hasRecommendation && <p className="guide-warning" role="status" data-testid="no-feasible-route">当前条件下尚未找到可推荐的完整路线。以下建议仍需调整，不能直接确认；预算、时间和步行限制均未放宽。</p>}
      <div className="recommendation-choices">{bundle.candidates.map((c, i) => <button type="button" key={c.profile}
        className={`draft-card ${selected === i ? 'selected' : ''}`} onClick={() => setSelected(i)} data-testid="recommendation-card">
        <strong>{c.recommended ? '推荐 · ' : hasRecommendation ? '备选 · ' : '建议 · '}{c.label}</strong>
        <Badge tone={c.feasibility === 'infeasible' ? 'fail' : c.validation.overall === 'PASS' ? 'pass' : 'unknown'}>{statusText(c)}</Badge>
        <p>{c.reason}</p>
        <p>步行 {c.walking_minutes === null ? '待核实' : `约 ${c.walking_minutes} 分钟`} · 交通 {c.transport_minutes === null ? '待核实' : `约 ${c.transport_minutes} 分钟`}</p>
        <p>{c.cost_complete ? '预计总支出' : '目前可估算支出'} {formatCny(c.known_cost_cny)}{!c.cost_complete && '（未含缺失费用）'}</p>
      </button>)}</div>
      <div className="guide-budget" data-testid="guide-budget">
        <span>已付支出 <strong>{formatCny(candidate.paid_cny)}</strong></span>
        <span>计划费用估算 <strong>{formatCny(candidate.estimated_cny)}</strong></span>
        {candidate.available_balance_cny !== null ? <span>按当前估算，预算预计剩余 <strong>{formatCny(candidate.available_balance_cny)}</strong></span> : <span className="guide-warning">费用未齐，暂不提供可用余额</span>}
      </div>
      {!candidate.cost_complete && <p className="activity-note">{candidate.missing_costs.join('；')}。以上不是最终总价，住宿与餐饮实价需另行核对。</p>}
      <div className="guide-warnings" data-testid="travel-warnings">
        {candidate.warnings.map((warning, i) => <p key={i} className="guide-warning">{warning}</p>)}
        {bike && <p className="guide-warning">骑行时间来自真实路径；共享单车是否有车、取还车和租金尚未确认。</p>}
        {driving && <p className="guide-warning">驾车时间不是出租车报价；取车接驳、油费及停车费尚未确认。</p>}
      </div>
      <div data-testid="recommendation-itinerary">{dates.map((day, dayIndex) => {
        const weather = candidate.days.find(d => d.date === day && d.kind !== 'lodging')?.weather
        return <article className="day" key={day}>
          <div className="day-head"><span className="day-label">第 {dayIndex + 1} 天</span><span className="day-date">{day}</span><span className="day-rule" /></div>
          <p className="daily-weather" data-testid="weather-result">天气：{weather?.data ? `${weather.data.conditions.join('/')} · ${Math.round(weather.data.temperature_min_c)}–${Math.round(weather.data.temperature_max_c)}°C` : '该日预报待核实'}{weather?.data?.risk_check === 'FAIL' && ' · 有户外活动风险，请查看提示'}</p>
          <ol className="day-list">{candidate.days.filter(d => d.date === day).map(detail => {
            const activity = candidate.plan.activities.find(a => a.id === detail.activity_id)!
            const leg = candidate.legs.find(l => l.activity_id === detail.activity_id)
            const duration = Math.round((Date.parse(activity.end_at) - Date.parse(activity.start_at)) / 60000)
            return <li className="activity" key={activity.id}>
              <div className="activity-time">{formatTime(activity.start_at)}<br />{detail.kind !== 'lodging' && formatTime(activity.end_at)}</div>
              <div className="activity-body">
                <strong className="activity-name">{detail.place?.name ?? '地点待核实'}</strong>
                <p>{detail.kind === 'lodging' ? `住宿 · 次日 ${formatTime(activity.end_at)} 出发（房态待核实）` : `游览约 ${duration} 分钟`}{detail.place?.district ? ` · ${detail.place.district}` : ''}</p>
                <p className="guide-transport">{routeText(leg?.selected)}</p>
                {activity.opening_status === 'confirmed_closed' ? <p className="guide-warning">地点已关闭，请更换安排。</p> : activity.opening_status === 'unknown' && <p className="activity-note">{detail.kind === 'lodging' ? '房态和入住条件待确认' : '开放及预约要求待核实'}</p>}
                {detail.place && <a href={mapLink(detail.place)} target="_blank" rel="noreferrer">查看地点</a>}
              </div>
            </li>
          })}</ol>
        </article>
      })}</div>
      <div className="return-summary">
        <strong>返程 · {bundle.input.return_station}</strong>
        <p>{routeText(candidate.legs.find(l => l.activity_id === null)?.selected)}</p>
        <p>到站截止：{bundle.input.end_date} {bundle.input.return_time}；{candidate.plan.arrival_at_return_station ? `预计到站 ${formatDateTime(candidate.plan.arrival_at_return_station)}` : '到站时间尚不能核实，请先调整末段交通。'}</p>
      </div>
      {candidate.days.some(d => d.place?.location && d.kind !== 'lodging') && <StayFoodPanel key={`${candidate.profile}:${JSON.stringify(candidate.plan)}`} bundle={bundle} candidate={candidate} busy={busy} onChooseStay={onChooseStay} />}
      <details className="guide-evidence" data-testid="guide-evidence"><summary>查看详细依据</summary>
        <p>抵达点：{bundle.arrival_candidates[0]?.name ?? '未知'}；返程点：{bundle.return_candidates[0]?.name ?? '未知'}。如与预期不符，请使用更准确的地点名称重新查询。</p>
        <p>{candidate.ranking_note} · 排序分 {candidate.score}</p>
        <CheckList checks={candidate.validation.checks} />
        <ul>{candidate.unverified.map((note, i) => <li key={i}>{note}</li>)}</ul>
        <h4>地点、天气和各段交通的来源与查询时间</h4>
        <pre>{JSON.stringify({ searches: bundle.searches, days: candidate.days, legs: candidate.legs }, null, 2)}</pre>
      </details>
      {!formal && <div className="form-actions">
        <button type="button" className="btn btn-primary" data-testid="save-recommendation" disabled={busy || candidate.validation.overall !== 'PASS'} onClick={() => onSave(candidate)}>选择并保存此行程</button>
        {candidate.validation.overall !== 'PASS' && <span className="form-hint">资料不全或仍有冲突，暂不能保存为正式行程。</span>}
      </div>}
    </>}
  </section>
}
