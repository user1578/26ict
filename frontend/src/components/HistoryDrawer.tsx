import { useEffect } from 'react'
import type { VersionView } from '../types.ts'
import { formatCny } from '../services/money.ts'
import { formatDateTime } from '../services/time.ts'
import { Badge, CheckBadge, Icon } from './ui.tsx'

interface Props {
  versions: VersionView[]
  currentVersion: number
  onClose: () => void
}

export function HistoryDrawer({ versions, currentVersion, onClose }: Props) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div className="overlay drawer-overlay" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="版本档案"
        onClick={(event) => event.stopPropagation()}
        data-testid="history-drawer"
      >
        <header className="drawer-head">
          <div>
            <h2 className="drawer-title">版本档案</h2>
            <p className="sheet-sub">只读快照 · 确认后不可回滚为旧版本</p>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭">
            <Icon name="close" />
          </button>
        </header>
        <div className="drawer-body">
          {[...versions].reverse().map((version) => (
            <article
              key={version.version}
              className={`version-row ${version.version === currentVersion ? 'current' : ''}`}
            >
              <div className="version-head">
                <span className="version-id">V{version.version}</span>
                {version.version === currentVersion && <Badge tone="action">当前</Badge>}
                <CheckBadge status={version.validation.overall} />
                <Badge tone="neutral">事件修订 #{version.event_revision}</Badge>
                <Badge tone="neutral">锁定历史 #{version.history_revision}</Badge>
              </div>
              <p className="version-meta">
                {formatDateTime(version.created_at)} · 来源草案 {version.source_draft_id ?? '初始创建'} · 保守总支出{' '}
                {formatCny(version.budget.conservative_total_cny)}
              </p>
              {version.confirmation && (
                <p className="version-meta">
                  用户确认：{version.confirmation.confirmed_by} @ {formatDateTime(version.confirmation.confirmed_at)}
                </p>
              )}
            </article>
          ))}
          {versions.length === 0 && <p className="form-hint">还没有版本记录。</p>}
        </div>
      </aside>
    </div>
  )
}
