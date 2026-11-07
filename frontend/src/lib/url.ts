import type { ApiMode } from '../services/client.ts'

const TRIP_PARAM = 'trip'

export function readTripId(): string | null {
  return new URLSearchParams(window.location.search).get(TRIP_PARAM)
}

/** 同步 trip 与 mode 到地址栏，刷新后可恢复（mock 模式无法恢复内存状态）。 */
export function syncUrl(tripId: string | null, mode: ApiMode) {
  const params = new URLSearchParams(window.location.search)
  if (tripId) params.set(TRIP_PARAM, tripId)
  else params.delete(TRIP_PARAM)
  if (mode === 'mock') params.set('mode', 'mock')
  else params.delete('mode')
  const query = params.toString()
  window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`)
}
