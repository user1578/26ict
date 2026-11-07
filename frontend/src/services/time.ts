/** 时间统一按 Asia/Shanghai 展示；服务端生成时间为 UTC，用户输入时间为 +08:00。 */

const TZ = 'Asia/Shanghai'

const partsFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

interface ShanghaiParts {
  year: string
  month: string
  day: string
  hour: string
  minute: string
}

function partsOf(date: Date): ShanghaiParts {
  const parts = partsFormatter.formatToParts(date)
  const pick = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? '00'
  return {
    year: pick('year'),
    month: pick('month'),
    day: pick('day'),
    hour: pick('hour'),
    minute: pick('minute'),
  }
}

export function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const p = partsOf(date)
  return `${p.year}-${p.month}-${p.day}`
}

export function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const p = partsOf(date)
  return `${p.hour}:${p.minute}`
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const p = partsOf(date)
  return `${p.month}-${p.day} ${p.hour}:${p.minute}`
}

export function fromEpoch(epochMs: number): string {
  const p = partsOf(new Date(epochMs))
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:00+08:00`
}

/** 用户输入（日期 + 时间）→ 带 +08:00 的 ISO。 */
export function toShanghaiIso(date: string, time: string): string {
  return `${date}T${time}:00+08:00`
}

export function addMinutes(iso: string, minutes: number): string {
  return fromEpoch(Date.parse(iso) + minutes * 60_000)
}

export function addDays(date: string, days: number): string {
  const epoch = Date.parse(`${date}T00:00:00+08:00`)
  return fromEpoch(epoch + days * 24 * 60 * 60 * 1000).slice(0, 10)
}

export function compareIso(left: string, right: string): number {
  return Date.parse(left) - Date.parse(right)
}

export function minutesBetween(startIso: string, endIso: string): number {
  return Math.round((Date.parse(endIso) - Date.parse(startIso)) / 60_000)
}

export function humanMinutes(value: number | null): string {
  return value === null ? '未知' : `${value} 分钟`
}
