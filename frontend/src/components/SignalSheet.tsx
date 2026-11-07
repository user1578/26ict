import { useEffect } from 'react'
import type { TripView } from '../types.ts'
import { POI, poiName } from '../services/dataset.ts'
import { formatDateTime } from '../services/time.ts'
import { Badge, Icon } from './ui.tsx'

interface Props {
  trip: TripView
  busy: boolean
  onClose: () => void
  onReportDelay: () => void
  onReportClosure: () => void
}

export function SignalSheet({ trip, busy, onClose, onReportDelay, onReportClosure }: Props) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const plan = trip.current_plan.plan
  const delayTarget =
    plan.activities.find((activity) => activity.poi_id === POI.eastLakeGreenway) ?? plan.activities[1]
  const closureTarget = plan.activities.find((activity) => activity.poi_id === POI.yellowCraneTower)
  const hasDelay = trip.events.some((event) => event.active && event.kind === 'train_delay')
  const hasClosure = trip.events.some((event) => event.active && event.kind === 'poi_closed')

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="上报异常"
        onClick={(event) => event.stopPropagation()}
        data-testid="signal-sheet"
      >
        <header className="sheet-head">
          <div>
            <h2 className="sheet-title">上报异常</h2>
            <p className="sheet-sub">
              先 GET 最新 trip 拿 event_revision，再 PUT 事件（乐观锁）；随后由 B 核验并生成候选。
            </p>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭" data-testid="close-signal">
            <Icon name="close" />
          </button>
        </header>

        <div className="sheet-body">
          <section className="scenario">
            <div className="scenario-head">
              <span className="scenario-title">列车晚点 · {delayTarget ? poiName(delayTarget.poi_id) : '—'}</span>
              <Badge tone="warn">train_delay</Badge>
              <Badge tone="sim">simulation</Badge>
            </div>
            <p className="scenario-desc">
              模拟上报：受影响段晚点 45 分钟；候选会先满足「最早可开始时间」，只调整受影响段与后续活动。
            </p>
            <p className="scenario-impact">
              影响预览：{delayTarget ? `${delayTarget.id} · ${formatDateTime(delayTarget.start_at)} 起顺延 45 分钟` : '当前没有可调整的活动'}
            </p>
            <div className="scenario-actions">
              <button
                type="button"
                className="btn btn-signal"
                disabled={busy || hasDelay || !delayTarget}
                onClick={onReportDelay}
                data-testid="signal-delay"
              >
                {hasDelay ? '晚点已上报' : '上报列车晚点 +45 分钟'}
              </button>
            </div>
          </section>

          <section className="scenario">
            <div className="scenario-head">
              <span className="scenario-title">景区闭馆 · {poiName(POI.yellowCraneTower)}</span>
              <Badge tone="warn">poi_closed</Badge>
              <Badge tone="sim">simulation</Badge>
            </div>
            <p className="scenario-desc">
              模拟上报：最后一天 08:00 起关闭；候选会替换或移除受影响活动，并保留已支付费用事实与锁定活动。
            </p>
            <p className="scenario-impact">
              影响预览：
              {closureTarget
                ? `${closureTarget.id} · ${formatDateTime(closureTarget.start_at)} 的参观需要替换或删除`
                : '当前行程没有黄鹤楼活动'}
            </p>
            <div className="scenario-actions">
              <button
                type="button"
                className="btn btn-signal"
                disabled={busy || hasClosure || !closureTarget}
                onClick={onReportClosure}
                data-testid="signal-closure"
              >
                {hasClosure ? '闭馆已上报' : '上报景区闭馆'}
              </button>
            </div>
          </section>

          <p className="sheet-note">
            B 暂不支持天气事件与改签/取消预约；天气只作为只读风险参考。所有事件与候选均为模拟数据，
            最终以 B 端返回的 PASS/FAIL/UNKNOWN 为准。
          </p>
        </div>
      </div>
    </div>
  )
}
