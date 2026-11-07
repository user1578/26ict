import type { FormEvent } from 'react'
import type { ApiMode } from '../services/client.ts'
import { apiModeLabel } from '../services/client.ts'
import { Icon } from './ui.tsx'

export interface TripFormValues {
  city: string
  startDate: string
  endDate: string
  partySize: string
  budget: string
  walkingLimit: string
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
  {
    title: '读取规则与证据',
    detail: 'B 工具 get_place_rules / GET trip state；未知一律 UNKNOWN',
    tag: 'B 工具',
  },
  {
    title: '核算路线与天气',
    detail: 'get_route_options / get_weather_risk；缺数据不补造',
    tag: 'B 工具',
  },
  {
    title: '校验预算与硬约束',
    detail: 'calculate_budget / validate_plan；模型不参与判定',
    tag: '确定性',
  },
  {
    title: '生成正式版本 V1',
    detail: 'AgentArts WF_Plan → C 提交；当前演示由前端模拟规划',
    tag: 'AgentArts',
  },
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
          再由 AgentArts 生成正式行程 V1——每一个数字都有来源，未知不会被伪装成通过。
        </p>
        <div className="hero-meta">
          <span>武汉两日 · 示例数据</span>
          <span>{apiModeLabel(mode)}</span>
          <span>AgentArts 未接入前为本地演示</span>
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

        <p className="hero-note">
          静态核验由 B 端程序完成；大模型只负责意图与候选生成。页面中的「模拟」标签表示该事实来自人工构造的
          演示数据，不构成现实开放、预约或付款凭证。
        </p>
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
          <span className="badge badge-sim">模拟数据</span>
        </div>

        <div className="form-grid">
          <label className="field field-wide">
            <span className="field-label">
              城市 <em>出发地与目的地</em>
            </span>
            <input
              value={values.city}
              onChange={(event) => onChange({ city: event.target.value })}
              autoComplete="off"
              data-testid="field-city"
            />
          </label>
          <label className="field">
            <span className="field-label">
              出发日期 <em>YYYY-MM-DD</em>
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
          <label className="field">
            <span className="field-label">
              单段步行上限 <em>分钟</em>
            </span>
            <input
              type="number"
              min="0"
              step="5"
              value={values.walkingLimit}
              onChange={(event) => onChange({ walkingLimit: event.target.value })}
            />
          </label>
          <label className="field">
            <span className="field-label">
              返程截止 <em>返回日当天</em>
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
            希望全程同行（仅偏好；B 端暂无多人同行校验）
          </label>
        </div>

        {error && <p className="form-error">{error}</p>}

        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={busy} data-testid="create-trip">
            {busy ? '正在生成 V1…' : '生成 V1 并启动智能体'}
            <Icon name="arrow" size={15} />
          </button>
          {busy && <span className="spinner" aria-hidden="true" />}
        </div>

        <p className="mode-note">
          {mode === 'mock' ? '本地模拟模式：不访问后端，核验由前端按 B 规则近似。' : '真实后端模式：通过 Vite 代理调用 B 端 FastAPI，密钥不进入浏览器。'}
          <a className="mode-link" href={mode === 'mock' ? '?mode=real' : '?mode=mock'}>
            {mode === 'mock' ? '切到真实后端' : '切到本地模拟'}
          </a>
        </p>
      </form>
    </div>
  )
}
