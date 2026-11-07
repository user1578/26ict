import type { TravelPlan } from '../types.ts'

/** 把十进制金额字符串转成整数分，避免二进制浮点累加。 */
export function toCents(value: string): number {
  const trimmed = value.trim()
  const negative = trimmed.startsWith('-')
  const body = negative ? trimmed.slice(1) : trimmed
  const [intPart = '0', fracPart = ''] = body.split('.')
  if (!/^\d+$/.test(intPart) || !/^\d{0,2}$/.test(fracPart)) {
    throw new Error(`无法解析金额：${value}`)
  }
  const cents = Number(intPart) * 100 + Number((fracPart + '00').slice(0, 2))
  if (!Number.isSafeInteger(cents)) {
    throw new Error(`金额超出安全范围：${value}`)
  }
  return negative ? -cents : cents
}

export function cnyFromCents(cents: number): string {
  const negative = cents < 0
  const abs = Math.abs(cents)
  const yuan = Math.floor(abs / 100)
  const fen = String(abs % 100).padStart(2, '0')
  return `${negative ? '-' : ''}${yuan}.${fen}`
}

/** 展示用：¥1,300.00 / -¥55.00。 */
export function formatCny(value: string): string {
  const cents = toCents(value)
  const negative = cents < 0
  const abs = Math.abs(cents)
  const yuan = Math.floor(abs / 100).toLocaleString('zh-CN')
  const fen = String(abs % 100).padStart(2, '0')
  return `${negative ? '-' : ''}¥${yuan}.${fen}`
}

export function sumCny(values: string[]): string {
  return cnyFromCents(values.reduce((total, value) => total + toCents(value), 0))
}

/** 与 B 的 budget 公式一致：已付 + 待付 − 已到账退款（pending 退款不抵扣）。 */
export function planTotalCny(plan: TravelPlan): string {
  const paid = plan.charges.filter((charge) => charge.status === 'paid').map((charge) => charge.amount_cny)
  const planned = plan.charges.filter((charge) => charge.status === 'planned').map((charge) => charge.amount_cny)
  const received = plan.refunds
    .filter((refund) => refund.status === 'received')
    .map((refund) => refund.amount_cny)
  return cnyFromCents(
    paid.reduce((total, value) => total + toCents(value), 0) +
      planned.reduce((total, value) => total + toCents(value), 0) -
      received.reduce((total, value) => total + toCents(value), 0),
  )
}

export function subtractCny(left: string, right: string): string {
  return cnyFromCents(toCents(left) - toCents(right))
}

export function isPositiveCny(value: string): boolean {
  return toCents(value) > 0
}
