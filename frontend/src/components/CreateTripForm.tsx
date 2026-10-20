import type { FormEvent } from 'react'

export interface TripFormValues {
  city: string
  startDate: string
  endDate: string
  partySize: string
  budget: string
  walkingLimit: string
  returnTime: string
}

interface Props {
  values: TripFormValues
  error: string | null
  onChange: (patch: Partial<TripFormValues>) => void
  onSubmit: () => void
}

export function CreateTripForm({ values, error, onChange, onSubmit }: Props) {
  return (
    <form
      className="card form-card"
      onSubmit={(event: FormEvent) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <h2>创建旅行</h2>
      <p className="hint">
        填写基础需求，生成一版模拟正式行程。当前未连接后端与 AgentArts，所有数据都在浏览器本地。
      </p>
      <div className="form-grid">
        <label>
          城市
          <input value={values.city} onChange={(event) => onChange({ city: event.target.value })} />
        </label>
        <label>
          出发日期
          <input type="date" value={values.startDate} onChange={(event) => onChange({ startDate: event.target.value })} />
        </label>
        <label>
          返回日期
          <input type="date" value={values.endDate} onChange={(event) => onChange({ endDate: event.target.value })} />
        </label>
        <label>
          同行人数
          <input type="number" min="1" max="10" value={values.partySize} onChange={(event) => onChange({ partySize: event.target.value })} />
        </label>
        <label>
          预算（元）
          <input type="number" min="0" step="50" value={values.budget} onChange={(event) => onChange({ budget: event.target.value })} />
        </label>
        <label>
          单段步行上限（分钟）
          <input type="number" min="0" step="5" value={values.walkingLimit} onChange={(event) => onChange({ walkingLimit: event.target.value })} />
        </label>
        <label>
          返程截止时间
          <input type="time" value={values.returnTime} onChange={(event) => onChange({ returnTime: event.target.value })} />
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      <button type="submit" className="primary">
        生成行程（模拟）
      </button>
    </form>
  )
}
