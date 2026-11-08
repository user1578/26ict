import { useEffect } from 'react'
import type { TripView } from '../types.ts'
import { POI, poiName } from '../services/dataset.ts'
import { formatDateTime } from '../services/time.ts'
import { Badge, Icon } from './ui.tsx'

interface Props {
  trip: TripView
  real?: boolean
  busy: boolean
  onClose: () => void
  onReportDelay: () => void
  onReportClosure: () => void
}

export function SignalSheet({ trip, busy, onClose, onReportDelay, onReportClosure, real = false }: Props) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const plan = trip.current_plan.plan
  const delayTarget =
    plan.activities.find((activity) => activity.poi_id === POI.eastLakeGreenway) ?? plan.activities[1] ?? plan.activities[0]
  const closureTarget = real ? plan.activities.at(-1) : plan.activities.find((activity) => activity.poi_id === POI.yellowCraneTower)
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
              上报你遇到的行程延误或地点关闭，再比较调整方案。
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
              <Badge tone={real?'unknown':'sim'}>{real?'用户上报 · 未核实':'模拟'}</Badge>
            </div>
            <p className="scenario-desc">
              {real?'用户上报：受影响活动延误45分钟；尚未取得外部核实证据，确认将被阻止。':'模拟上报：受影响段晚点45分钟，仅调整需要变动的后续活动。'}
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
              <span className="scenario-title">景区闭馆 · {closureTarget ? poiName(closureTarget.poi_id) : '未选择地点'}</span>
              <Badge tone="warn">poi_closed</Badge>
              <Badge tone={real?'unknown':'sim'}>{real?'用户上报 · 未核实':'模拟'}</Badge>
            </div>
            <p className="scenario-desc">
              {real?'用户上报：最后一项活动地点从末日08:00起关闭；来源未核实，候选会保留确认限制。':'模拟上报：最后一天08:00起关闭，生成替换或删减候选。'}
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
            {real?'上报不会执行预约、付款或改签。异常未经核实不能确认正式新版本。':'当前为模拟测试事件，非真实核实事实。'}
          </p>
        </div>
      </div>
    </div>
  )
}
