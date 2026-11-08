import type { FormEvent } from 'react'
import type { ApiMode } from '../services/client.ts'
import type { TransportMode } from '../services/recommendations.ts'
import { transportLabels } from '../services/guide.ts'
import { Icon } from './ui.tsx'

export interface TripFormValues {
  city: string
  originCity: string
  arrivalStation: string
  returnStation: string
  arrivalTime: string
  keywords: string
  otherCosts: string
  startDate: string
  endDate: string
  partySize: string
  budget: string
  walkingLimit: string
  allowedModes: TransportMode[]
  returnTime: string
  stayTogether: boolean
}

interface Props {
  values: TripFormValues
  error: string | null
  busy: boolean
  mode: ApiMode
  onChange: (patch: Partial<TripFormValues>) => void
  onSubmit: () => void
}

const RUNBOOK = [
  { title: '选目的地与日期', detail: '从抵达点安排真实地点与出行路线', tag: '任务简报' },
  { title: '对比三条路线', detail: '比较步行、费用与天气风险，未知保留提示', tag: '规则推荐' },
  { title: '核对后再确认', detail: '开放、预约与交通证据不足时仅保留候选', tag: '用户确认' },
]

export function SetupScreen({ values, error, busy, mode, onChange, onSubmit }: Props) {
  return (
    <div className="setup">
      <section className="setup-hero">
        <p className="eyebrow">Live Agent Console · 2026 华为 ICT 赛题 2</p>
        <h1 className="hero-title">
          为一次会被打断的旅行，
          <br />
          准备一个会<em>守住约束</em>的系统。
        </h1>
        <p className="hero-lede">
          多事件连锁影响、最小必要重规划、约束与证据核验。先给系统一份任务简报，它会算清预算与硬约束，
          根据地图与天气生成路线候选，核对通过后由你确认保存。
        </p>
        <div className="hero-meta">
          <span>多目的地 · 多日路线</span>
          {mode === 'mock' && <span>演示数据</span>}
          <span>地图路线 · 天气参考 · 自由选择</span>
        </div>

        <ol className="runbook">
          {RUNBOOK.map((step, index) => (
            <li key={step.title} className="runbook-step">
              <span className="runbook-num">0{index + 1}</span>
              <div>
                <strong>{step.title}</strong>
                <span>{step.detail}</span>
                <span className="tag">{step.tag}</span>
              </div>
            </li>
          ))}
        </ol>

        <p className="hero-note">地图和天气有来源与查询时间；开放、预约和费用未知时不会当作已核实。</p>
      </section>

      <form
        className="brief-card"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          onSubmit()
        }}
      >
        <div className="brief-head">
          <h2 className="brief-title">任务简报</h2>
          <span className={`badge badge-${mode === 'mock' ? 'sim' : 'neutral'}`}>{mode === 'mock' ? '演示数据' : '地图与天气'}</span>
        </div>

        <div className="form-grid">
          <label className="field"><span className="field-label">出发地城市</span><input value={values.originCity} onChange={event=>onChange({originCity:event.target.value})} data-testid="field-origin"/></label>
          <label className="field field-wide">
            <span className="field-label">
              目的地城市 <em>实际游览城市</em>
            </span>
            <input
              value={values.city}
              onChange={(event) => onChange({ city: event.target.value })}
              autoComplete="off"
              data-testid="field-city"
            />
          </label>
          <label className="field"><span className="field-label">目的地抵达点 <em>车站或住处</em></span><input value={values.arrivalStation} onChange={event=>onChange({arrivalStation:event.target.value})} data-testid="field-arrival-station"/></label>
          <label className="field"><span className="field-label">返程车站 <em>目的地内</em></span><input value={values.returnStation} onChange={event=>onChange({returnStation:event.target.value})} data-testid="field-return-station"/></label>
          <label className="field"><span className="field-label">抵达后出发游览时间</span><input type="time" value={values.arrivalTime} onChange={event=>onChange({arrivalTime:event.target.value})}/></label>
          <label className="field"><span className="field-label">景点搜索与偏好</span><input value={values.keywords} onChange={event=>onChange({keywords:event.target.value})} data-testid="field-keywords"/></label>
          <label className="field field-wide"><span className="field-label">其他费用估算（整团元）<em>长途、食宿等；留空表示未知</em></span><input type="number" min="0" step="0.01" value={values.otherCosts} onChange={event=>onChange({otherCosts:event.target.value})}/></label>
          <label className="field">
            <span className="field-label">
              开始游览日期 <em>最多7日</em>
            </span>
            <input
              type="date"
              value={values.startDate}
              onChange={(event) => onChange({ startDate: event.target.value })}
            />
          </label>
          <label className="field">
            <span className="field-label">
              返回日期 <em>不早于出发</em>
            </span>
            <input
              type="date"
              value={values.endDate}
              onChange={(event) => onChange({ endDate: event.target.value })}
            />
          </label>
          <label className="field">
            <span className="field-label">
              同行人数 <em>1–10</em>
            </span>
            <input
              type="number"
              min="1"
              max="10"
              value={values.partySize}
              onChange={(event) => onChange({ partySize: event.target.value })}
            />
          </label>
          <label className="field">
            <span className="field-label">
              预算（元） <em>总预算</em>
            </span>
            <input
              type="number"
              min="0"
              step="50"
              value={values.budget}
              onChange={(event) => onChange({ budget: event.target.value })}
            />
          </label>
          <fieldset className="field field-wide transport-options"><legend>愿意使用哪些出行方式</legend>
            {(Object.entries(transportLabels) as Array<[TransportMode, string]>).map(([key, label]) => <label key={key} className="checkbox-field"><input type="checkbox" data-testid={`mode-${key}`} checked={values.allowedModes.includes(key)} onChange={event => onChange({ allowedModes: event.target.checked ? [...values.allowedModes, key] : values.allowedModes.filter(mode => mode !== key) })} />{label}</label>)}
          </fieldset>
          <label className="field"><span className="field-label">每次最多愿意走多久</span>
            <select value={values.walkingLimit} onChange={event => onChange({walkingLimit: event.target.value})} data-testid="walking-preference">
              <option value="10">10分钟以内</option><option value="20">20分钟以内</option><option value="30">30分钟以内</option><option value="">不限制</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">
              到达返程车站的截止时间 <em>返回日当天</em>
            </span>
            <input
              type="time"
              value={values.returnTime}
              onChange={(event) => onChange({ returnTime: event.target.value })}
            />
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={values.stayTogether}
              onChange={(event) => onChange({ stayTogether: event.target.checked })}
            />
            希望全程同行（偏好）
          </label>
        </div>

        {error && <p className="form-error">{error}</p>}

        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy} data-testid="create-trip">
            {busy ? '正在查询地图与天气…' : mode === 'mock' ? '生成演示行程' : '生成路线推荐'}
            <Icon name="arrow" size={15} />
          </button>
          {busy && <span className="spinner" aria-hidden="true" />}
        </div>

        {mode === 'mock' && <p className="mode-note">演示数据，不代表真实开放、预约或付款。</p>}
      </form>
    </div>
  )
}
