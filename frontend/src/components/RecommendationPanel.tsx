import { useState } from 'react'
import type { PlanningBundle, Recommendation, Evidence } from '../services/recommendations.ts'
import { formatCny } from '../services/money.ts'
import { formatDateTime, formatTime } from '../services/time.ts'
import { Badge, CheckList } from './ui.tsx'

function Source({ evidence }: { evidence: Evidence }) {
  const type=evidence.data_type==='real'?'真实来源':evidence.data_type==='simulated'?'模拟数据':'来源待核实'
  const state=evidence.verification_status==='verified'?'已核实':evidence.verification_status==='source_reported'?'来源报告':'未核实'
  return <small className="activity-note">{evidence.source} · {type} · 查询 {formatDateTime(evidence.fetched_at)} · {state}
    {evidence.source==='qweather' && <span> · <a href="https://developer.qweather.com/attribution.html" target="_blank" rel="noreferrer">和风天气</a></span>}</small>
}
function ruleMessage(code: string, message: string) {
  return code==='missing_rules_source' ? '地点开放、预约与票价资料尚未核实。' : message
}

const modes: Record<string,string> = { walking: '步行', transit: '公交', driving: '驾车' }
export function RecommendationPanel({ bundle, busy, formal, onSave }: {
  bundle: PlanningBundle; busy: boolean; formal: boolean; onSave: (candidate: Recommendation) => void
}) {
  const [selected, setSelected] = useState(0)
  const candidate = bundle.candidates[selected] ?? bundle.candidates[0]
  return <section className="spine recommendation-panel" data-testid="recommendations">
    <div className="section-head"><div><p className="section-kicker">Route Options</p>
      <h2 className="section-title">路线推荐与备选 <Badge tone="neutral">规则推荐</Badge></h2></div></div>
    <p className="form-hint">{bundle.input.origin_city} → {bundle.input.city} · {bundle.input.start_date} 至 {bundle.input.end_date}。从 {bundle.input.arrival_station} 抵达后开始游览；到达 {bundle.input.return_station} 截止 {bundle.input.return_time}。AgentArts 尚未接入。</p>
    <details><summary>地点与抵达点搜索结果 · {bundle.places.length} 个</summary>
      <p className="activity-note">抵达点及返程点采用输入名称的首个搜索结果，请核对：{bundle.arrival_candidates[0]?.name ?? '未知'} / {bundle.return_candidates[0]?.name ?? '未知'}。有歧义时请填写更准确名称后重新查询。</p>
      <ul>{bundle.places.map(place => <li key={place.poi_id}>{place.name} · {place.address ?? '地址未知'}</li>)}</ul>
      {bundle.searches.map((s,i) => <p key={i}>{s.status} · {s.code} · {s.message}<br/><Source evidence={s.evidence}/></p>)}
    </details>
    {!candidate ? <p role="alert">当前未取得可用地点，不能生成路线。请查看上方真实请求结果，调整城市或关键词后重试。</p> : <>
      <div className="recommendation-choices">{bundle.candidates.map((c,i) => <button type="button" key={c.profile} className={`draft-card ${selected===i?'selected':''}`} onClick={()=>setSelected(i)} data-testid="recommendation-card">
        <strong>{c.recommended ? '主推 · ' : '备选 · '}{c.label.replace('综合主推','综合方案')}</strong>
        <Badge tone={c.validation.overall==='PASS'?'pass':c.validation.overall==='FAIL'?'fail':'unknown'}>{c.validation.overall}</Badge>
        <p>{c.reason}</p><p>{c.cost_complete?'预计费用':'已知费用小计'} {formatCny(c.known_cost_cny)} · 预算余量 {formatCny(c.remaining_cny)}</p>
        <p>步行 {c.walking_minutes ?? '未知'} 分 · 交通 {c.transport_minutes ?? '未知'} 分 · 排序分 {c.score}（越低越优）</p>
      </button>)}</div>
      <p className="activity-note">{candidate.ranking_note}。费用按 {bundle.input.party_size} 人计算；其他费用输入为整团估算。</p>
      <div data-testid="recommendation-itinerary">{[...new Set(candidate.days.map(d=>d.date))].map(day => <article className="day" key={day}>
        <div className="day-head"><span className="day-label">{day}</span><span className="day-rule"/></div>
        <ol className="day-list">{candidate.days.filter(d=>d.date===day).map(detail => {
          const activity=candidate.plan.activities.find(a=>a.id===detail.activity_id)!
          const leg=candidate.legs.find(l=>l.activity_id===detail.activity_id)
          return <li className="activity" key={activity.id}><div className="activity-time">{formatTime(activity.start_at)}<br/>{formatTime(activity.end_at)}</div>
            <div className="activity-body"><strong className="activity-name">{detail.place?.name ?? activity.poi_id}</strong>
              <p>{detail.place?.address ?? '地址未核实'} · {detail.indoor_inferred===true?'室内（分类推断）':'室内外属性未核实'}</p>
              {detail.place?.location && <p><a target="_blank" rel="noreferrer" href={`https://uri.amap.com/marker?position=${detail.place.location.longitude},${detail.place.location.latitude}&name=${encodeURIComponent(detail.place.name)}&coordinate=gaode&callnative=0`}>在高德地图查看 · GCJ-02 {detail.place.location.longitude}, {detail.place.location.latitude}</a></p>}
              <p>{leg?.from_name} → {leg?.to_name} · {leg?.selected ? `${modes[leg.selected.mode]} ${leg.selected.duration_minutes} 分 / ${leg.selected.distance_meters} 米 / 步行 ${leg.selected.walking_minutes ?? '未知'} 分 / ${leg.selected.cost_cny===null?'费用未知':formatCny(leg.selected.cost_cny)}`:'交通耗时、步行及费用未知'}</p>
              {leg?.selected && <Source evidence={leg.selected.evidence}/>}
              <p>开放：{activity.opening_status==='confirmed_open'?'有规则依据':activity.opening_status==='confirmed_closed'?'关闭':'未知'} · 预约：{activity.booking_required?'需要或待核实':'规则声明不需要'}</p>
              <p>{ruleMessage(detail.rules.code,detail.rules.message)}</p><Source evidence={detail.rules.evidence}/>
              <p data-testid="weather-result">天气：{detail.weather?.data ? `${detail.weather.data.conditions.join('/')} ${detail.weather.data.temperature_min_c}–${detail.weather.data.temperature_max_c}°C · 户外风险 ${detail.weather.data.risk_check}`:`UNKNOWN · ${detail.weather?.code ?? '坐标未知'} · ${detail.weather?.message ?? '未取得预报'}`}</p>
              {detail.weather && <Source evidence={detail.weather.evidence}/>}
              {detail.weather?.data && <p className="activity-note">{detail.weather.data.note}</p>}
            </div></li>
        })}</ol>
      </article>)}</div>
      <p>到达返程车站：{candidate.plan.arrival_at_return_station ? formatDateTime(candidate.plan.arrival_at_return_station) : 'UNKNOWN，末段路线未取得'}。</p>
      <details><summary>全部路段、交通方式与失败证据</summary>{candidate.legs.map((l,i)=><div key={i}><strong>{l.from_name} → {l.to_name}</strong>{l.options?.results.map(r=><p key={r.mode}>{modes[r.mode]} · {r.status} · {r.code} · {r.message}{r.data?.map((option,j)=><span key={j}> / {Math.ceil(option.duration_seconds/60)} 分、{option.distance_meters} 米、步行 {option.walking_seconds===null?'未知':Math.ceil(option.walking_seconds/60)} 分、{option.cost_cny===null?'费用未知':formatCny(option.cost_cny)}</span>)}<br/><Source evidence={r.evidence}/></p>) ?? <p>缺少坐标，未发起路线查询</p>}</div>)}</details>
      <details><summary>核验与待核实事项</summary><CheckList checks={candidate.validation.checks}/><ul>{candidate.unverified.map((note,i)=><li key={i}>{note}</li>)}</ul></details>
      {!formal && <div className="form-actions"><button type="button" className="btn btn-primary" data-testid="save-recommendation" disabled={busy || candidate.validation.overall!=='PASS'} onClick={()=>onSave(candidate)}>选择此方案并保存正式 V1</button>
        {candidate.validation.overall!=='PASS' && <span className="form-hint">存在未知或冲突，当前仅供对比，不能确认正式版本。</span>}</div>}
    </>}
  </section>
}
