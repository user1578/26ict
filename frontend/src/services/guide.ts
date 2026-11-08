import type { Place, PlanningInput, Recommendation, SelectedRoute, ToolResult } from './recommendations.ts'

export const transportLabels = { transit: '地铁/公交', walking: '步行', bicycling: '自行车', driving: '驾车' } as const
export const externalPlatforms = [
  { name: '小红书', url: 'https://www.xiaohongshu.com/' },
  { name: '美团', url: 'https://www.meituan.com/' },
  { name: '智行', url: 'https://www.suanya.com/' },
] as const

export function routeText(route: SelectedRoute | null | undefined): string {
  if (!route) return '尚未找到符合当前偏好的路线'
  const mode = transportLabels[route.mode as keyof typeof transportLabels] ?? '交通'
  return `${mode}约 ${route.duration_minutes} 分钟${route.mode !== 'walking' ? ` · 接驳步行${route.walking_minutes === null ? '待核实' : ` ${route.walking_minutes} 分钟`}` : ''}`
}

export function statusText(candidate: Recommendation): string {
  return candidate.feasibility === 'infeasible' ? '需要调整' : candidate.validation.overall === 'PASS' ? '可以确认' : '待核实'
}

export function mapLink(place: Place): string | undefined {
  return place.location ? `https://uri.amap.com/marker?position=${place.location.longitude},${place.location.latitude}&name=${encodeURIComponent(place.name)}&coordinate=gaode&callnative=0` : undefined
}

interface RouteReference { selected: SelectedRoute | null; options: unknown }
export interface NearbyGuide {
  on_date: string; area: { name: string; basis: string }; hotels: ToolResult<Place[]>
  hotel_routes: { hotel_id: string; to_hotel: RouteReference; next_morning: RouteReference | null } | null
  meals: Array<{ period: 'lunch' | 'dinner'; suggested_time: string; anchor: Place
    candidates: ToolResult<Place[]>; route: RouteReference | null; note: string }>
  availability: 'unknown'; price_cny: null; rating: null; note: string
}

export async function findNearby(input: PlanningInput, candidate: Recommendation, day: string,
  hotelKeyword: string, foodKeyword: string): Promise<NearbyGuide> {
  const visits = candidate.days.filter(d => d.date === day && d.kind !== 'lodging' && d.place?.location).map(d => d.place!)
  const nextDay = candidate.days.find(d => d.date > day && d.kind !== 'lodging' && d.place?.location)
  const response = await fetch('/api/guide/nearby', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ city: input.city, on_date: day, visits, next_day_first: nextDay?.place ?? null, next_day_date: nextDay?.date ?? null,
      hotel_keyword: hotelKeyword, food_keyword: foodKeyword, allowed_modes: input.allowed_modes ?? ['transit', 'walking'],
      max_walking_minutes_per_leg: input.max_walking_minutes_per_leg }) })
  if (!response.ok) throw new Error('附近住宿与美食查询未完成，请稍后重试。')
  return response.json() as Promise<NearbyGuide>
}
