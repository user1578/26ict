import type { Activity } from '../types.ts'
import { SourceBadge, VerificationBadge } from './Badges.tsx'

const timeOf = (iso: string) => iso.slice(11, 16)

const bookingText = (activity: Activity) => {
  switch (activity.booking_status) {
    case 'confirmed':
      return activity.booking_source_type === 'simulation' ? '预约：模拟已确认' : '预约：已确认'
    case 'pending':
      return '预约：待确认'
    case 'none':
      return '预约：不需要'
    default:
      return '预约：未知'
  }
}

const openingText = (activity: Activity) => {
  switch (activity.opening_status) {
    case 'confirmed_open':
      return '开放：已核实'
    case 'confirmed_closed':
      return '开放：已关闭'
    default:
      return '开放：未知'
  }
}

export function Timeline({ activities }: { activities: Activity[] }) {
  const dates = Array.from(new Set(activities.map((activity) => activity.start_at.slice(0, 10)))).sort()

  return (
    <section className="card">
      <h2>行程时间轴</h2>
      {dates.map((date, index) => (
        <div key={date} className="day-block">
          <h3>
            第 {index + 1} 天 · {date}
          </h3>
          <ol className="timeline">
            {activities
              .filter((activity) => activity.start_at.slice(0, 10) === date)
              .map((activity) => (
                <li key={activity.activity_id} className="timeline-item">
                  <div className="timeline-time">
                    {timeOf(activity.start_at)} – {timeOf(activity.end_at)}
                  </div>
                  <div className="timeline-body">
                    <div className="timeline-head">
                      <strong>{activity.name}</strong>
                      <SourceBadge value={activity.source_type} />
                      <VerificationBadge value={activity.rule_verification} />
                    </div>
                    <p className="meta">
                      {activity.poi_id} · {openingText(activity)} · {bookingText(activity)} · 预计 ¥
                      {activity.est_cost_cny}
                    </p>
                    {activity.unknown_fields.length > 0 && (
                      <p className="unknown">未核实字段：{activity.unknown_fields.join('、')}</p>
                    )}
                  </div>
                </li>
              ))}
          </ol>
        </div>
      ))}
    </section>
  )
}
