import type {
  ConfirmDraftRequest,
  CreateDraftRequest,
  CreateTripRequest,
  DraftView,
  EventView,
  LockActivitiesRequest,
  PutEventRequest,
  TripView,
  VersionView,
} from '../types.ts'
import { ApiError, type ValidationIssue } from './apiError.ts'
import type { TravelGuardApi } from './client.ts'

interface ErrorDetail {
  code?: string
  message?: string
  validation?: DraftView['validation']
}

function parseError(status: number, payload: unknown): ApiError {
  const detail = (payload as { detail?: unknown } | null)?.detail
  if (Array.isArray(detail)) {
    const issues: ValidationIssue[] = detail.map((item) => {
      const record = item as { loc?: Array<string | number>; msg?: string }
      return {
        path: Array.isArray(record.loc) ? record.loc.join('.') : '',
        message: record.msg ?? '字段不合法',
      }
    })
    return new ApiError(status, 'validation_error', '请求校验失败', { issues })
  }
  if (detail && typeof detail === 'object') {
    const shaped = detail as ErrorDetail
    return new ApiError(status, shaped.code ?? 'business_error', shaped.message ?? '请求失败', {
      validation: shaped.validation,
    })
  }
  return new ApiError(status, 'http_error', typeof payload === 'string' ? payload : `HTTP ${status}`)
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(
      0,
      'network_error',
      '无法连接后端：请确认 B 的后端已在 127.0.0.1:8000 启动，并且开发代理已注入 X-Tool-Key。',
    )
  }
  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text) as unknown
    } catch {
      payload = text
    }
  }
  if (!response.ok) {
    throw parseError(response.status, payload)
  }
  return payload as T
}

const tripPath = (tripId: string) => `/api/trips/${encodeURIComponent(tripId)}`
const draftPath = (tripId: string, draftId: string) =>
  `${tripPath(tripId)}/drafts/${encodeURIComponent(draftId)}`

export const httpApi: TravelGuardApi = {
  mode: 'real',

  createTrip: (body: CreateTripRequest) => request<TripView>('POST', '/api/trips', body),
  getTrip: (tripId: string) => request<TripView>('GET', tripPath(tripId)),
  getVersions: (tripId: string) => request<VersionView[]>('GET', `${tripPath(tripId)}/versions`),
  putEvent: (tripId: string, eventId: string, body: PutEventRequest) =>
    request<EventView>('PUT', `${tripPath(tripId)}/events/${encodeURIComponent(eventId)}`, body),
  createDraft: (tripId: string, body: CreateDraftRequest) =>
    request<DraftView>('POST', `${tripPath(tripId)}/drafts`, body),
  getDrafts: (tripId: string) => request<DraftView[]>('GET', `${tripPath(tripId)}/drafts`),
  getDraft: (tripId: string, draftId: string) => request<DraftView>('GET', draftPath(tripId, draftId)),
  confirmDraft: (tripId: string, draftId: string, body: ConfirmDraftRequest) =>
    request<VersionView>('POST', `${draftPath(tripId, draftId)}/confirm`, body),
  lockActivities: (tripId: string, body: LockActivitiesRequest) =>
    request<TripView>('POST', `${tripPath(tripId)}/locks`, body),
}
