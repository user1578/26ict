import { afterEach, describe, expect, it, vi } from 'vitest'
import { recommend, type PlanningInput } from '../recommendations.ts'
const input: PlanningInput = { origin_city:'上海',city:'南京',arrival_station:'南京站',return_station:'南京站',
  keywords:'公园',start_date:'2026-11-10',end_date:'2026-11-11',party_size:2,budget_cny:'1000',
  max_walking_minutes_per_leg:20,arrival_time:'09:00',return_time:'17:00',stay_together:true,other_costs_cny:null }
afterEach(()=>vi.unstubAllGlobals())
describe('真实推荐 HTTP 边界',()=>{
  it('发送真实目的地与日期且不在浏览器注入工具密钥',async()=>{
    const fetcher=vi.fn<(url:string,init?:RequestInit)=>Promise<Response>>(async()=>new Response(JSON.stringify({generator:'rules-v1'}),{status:200}))
    vi.stubGlobal('fetch',fetcher)
    await recommend(input)
    const [url, init]=fetcher.mock.calls[0] as unknown as [string,RequestInit]
    expect(url).toBe('/api/recommendations')
    expect(JSON.parse(init.body as string)).toEqual(input)
    expect(init.headers).toEqual({'Content-Type':'application/json'})
  })
  it('后端不可达时给出具体代理错误，不返回模拟方案',async()=>{
    vi.stubGlobal('fetch',async()=>new Response('',{status:502}))
    await expect(recommend(input)).rejects.toThrow('无法连接行程服务')
  })
  it('既有旅行重新推荐使用编码后的旅行路径',async()=>{
    const fetcher=vi.fn<(url:string,init?:RequestInit)=>Promise<Response>>(async()=>new Response('{}',{status:200}))
    vi.stubGlobal('fetch',fetcher)
    await recommend(input,'trip:杭州')
    expect(fetcher.mock.calls[0][0]).toBe('/api/trips/trip%3A%E6%9D%AD%E5%B7%9E/recommendations')
  })
})
