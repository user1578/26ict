import type { Trip } from '../types.ts'
import { plannedTotalCny } from '../services/demoApi.ts'

export function BudgetPanel({ trip }: { trip: Trip }) {
  const total = plannedTotalCny(trip)
  const remaining = trip.budget_cny - total
  const ratio = trip.budget_cny > 0 ? remaining / trip.budget_cny : 0
  const status = remaining < 0 ? 'over' : ratio <= 0.05 ? 'tight' : 'ok'
  const statusText =
    status === 'over'
      ? `超出预算 ¥${Math.abs(remaining)}`
      : status === 'tight'
        ? `预算接近上限，剩余 ¥${remaining}`
        : `预算充足，剩余 ¥${remaining}`

  return (
    <section className="card">
      <h2>预算</h2>
      <p className={`budget-status budget-${status}`}>{statusText}</p>
      <dl className="kv">
        <div>
          <dt>预算</dt>
          <dd>¥{trip.budget_cny}</dd>
        </div>
        <div>
          <dt>保守预计总支出</dt>
          <dd>¥{total}</dd>
        </div>
        <div>
          <dt>可支配余量</dt>
          <dd>¥{remaining}</dd>
        </div>
      </dl>
      <ul className="cost-list">
        {trip.costs.map((item) => (
          <li key={item.id}>
            <span>{item.label}</span>
            <span>¥{item.amount_cny}</span>
          </li>
        ))}
        <li>
          <span>门票（按活动估算）</span>
          <span>¥{trip.activities.reduce((sum, activity) => sum + activity.est_cost_cny, 0)}</span>
        </li>
      </ul>
      <p className="hint">
        口径与后端 calculate-budget 的 conservative_total_cny 一致：已付 + 待付 − 已到账退款。
      </p>
    </section>
  )
}
