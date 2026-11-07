import type { CheckStatus } from '../types.ts'

const checkLabels: Record<string, string> = {
  time_check: '时间冲突',
  opening_check: '开放状态',
  booking_check: '预约要求',
  budget_check: '预算',
  walking_check: '步行强度',
  return_check: '返程截止',
  return_timeline_check: '返程时间线',
  state_check: '锁定活动',
  evidence_check: '事实证据',
  financial_state_check: '资金状态',
  locked_evidence_check: '锁定证据',
  booking_state_check: '预约状态',
}

export function checkLabel(name: string): string {
  if (name.startsWith('event:')) {
    const parts = name.split(':')
    return `异常 ${parts[1] ?? ''}${parts.length > 2 ? ' 证据' : ''}`
  }
  return checkLabels[name] ?? name
}

export function checkTone(status: CheckStatus): 'pass' | 'fail' | 'unknown' | 'neutral' {
  if (status === 'PASS') return 'pass'
  if (status === 'FAIL') return 'fail'
  if (status === 'UNKNOWN') return 'unknown'
  return 'neutral'
}
