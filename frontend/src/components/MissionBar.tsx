import type { TripView } from '../types.ts'
import type { ApiMode } from '../services/client.ts'
import type { Theme } from '../hooks/useTheme.ts'
import { apiModeLabel } from '../services/client.ts'
import { Icon } from './ui.tsx'

interface Props {
  mode: ApiMode
  trip: TripView | null
  busy: boolean
  hasTrace: boolean
  theme: Theme
  hasDrafts: boolean
  onToggleTheme: () => void
  onOpenHistory: () => void
  onOpenSignal: () => void
  onReset: () => void
}

export function MissionBar({
  mode,
  trip,
  busy,
  hasTrace,
  theme,
  hasDrafts,
  onToggleTheme,
  onOpenHistory,
  onOpenSignal,
  onReset,
}: Props) {
  const statusLabel = busy ? 'Agent 运行中' : hasTrace ? 'Agent 已回执' : 'Agent 待命'
  const statusTone = busy ? 'busy' : hasTrace ? 'live' : ''

  return (
    <header className="mission">
      <div className="mission-brand">
        <span className="brand-mark" aria-hidden="true">
          TG
        </span>
        <div className="mission-titles">
          <p className="eyebrow">TravelGuard · 旅途智盾</p>
          <h1 className="mission-title">
            {trip ? trip.title : '多事件约束感知与最小必要重规划'}
          </h1>
        </div>
      </div>

      {trip && (
        <div className="mission-meta">
          <span className="meta-chip">
            版本 <strong>V{trip.current_version}</strong>
          </span>
          <span className="meta-chip">
            事件修订 <strong>#{trip.event_revision}</strong>
          </span>
          <span className="meta-chip">
            锁定历史 <strong>#{trip.history_revision}</strong>
          </span>
          {trip.locked_activity_ids.length > 0 && (
            <span className="meta-chip">
              锁定 <strong>{trip.locked_activity_ids.length}</strong> 项
            </span>
          )}
        </div>
      )}

      <div className="mission-actions">
        <span className="status-pill hide-sm">
          <span className={`status-dot ${statusTone}`} />
          {statusLabel}
        </span>
        <span className={`badge badge-${mode === 'mock' ? 'warn' : 'neutral'} hide-sm`}>
          {apiModeLabel(mode)}
        </span>
        {trip && (
          <button
            type="button"
            className="btn btn-signal btn-small"
            onClick={onOpenSignal}
            disabled={busy}
            data-testid="open-signal"
          >
            <Icon name="signal" size={14} />
            上报异常
          </button>
        )}
        {trip && (
          <button
            type="button"
            className="icon-btn"
            onClick={onOpenHistory}
            title="版本档案"
            aria-label="版本档案"
            data-testid="open-history"
          >
            <Icon name="history" />
          </button>
        )}
        <button
          type="button"
          className="icon-btn"
          onClick={onToggleTheme}
          title={theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
          aria-label="切换主题"
          data-testid="theme-toggle"
        >
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
        </button>
        {trip && (
          <button type="button" className="btn btn-ghost btn-small hide-sm" onClick={onReset} disabled={busy}>
            重新开始
          </button>
        )}
        {trip && (
          <button
            type="button"
            className="icon-btn show-sm"
            onClick={onReset}
            disabled={busy}
            title="重新开始"
            aria-label="重新开始"
          >
            <Icon name="refresh" />
          </button>
        )}
        {!trip && (
          <a className="mode-link hide-sm" href={mode === 'mock' ? '?mode=real' : '?mode=mock'}>
            {mode === 'mock' ? '切到真实后端' : '切到本地模拟'}
          </a>
        )}
        {trip && hasDrafts && <span className="visually-hidden">存在待决候选</span>}
      </div>
    </header>
  )
}
