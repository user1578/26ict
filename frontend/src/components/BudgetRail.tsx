import type { TripView } from '../types.ts'
import { formatCny, toCents } from '../services/money.ts'
import { formatDateTime } from '../services/time.ts'
import { Icon } from './ui.tsx'

export function BudgetRail({ trip }: { trip: TripView }) {
  const budget = trip.current_plan.budget
  const paid = toCents(budget.paid_cny)
  const planned = toCents(budget.planned_cny)
  const received = toCents(budget.received_refunds_cny)
  const pending = toCents(budget.pending_refunds_cny)
  const budgetCents = toCents(budget.budget_cny)
  const base = Math.max(paid + planned, budgetCents, 1)
  const width = (value: number) => `${Math.max(0, Math.min(100, (value / base) * 100))}%`

  return (
    <section className="budget-rail" aria-label="预算与约束" data-testid="budget-rail">
      <div className="budget-main">
        <div className="budget-line">
          <span className="budget-total">{formatCny(budget.budget_cny)}</span>
          <span className="budget-total-meta">
            保守总支出 {formatCny(budget.conservative_total_cny)} · 余量{' '}
            <strong>{formatCny(budget.remaining_cny)}</strong>
          </span>
        </div>
        <div
          className="budget-bar"
          role="img"
          aria-label={`已付 ${formatCny(budget.paid_cny)}，待付 ${formatCny(
            budget.planned_cny,
          )}，已到账退款 ${formatCny(budget.received_refunds_cny)}，待到账退款 ${formatCny(
            budget.pending_refunds_cny,
          )}`}
        >
          <span className="budget-seg seg-paid" style={{ width: width(paid) }} />
          <span className="budget-seg seg-planned" style={{ width: width(planned) }} />
          <span className="budget-seg seg-received" style={{ width: width(received) }} />
          <span className="budget-seg seg-pending" style={{ width: width(pending) }} />
        </div>
        <dl className="budget-stats">
          <div className="stat">
            <dt>已付</dt>
            <dd>{formatCny(budget.paid_cny)}</dd>
          </div>
          <div className="stat">
            <dt>待付</dt>
            <dd>{formatCny(budget.planned_cny)}</dd>
          </div>
          <div className="stat">
            <dt>已到账退款</dt>
            <dd>{formatCny(budget.received_refunds_cny)}</dd>
          </div>
          <div className="stat">
            <dt>待到账（不抵扣）</dt>
            <dd>{formatCny(budget.pending_refunds_cny)}</dd>
          </div>
        </dl>
      </div>
      <div className="constraint-chips">
        <span className="chip">
          人数 <b>{trip.party_size ?? '未知'}</b>
        </span>
        <span className="chip">
          步行/段 ≤ <b>{trip.constraints.max_walking_minutes_per_leg ?? '—'} 分</b>
        </span>
        <span className="chip">
          <Icon name="clock" size={13} />
          <b>
            {trip.constraints.return_deadline
              ? formatDateTime(trip.constraints.return_deadline)
              : '未设返程'}
          </b>
        </span>
        <span className="chip">
          同行偏好 <b>{trip.preferences.stay_together === false ? '否' : '是'}</b>
        </span>
      </div>
    </section>
  )
}
