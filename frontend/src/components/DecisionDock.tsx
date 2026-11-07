import type { DraftView, TripView } from '../types.ts'
import { poiName } from '../services/dataset.ts'
import { formatCny } from '../services/money.ts'
import { summarizePlanChange } from '../services/planner.ts'
import { formatTime } from '../services/time.ts'
import { checkLabel } from '../lib/labels.ts'
import { Badge, DraftStateBadge, Icon } from './ui.tsx'

interface Props {
  trip: TripView
  drafts: DraftView[]
  busy: boolean
  selectedDraftId: string | null
  onSelect: (draftId: string) => void
  onConfirm: (draft: DraftView) => void
}

const statusOrder: Record<DraftView['status'], number> = { pending: 0, committed: 1, stale: 2 }

export function DecisionDock({ trip, drafts, busy, selectedDraftId, onSelect, onConfirm }: Props) {
  const sorted = [...drafts].sort((left, right) => statusOrder[left.status] - statusOrder[right.status])
  const pendingCount = drafts.filter((draft) => draft.status === 'pending').length

  return (
    <section className="dock" aria-label="决策坞" data-testid="decision-dock">
      <div className="dock-head">
        <span className="dock-title">Decision Dock · 决策坞</span>
        <Badge tone={pendingCount > 0 ? 'warn' : 'neutral'}>{pendingCount} 个待确认</Badge>
        <span className="dock-sub">
          一个候选 = 一份完整方案 · 确认一个后其余自动失效 · 核验以 B 端为准
        </span>
      </div>

      {drafts.length === 0 ? (
        <div className="dock-empty">
          <Icon name="signal" size={14} />
          <span>
            <strong>暂无待决候选</strong> · 上报异常后，系统会生成候选并在这里等待你确认
          </span>
        </div>
      ) : (
        <div className="dock-cards">
          {sorted.map((draft) => {
            const diff = summarizePlanChange(trip.current_plan.plan, draft.plan)
            const problems = draft.validation.checks.filter(
              (check) => check.status === 'FAIL' || check.status === 'UNKNOWN',
            )
            const confirmable = draft.status === 'pending' && draft.validation.overall === 'PASS'
            const selected = draft.draft_id === selectedDraftId
            const hint =
              draft.status === 'stale'
                ? '已失效：请按最新状态重新生成'
                : draft.status === 'committed'
                  ? `已形成正式版本 V${draft.committed_version ?? '?'}`
                  : draft.validation.overall !== 'PASS'
                    ? 'B 端核验未通过，不能确认'
                    : busy
                      ? '正在提交…'
                      : ''
            return (
              <article
                key={draft.draft_id}
                className={`draft-card ${selected ? 'selected' : ''} ${
                  draft.status !== 'pending' ? 'is-inactive' : ''
                }`}
                data-testid="draft-card"
              >
                <div className="draft-head">
                  <span className="draft-id">{draft.draft_id}</span>
                  <DraftStateBadge status={draft.status} />
                  <Badge tone={draft.validation.overall === 'PASS' ? 'pass' : draft.validation.overall === 'FAIL' ? 'fail' : 'unknown'}>
                    核验 {draft.validation.overall}
                  </Badge>
                </div>

                <div className="draft-row">
                  <span className="draft-figure">
                    改动 <b>{diff.changed.length}</b>
                  </span>
                  <span className="draft-figure">
                    新增 <b>{diff.added.length}</b>
                  </span>
                  <span className="draft-figure">
                    移除 <b>{diff.removed.length}</b>
                  </span>
                  <span className="draft-figure">
                    预算变化 <b>{formatCny(diff.budgetDeltaCny)}</b>
                  </span>
                  <span className="draft-figure">
                    基于 <b>V{draft.base_version}</b>
                  </span>
                </div>

                <ul className="draft-diff">
                  {diff.changed.map((id) => (
                    <li key={`c-${id}`} className="diff-line change">
                      <span className="diff-mark">~</span>
                      <span>
                        {id} · {poiName(draft.plan.activities.find((activity) => activity.id === id)?.poi_id ?? '')} ·
                        时间/属性调整 → {formatTime(draft.plan.activities.find((activity) => activity.id === id)?.start_at ?? null)}
                      </span>
                    </li>
                  ))}
                  {diff.added.map((id) => (
                    <li key={`a-${id}`} className="diff-line add">
                      <span className="diff-mark">+</span>
                      <span>
                        {id} · {poiName(draft.plan.activities.find((activity) => activity.id === id)?.poi_id ?? '')} ·
                        新增候选活动
                      </span>
                    </li>
                  ))}
                  {diff.removed.map((id) => (
                    <li key={`r-${id}`} className="diff-line remove">
                      <span className="diff-mark">−</span>
                      <span>
                        {id} ·{' '}
                        {poiName(
                          trip.current_plan.plan.activities.find((activity) => activity.id === id)?.poi_id ?? '',
                        )}{' '}
                        · 从候选移除
                      </span>
                    </li>
                  ))}
                </ul>

                {problems.length > 0 ? (
                  <ul className="draft-risks">
                    {problems.slice(0, 3).map((check) => (
                      <li
                        key={check.name}
                        className={`risk-item ${
                          check.status === 'FAIL' ? 'fail' : check.status === 'UNKNOWN' ? 'unknown' : ''
                        }`}
                      >
                        <b>{check.status === 'FAIL' ? 'FAIL' : '未知'}</b>
                        {checkLabel(check.name)}：{check.detail}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="draft-hint">没有 FAIL / UNKNOWN；仍需你阅读差异后确认。</p>
                )}

                <details className="draft-details">
                  <summary>查看完整候选方案（{draft.plan.activities.length} 项活动）</summary>
                  <ul className="draft-plan">
                    {draft.plan.activities.map((activity) => (
                      <li key={activity.id}>
                        <span>
                          {formatTime(activity.start_at)}–{formatTime(activity.end_at)}
                        </span>
                        <span>{poiName(activity.poi_id)}</span>
                        <span style={{ color: 'var(--text-3)' }}>{activity.id}</span>
                      </li>
                    ))}
                  </ul>
                </details>

                <div className="draft-actions">
                  <button
                    type="button"
                    className={`btn btn-small ${selected ? 'btn-primary' : ''}`}
                    onClick={() => onSelect(draft.draft_id)}
                    disabled={busy}
                  >
                    <Icon name="route" size={13} />
                    {selected ? '正在预览差异' : '在脊柱上预览'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-small btn-primary"
                    disabled={!confirmable || busy}
                    onClick={() => onConfirm(draft)}
                    data-testid="confirm-draft"
                    title={hint || '确认后生成新正式版本'}
                  >
                    {draft.status === 'committed' ? '已确认' : '确认此候选'}
                  </button>
                  {hint && <span className="draft-hint">{hint}</span>}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
