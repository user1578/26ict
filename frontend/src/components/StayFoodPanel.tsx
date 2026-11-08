import { useEffect, useRef, useState } from 'react'
import type { Place, PlanningBundle, Recommendation } from '../services/recommendations.ts'
import { externalPlatforms, findNearby, mapLink, routeText, type NearbyGuide } from '../services/guide.ts'

export function StayFoodPanel({ bundle, candidate, busy, onChooseStay }: {
  bundle: PlanningBundle; candidate: Recommendation; busy: boolean; onChooseStay: (place: Place) => void
}) {
  const dates = [...new Set(candidate.days.filter(d => d.kind !== 'lodging').map(d => d.date))]
  const [day, setDay] = useState(dates[0] ?? '')
  const [hotelKeyword, setHotelKeyword] = useState('酒店')
  const [foodKeyword, setFoodKeyword] = useState('地方小吃')
  const [guide, setGuide] = useState<NearbyGuide | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const requestSequence = useRef(0)
  useEffect(() => () => { requestSequence.current += 1 }, [])
  const searchWords = `${bundle.input.city} ${dates.length}日游 ${bundle.input.keywords} 住宿 美食`

  const search = async () => {
    const sequence = ++requestSequence.current
    setLoading(true); setError(null)
    try {
      const result = await findNearby(bundle.input, candidate, day, hotelKeyword, foodKeyword)
      if (sequence === requestSequence.current) setGuide(result)
    } catch (caught) {
      if (sequence === requestSequence.current) setError(caught instanceof Error ? caught.message : '附近查询未完成')
    } finally { if (sequence === requestSequence.current) setLoading(false) }
  }

  const placeLine = (place: Place) => <><strong>{place.name}</strong><p>{place.address ?? '地址待核实'} {mapLink(place) && <a href={mapLink(place)} target="_blank" rel="noreferrer">查看位置</a>}</p></>

  return <section className="guide-extras" data-testid="stay-food">
    <div className="section-head"><h3 className="section-title">住哪里 · 吃什么</h3><span className="activity-note">围绕每天的景点查找，地点来自高德地图</span></div>
    <div className="guide-search">
      <label className="field"><span>哪一天</span><select value={day} disabled={loading} onChange={e => { setDay(e.target.value); setGuide(null) }} data-testid="guide-day">{dates.map(date => <option key={date}>{date}</option>)}</select></label>
      <label className="field"><span>住宿关键词</span><input value={hotelKeyword} disabled={loading} onChange={e => { setHotelKeyword(e.target.value); setGuide(null) }} data-testid="hotel-keyword" /></label>
      <label className="field"><span>美食关键词</span><input value={foodKeyword} disabled={loading} onChange={e => { setFoodKeyword(e.target.value); setGuide(null) }} data-testid="food-keyword" /></label>
      <button type="button" className="btn btn-ghost" disabled={loading || busy || !day || !hotelKeyword.trim() || !foodKeyword.trim()} onClick={search} data-testid="search-nearby">{loading ? '正在查找附近地点…' : '查找住宿与美食'}</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {guide && <div data-testid="nearby-results">
      <p><strong>建议住宿区域：{guide.area.name}</strong></p>
      <p className="activity-note">按当天景点位置选择附近区域。酒店价格、评分、营业状态和房态均待核实。</p>
      <div className="guide-place-grid">{(guide.hotels.data ?? []).map(place => <article className="draft-card" key={place.poi_id}>
        {placeLine(place)}
        {guide.hotel_routes?.hotel_id === place.poi_id && <p>当天返回：{routeText(guide.hotel_routes.to_hotel.selected)}{guide.hotel_routes.next_morning && <><br />次日出发：{routeText(guide.hotel_routes.next_morning.selected)}</>}</p>}
        <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={() => onChooseStay(place)} data-testid="choose-stay">以此住宿位置重算交通</button>
      </article>)}</div>
      {!guide.hotels.data?.length && <p>未找到住宿地点，可换关键词重试。没有结果不代表附近没有住宿。</p>}
      {guide.meals.map(meal => <section key={meal.period} className="meal-suggestions">
        <h4>{meal.period === 'lunch' ? '午餐' : '晚餐'}建议 · {meal.suggested_time} · {meal.anchor.name}附近</h4>
        <div className="guide-place-grid">{(meal.candidates.data ?? []).map((place, i) => <article className="draft-card" key={place.poi_id}>{placeLine(place)}
          {i === 0 && meal.route && <p>{routeText(meal.route.selected)}</p>}<small className="activity-note">价格、评分与营业状态待核实</small></article>)}</div>
        {!meal.candidates.data?.length && <p>未找到符合关键词的餐饮地点，可换关键词重试。</p>}
        <p className="activity-note">{meal.note}</p>
      </section>)}
      <details><summary>查看住宿与美食依据</summary><p>{guide.area.basis}</p><p>{guide.note}</p><pre>{JSON.stringify(guide, null, 2)}</pre></details>
    </div>}
    <div className="external-options">
      <h4>再看看其他人的攻略与平台信息</h4>
      <p>建议搜索：{searchWords}</p>
      <button type="button" className="btn btn-ghost btn-small" onClick={async () => { try { await navigator.clipboard.writeText(searchWords); setCopied(true) } catch { setCopied(false) } }}>{copied ? '已复制搜索词' : '复制搜索词'}</button>
      <nav aria-label="外部旅行平台">{externalPlatforms.map(platform => <a key={platform.name} href={platform.url} target="_blank" rel="noreferrer">打开{platform.name}官网 ↗</a>)}</nav>
      <p className="activity-note">外部平台可能需要登录或使用 App；这里未接入其价格、余票或房态数据，不执行预订或支付。</p>
    </div>
  </section>
}
