import type { ReactNode } from 'react'
import type { Check, CheckStatus, DraftStatus } from '../types.ts'
import { checkLabel, checkTone } from '../lib/labels.ts'

export type IconName =
  | 'signal'
  | 'check'
  | 'question'
  | 'clock'
  | 'lock'
  | 'sun'
  | 'moon'
  | 'history'
  | 'agent'
  | 'close'
  | 'arrow'
  | 'plus'
  | 'refresh'
  | 'chevron'
  | 'pin'
  | 'route'

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }
  switch (name) {
    case 'signal':
      return (
        <svg {...common}>
          <path d="M12 3 2.8 19.2h18.4L12 3Z" />
          <path d="M12 9.4v4.1" />
          <circle cx="12" cy="16.4" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'check':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8.6" />
          <path d="m8.2 12.2 2.6 2.6 5-5.2" />
        </svg>
      )
    case 'question':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8.6" />
          <path d="M9.5 9.4a2.6 2.6 0 1 1 3.4 2.5c-.7.3-.9.9-.9 1.7" />
          <circle cx="12" cy="16.9" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'clock':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8.6" />
          <path d="M12 7v5.2l3.1 2" />
        </svg>
      )
    case 'lock':
      return (
        <svg {...common}>
          <rect x="5" y="10.4" width="14" height="9.2" rx="1.4" />
          <path d="M8.5 10.4V8a3.5 3.5 0 0 1 7 0v2.4" />
        </svg>
      )
    case 'sun':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2.6v2M12 19.4v2M2.6 12h2M19.4 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" />
        </svg>
      )
    case 'moon':
      return (
        <svg {...common}>
          <path d="M20 14.3A8.4 8.4 0 0 1 9.7 4 8.5 8.5 0 1 0 20 14.3Z" />
        </svg>
      )
    case 'history':
      return (
        <svg {...common}>
          <path d="M3.6 12a8.4 8.4 0 1 0 2.5-6" />
          <path d="M3 5.6V9.2h3.6" />
          <path d="M12 7.4V12l3 1.9" />
        </svg>
      )
    case 'agent':
      return (
        <svg {...common}>
          <rect x="4" y="7.2" width="16" height="10.8" rx="2" />
          <path d="M12 3.6v3.6" />
          <path d="M8.2 11.2h.01M15.8 11.2h.01" strokeWidth={2.2} />
          <path d="M9.2 15h5.6" />
        </svg>
      )
    case 'close':
      return (
        <svg {...common}>
          <path d="m6 6 12 12M18 6 6 18" />
        </svg>
      )
    case 'arrow':
      return (
        <svg {...common}>
          <path d="M4.5 12h14.5M14 7l5 5-5 5" />
        </svg>
      )
    case 'plus':
      return (
        <svg {...common}>
          <path d="M12 4.5v15M4.5 12h15" />
        </svg>
      )
    case 'refresh':
      return (
        <svg {...common}>
          <path d="M20 11a8 8 0 1 0-2.3 6.6" />
          <path d="M20 5.2V11h-5.8" />
        </svg>
      )
    case 'chevron':
      return (
        <svg {...common}>
          <path d="m6 9 6 6 6-6" />
        </svg>
      )
    case 'pin':
      return (
        <svg {...common}>
          <path d="M12 21s7-5.4 7-11a7 7 0 1 0-14 0c0 5.6 7 11 7 11Z" />
          <circle cx="12" cy="10" r="2.4" />
        </svg>
      )
    case 'route':
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="2.4" />
          <circle cx="18" cy="18" r="2.4" />
          <path d="M8.4 6H14a4 4 0 0 1 0 8H9.6a3.2 3.2 0 0 0 0 6.4h6" />
        </svg>
      )
  }
}

export type BadgeTone = 'pass' | 'warn' | 'fail' | 'unknown' | 'neutral' | 'sim' | 'action'

export function Badge({
  tone = 'neutral',
  children,
  title,
}: {
  tone?: BadgeTone
  children: ReactNode
  title?: string
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  )
}

export function CheckBadge({ status }: { status: CheckStatus }) {
  const labels: Record<CheckStatus, string> = {
    PASS: '通过',
    FAIL: '不通过',
    UNKNOWN: '未知',
    NOT_APPLICABLE: '不适用',
  }
  return <Badge tone={checkTone(status)}>{labels[status]}</Badge>
}

export function DraftStateBadge({ status }: { status: DraftStatus }) {
  const labels: Record<DraftStatus, string> = {
    pending: '待确认',
    stale: '已失效',
    committed: '已确认',
  }
  const tone: Record<DraftStatus, BadgeTone> = {
    pending: 'action',
    stale: 'neutral',
    committed: 'pass',
  }
  return <Badge tone={tone[status]}>{labels[status]}</Badge>
}

export function CheckList({
  checks,
  onlyProblems = false,
}: {
  checks: Check[]
  onlyProblems?: boolean
}) {
  const visible = onlyProblems
    ? checks.filter((check) => check.status === 'FAIL' || check.status === 'UNKNOWN')
    : checks
  if (visible.length === 0) {
    return <p className="form-hint">没有需要关注的问题。</p>
  }
  return (
    <ul className="check-list">
      {visible.map((check) => (
        <li key={check.name} className="check-item">
          <span className="check-name">
            {checkLabel(check.name)} <CheckBadge status={check.status} />
          </span>
          <span className="check-detail">{check.detail}</span>
        </li>
      ))}
    </ul>
  )
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}
