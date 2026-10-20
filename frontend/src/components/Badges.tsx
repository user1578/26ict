import type { Feasibility, SourceType, VerificationStatus } from '../types.ts'

const sourceLabels: Record<SourceType, string> = {
  real: '真实',
  simulation: '模拟',
  estimate: '估算',
}

const verificationLabels: Record<VerificationStatus, string> = {
  PASS: '通过',
  FAIL: '不通过',
  UNKNOWN: '未知',
  NOT_APPLICABLE: '不适用',
}

const feasibilityLabels: Record<Feasibility, string> = {
  feasible: '可行',
  conditional: '有条件可行',
  infeasible: '不可行',
  unknown: '未知',
}

export function SourceBadge({ value }: { value: SourceType }) {
  return <span className={`badge badge-source-${value}`}>{sourceLabels[value]}</span>
}

export function VerificationBadge({ value }: { value: VerificationStatus }) {
  return <span className={`badge badge-check-${value.toLowerCase()}`}>{verificationLabels[value]}</span>
}

export function FeasibilityBadge({ value }: { value: Feasibility }) {
  return <span className={`badge badge-feasibility-${value}`}>{feasibilityLabels[value]}</span>
}
