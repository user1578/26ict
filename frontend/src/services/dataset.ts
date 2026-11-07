/** C 侧数据三件套：data/wuhan_pois.json、data/wuhan_rules.json、data/evidence_registry.json。
 *  全部为人工构造的模拟数据（data_type=simulated / verification_status=unverified）。
 *  Vite 允许从仓库根目录 data/ 静态导入，构建时打包。 */

import poisJson from '../../../data/wuhan_pois.json'
import rulesJson from '../../../data/wuhan_rules.json'
import evidenceJson from '../../../data/evidence_registry.json'

export interface LonLat {
  longitude: number
  latitude: number
}

export interface PoiRecord {
  poi_id: string
  name: string
  amap_id: string | null
  amap_mapping_status: string
  address: string
  coordinates: { gcj02: LonLat; wgs84: LonLat }
  coordinate_note: string
  category: string
  indoor: boolean
  data_type: string
  verification_status: string
  source_ref: string
  retrieved_at: string
}

export interface RuleRecord {
  poi_id: string
  opening_status: string
  booking_required: boolean
  booking_note: string | null
  ticket_price_cny: string
  valid_from: string
  valid_until: string
  source_ref: string
  retrieved_at: string
  data_type: string
  verification_status: string
}

export interface EvidenceRecord {
  kind: string
  poi_id: string | null
  summary: string
  data_type: string
  verification_status: string
  source_ref: string
  retrieved_at: string
}

interface PoiFile {
  format_version: number
  city: string
  note: string
  records: PoiRecord[]
}

interface RuleFile {
  format_version?: number
  note?: string
  records: RuleRecord[]
}

interface EvidenceFile {
  format_version: number
  note: string
  records: Record<string, EvidenceRecord>
}

const pois = (poisJson as unknown as PoiFile).records
const rules = (rulesJson as unknown as RuleFile).records
const evidence = (evidenceJson as unknown as EvidenceFile).records

export const dataset = {
  city: (poisJson as unknown as PoiFile).city,
  pois,
  rules,
  evidence,
}

export const poiById = new Map<string, PoiRecord>(pois.map((record) => [record.poi_id, record]))
export const ruleByPoiId = new Map<string, RuleRecord>(rules.map((record) => [record.poi_id, record]))

export function poiName(poiId: string): string {
  return poiById.get(poiId)?.name ?? poiId
}

export function poiRule(poiId: string): RuleRecord | undefined {
  return ruleByPoiId.get(poiId)
}

export function evidenceOf(ref: string): EvidenceRecord | undefined {
  return evidence[ref]
}

export function evidenceSummary(ref: string): string {
  return evidence[ref]?.summary ?? ref
}

/** 规划器使用的稳定 POI ID（与 data/wuhan_pois.json 对齐）。 */
export const POI = {
  hubeiMuseum: 'local:wh-hubei-museum',
  eastLakeGreenway: 'local:wh-east-lake-greenway',
  yellowCraneTower: 'local:wh-yellow-crane-tower',
  hubuxiang: 'local:wh-hubuxiang',
  xinhaiMuseum: 'local:wh-xinhai-revolution-museum',
} as const

/** 规划器 / 证据登记里约定好的模拟证据引用。 */
export const EVIDENCE = {
  openingHubeiMuseum: 'simulation:opening:hubei-museum',
  openingEastLake: 'simulation:opening:east-lake-greenway',
  openingYellowCrane: 'simulation:opening:yellow-crane-tower',
  openingHubuxiang: 'simulation:opening:hubuxiang',
  openingXinhaiMuseum: 'simulation:opening:xinhai-revolution-museum',
  bookingHubeiMuseum: 'simulation:booking:hubei-museum',
  paidYellowCraneTicket: 'simulation:financial:paid-yellow-crane-ticket',
} as const
