import { afterEach, describe, expect, it, vi } from 'vitest'
import { externalPlatforms, findNearby, routeText, statusText } from '../guide.ts'
import type { PlanningInput, Recommendation, SelectedRoute } from '../recommendations.ts'
import { readPlanning } from '../recommendations.ts'

afterEach(() => vi.unstubAllGlobals())

describe('用户攻略表达与真实查询边界', () => {
  it('旧缓存只恢复查询输入，不虚构缺失金额或继续信任旧候选状态', () => {
    const old = { generator: 'rules-v1', input: { city: '杭州' }, places: [],
      candidates: [{ validation: { overall: 'PASS' }, known_cost_cny: '100.00' }] }
    vi.stubGlobal('localStorage', { getItem: () => JSON.stringify(old) })
    const restored = readPlanning('old-trip')!
    expect(restored.input.city).toBe('杭州')
    expect(restored.candidates).toEqual([])
    expect(restored.needs_refresh).toBe(true)
  })
  it('失败路线显示需要调整，不以普通待核实弱化冲突', () => {
    expect(statusText({ feasibility: 'infeasible', validation: { overall: 'FAIL' } } as Recommendation)).toBe('需要调整')
    expect(statusText({ feasibility: 'unverified', validation: { overall: 'UNKNOWN' } } as Recommendation)).toBe('待核实')
  })

  it('骑行和接驳步行不混为直线估算', () => {
    const text = routeText({ mode: 'bicycling', duration_minutes: 18, walking_minutes: null } as SelectedRoute)
    expect(text).toContain('自行车约 18 分钟')
    expect(text).toContain('待核实')
    expect(routeText(null)).toContain('尚未找到')
  })

  it('外部平台只指向核实过的官网，没有拼接搜索或价格参数', () => {
    expect(externalPlatforms.map(p => p.url)).toEqual([
      'https://www.xiaohongshu.com/', 'https://www.meituan.com/', 'https://www.suanya.com/',
    ])
  })

  it('住宿美食请求保留日期、坐标与允许的出行方式，排除住宿活动作为餐饮锚点', async () => {
    const place = { poi_id: 'amap:1', name: '南京景点', address: null, indoor: null, location: { longitude: 118.8, latitude: 32.0 } }
    const input = { city: '南京', allowed_modes: ['bicycling'], max_walking_minutes_per_leg: 10 } as PlanningInput
    const candidate = { days: [
      { date: '2026-11-10', place, kind: 'visit' },
      { date: '2026-11-10', place: { ...place, poi_id: 'amap:hotel' }, kind: 'lodging' },
      { date: '2026-11-11', place, kind: 'visit' },
    ] } as Recommendation
    const fetcher = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    await findNearby(input, candidate, '2026-11-10', '酒店', '火锅')
    const body = JSON.parse(fetcher.mock.calls[0][1]!.body as string)
    expect(body.city).toBe('南京')
    expect(body.visits).toEqual([place])
    expect(body.allowed_modes).toEqual(['bicycling'])
    expect(body.food_keyword).toBe('火锅')
    expect(body.next_day_first).toEqual(place)
    expect(fetcher.mock.calls[0][1]!.headers).toEqual({ 'Content-Type': 'application/json' })
  })
})
