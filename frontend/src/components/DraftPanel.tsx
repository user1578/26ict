import type { Draft, DraftOption } from '../types.ts'
import { FeasibilityBadge } from './Badges.tsx'

const statusText: Record<Draft['status'], string> = {
  awaiting_confirmation: '待确认',
  superseded: '已失效',
  confirmed: '已确认',
}

interface Props {
  drafts: Draft[]
  onConfirm: (draftId: string, option: DraftOption) => void
}

export function DraftPanel({ drafts, onConfirm }: Props) {
  if (drafts.length === 0) {
    return (
      <section className="card">
        <h2>调整候选</h2>
        <p className="hint">上报异常后，这里会显示重规划候选方案与约束提示。</p>
      </section>
    )
  }

  return (
    <section className="card">
      <h2>调整候选</h2>
      {[...drafts].reverse().map((draft) => (
        <article key={draft.draft_id} className={draft.status === 'superseded' ? 'draft draft-inactive' : 'draft'}>
          <header className="draft-head">
            <strong>{draft.draft_id}</strong>
            <span className="meta">
              基于 V{draft.base_version} · 事件 {draft.event_ids.join('、')}
            </span>
            <span className={`badge badge-draft-${draft.status}`}>{statusText[draft.status]}</span>
          </header>

          {draft.status === 'superseded' && (
            <p className="hint">
              已失效{draft.superseded_by ? `，由 ${draft.superseded_by} 取代` : ''}：旧草案不能提交为正式版本。
            </p>
          )}

          <div className="options">
            {draft.options.map((option) => (
              <div key={option.option_id} className="option">
                <h4>
                  {option.option_id} · {option.title}
                </h4>
                <div className="option-meta">
                  <FeasibilityBadge value={option.feasibility} />
                  <span className="meta">
                    费用变化 {option.cost_delta_cny >= 0 ? `+¥${option.cost_delta_cny}` : `-¥${Math.abs(option.cost_delta_cny)}`}
                  </span>
                </div>
                <p>{option.description}</p>
                <p className="meta">涉及活动：{option.changed_activity_ids.join('、')}</p>
                {option.warnings.length > 0 && (
                  <ul className="warn-list">
                    {option.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                )}
                {option.requires_external_actions.length > 0 && (
                  <p className="meta">需人工处理：{option.requires_external_actions.join('；')}</p>
                )}
                {option.unknown_fields.length > 0 && (
                  <p className="unknown">未核实：{option.unknown_fields.join('、')}</p>
                )}
                <button
                  type="button"
                  className="primary"
                  disabled={draft.status !== 'awaiting_confirmation' || option.feasibility === 'infeasible'}
                  onClick={() => onConfirm(draft.draft_id, option)}
                >
                  确认此方案
                </button>
              </div>
            ))}
          </div>
        </article>
      ))}
    </section>
  )
}
