import { useEffect, useState } from 'react'
import type { TraceRun, TraceStatus } from '../services/agentTrace.ts'
import { Icon } from './ui.tsx'

const actorLabels = {
  controller: '控制器',
  planner: 'WF_Plan',
  replanner: 'WF_Replan',
  budget: '预算',
  verify: '核验',
  system: 'B/C 接口',
} as const

const statusLabels: Record<TraceStatus, string> = {
  ok: '完成',
  run: '运行中',
  unknown: '未知',
  fail: '失败',
}

export function AgentRail({ trace, running }: { trace: TraceRun | null; running: boolean }) {
  const title = trace ? `智能体工作台 · ${trace.steps.length} 步` : '智能体工作台 · 待命'
  const [collapsed, setCollapsed] = useState(() => window.matchMedia('(max-width: 1120px)').matches)

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1120px)')
    const onChange = () => setCollapsed(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  return (
    <details className="agent-rail" open={!collapsed} data-testid="agent-rail">
      <summary>{title}</summary>
      <div className="rail-head">
        <span className="rail-title">
          <Icon name="agent" size={15} /> 智能体工作台
        </span>
        <span className="rail-status">{running ? '运行中…' : trace ? trace.intent : '待命'}</span>
      </div>

      {trace ? (
        <ol className="trace-list">
          {trace.steps.map((step) => (
            <li className="trace-step" key={step.id} data-testid="trace-step">
              <span
                className={`trace-dot ${
                  running && step.status === 'ok' ? 'run' : step.status === 'ok' ? 'ok' : step.status
                }`}
              />
              <div>
                <span className="trace-kind">
                  {step.kind} · {actorLabels[step.actor]}
                </span>
                <div className="trace-node">{step.node}</div>
                <p className="trace-summary">{step.summary}</p>
                <div className="trace-meta">
                  <span>{step.tool ? `tool ${step.tool}` : step.actor}</span>
                  {step.durationMs !== undefined && <span>{step.durationMs} ms</span>}
                  <span>状态 {statusLabels[step.status]}</span>
                </div>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <div className="rail-empty">
          <strong>等待第一次运行</strong>
          AgentArts 尚未接入。规则推荐的地图、天气和核验结果可在路线对比中查看。
        </div>
      )}

      <p className="rail-note">
        {trace ? '模拟演示轨迹；不代表真实 AgentArts 调用或耗时。' : '未调用 AgentArts，不生成执行轨迹或耗时。'}
      </p>
    </details>
  )
}
