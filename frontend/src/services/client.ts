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
import { httpApi } from './httpApi.ts'
import { MockTravelGuardApi } from './mockApi.ts'

export type ApiMode = 'real' | 'mock'

export interface TravelGuardApi {
  readonly mode: ApiMode
  createTrip(body: CreateTripRequest): Promise<TripView>
  getTrip(tripId: string): Promise<TripView>
  getVersions(tripId: string): Promise<VersionView[]>
  putEvent(tripId: string, eventId: string, body: PutEventRequest): Promise<EventView>
  createDraft(tripId: string, body: CreateDraftRequest): Promise<DraftView>
  getDrafts(tripId: string): Promise<DraftView[]>
  getDraft(tripId: string, draftId: string): Promise<DraftView>
  confirmDraft(tripId: string, draftId: string, body: ConfirmDraftRequest): Promise<VersionView>
  lockActivities(tripId: string, body: LockActivitiesRequest): Promise<TripView>
}

/** 默认真实后端；`?mode=mock` 或 VITE_TRAVELGUARD_MODE=mock 切换到本地模拟。 */
export function resolveApiMode(): ApiMode {
  const fromQuery = new URLSearchParams(window.location.search).get('mode')
  if (fromQuery === 'mock' || fromQuery === 'real') return fromQuery
  const fromEnv = import.meta.env.VITE_TRAVELGUARD_MODE as string | undefined
  return fromEnv === 'mock' ? 'mock' : 'real'
}

export function createApi(mode: ApiMode = resolveApiMode()): TravelGuardApi {
  return mode === 'mock' ? new MockTravelGuardApi() : httpApi
}

export function apiModeLabel(mode: ApiMode): string {
  return mode === 'mock' ? '演示数据' : '行程规划'
}
