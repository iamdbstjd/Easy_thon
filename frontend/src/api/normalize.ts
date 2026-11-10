// 서버에서 받은 JSON을 types.ts 형태로 맞춘다.
// - 빠진 필드는 schemas.py의 기본값으로 채운다.
// - schemas.py에 없는 필드는 버린다. 이 값을 그대로 /api/check로 돌려보내므로,
//   여기서 걸러 두면 extra="forbid" 때문에 요청이 거절되는 일이 없다.

import type {
  BuildingRegister,
  ChecklistItem,
  CheckRequest,
  ContractExtract,
  Evidence,
  EvidenceDoc,
  Entry,
  ExtractResponse,
  Level,
  ManualInput,
  MarketPrice,
  Report,
  RegistryExtract,
  RuleResult,
} from './types'

type Json = Record<string, unknown>

function obj(v: unknown): Json {
  return v !== null && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {}
}
function str(v: unknown): string | null {
  return typeof v === 'string' ? v : null
}
function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}
function bool(v: unknown, fallback: boolean): boolean {
  return typeof v === 'boolean' ? v : fallback
}
function boolOrNull(v: unknown): boolean | null {
  return typeof v === 'boolean' ? v : null
}
function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
}
function list(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}
function oneOf<T extends string>(v: unknown, allowed: readonly T[]): T | null {
  return typeof v === 'string' && (allowed as readonly string[]).includes(v) ? (v as T) : null
}

export function normEntry(raw: unknown): Entry {
  const v = obj(raw)
  return {
    rank: str(v.rank) ?? '',
    purpose: str(v.purpose) ?? '',
    received_at: str(v.received_at),
    cause: str(v.cause),
    holders: strList(v.holders),
    amount: num(v.amount),
    is_cancelled: bool(v.is_cancelled, false),
    page: num(v.page),
    source_text: str(v.source_text) ?? '',
  }
}

export function normRegistry(raw: unknown): RegistryExtract {
  const v = obj(raw)
  const unit = obj(v.unit)
  return {
    is_registry: bool(v.is_registry, true),
    registry_type: oneOf(v.registry_type, ['집합건물', '건물', '토지'] as const),
    viewed_at: str(v.viewed_at),
    address_jibun: str(v.address_jibun),
    address_road: str(v.address_road),
    building_name: str(v.building_name),
    unit: {
      dong: str(unit.dong),
      ho: str(unit.ho),
      floor: str(unit.floor),
      area_m2: num(unit.area_m2),
    },
    building_use_lines: strList(v.building_use_lines),
    gapgu: list(v.gapgu).map(normEntry),
    eulgu: list(v.eulgu).map(normEntry),
    unreadable: strList(v.unreadable),
  }
}

export function normContract(raw: unknown): ContractExtract | null {
  if (raw === null || raw === undefined) return null
  const v = obj(raw)
  const unit = obj(v.unit)
  const sources = obj(v.sources)
  return {
    is_contract: bool(v.is_contract, true),
    landlord_names: strList(v.landlord_names),
    agent_name: str(v.agent_name),
    address: str(v.address),
    unit: { dong: str(unit.dong), ho: str(unit.ho) },
    lease_type: oneOf(v.lease_type, ['전세', '월세'] as const),
    deposit: num(v.deposit),
    monthly_rent: num(v.monthly_rent),
    contract_date: str(v.contract_date),
    balance_date: str(v.balance_date),
    move_in_date: str(v.move_in_date),
    lease_end: str(v.lease_end),
    special_terms: strList(v.special_terms),
    sources: {
      landlord: str(sources.landlord),
      address: str(sources.address),
      deposit: str(sources.deposit),
      special_terms: str(sources.special_terms),
    },
  }
}

export function normManual(raw: unknown): ManualInput {
  const v = obj(raw)
  return {
    deposit: num(v.deposit),
    monthly_rent: num(v.monthly_rent),
    contract_date: str(v.contract_date),
    landlord_name: str(v.landlord_name),
    prior_deposits: num(v.prior_deposits),
    market_price: num(v.market_price),
  }
}

export function normBuilding(raw: unknown): BuildingRegister | null {
  if (raw === null || raw === undefined) return null
  const v = obj(raw)
  return {
    main_use: str(v.main_use),
    unit_use: str(v.unit_use),
    is_violating: boolOrNull(v.is_violating),
    source: oneOf(v.source, ['api', 'pdf'] as const) ?? 'pdf',
    source_text: str(v.source_text),
  }
}

export function normMarket(raw: unknown): MarketPrice | null {
  if (raw === null || raw === undefined) return null
  const v = obj(raw)
  return {
    price: num(v.price),
    method: oneOf(v.method, ['same_building', 'same_dong', 'manual'] as const) ?? 'manual',
    deals: num(v.deals) ?? 0,
    period: str(v.period),
  }
}

export function normCheckRequest(raw: unknown): CheckRequest {
  const v = obj(raw)
  return {
    registry: normRegistry(v.registry),
    contract: normContract(v.contract),
    manual: normManual(v.manual),
    building: normBuilding(v.building),
    market: normMarket(v.market),
    today: str(v.today),
    mode: v.mode === 'demo' ? 'demo' : 'live',
  }
}

export function normExtractResponse(raw: unknown): ExtractResponse {
  const v = obj(raw)
  return { registry: normRegistry(v.registry), contract: normContract(v.contract) }
}

const LEVELS = ['red', 'yellow', 'green', 'unknown'] as const
const DOCS = ['registry', 'contract', 'building', 'market', 'manual'] as const

function normEvidence(raw: unknown): Evidence | null {
  const v = obj(raw)
  const doc = oneOf<EvidenceDoc>(v.doc, DOCS)
  if (!doc) return null
  return { doc, page: num(v.page), text: str(v.text) ?? '' }
}

function normRule(raw: unknown): RuleResult {
  const v = obj(raw)
  return {
    id: str(v.id) ?? '',
    name: str(v.name) ?? '',
    level: oneOf<Level>(v.level, LEVELS) ?? 'unknown',
    title: str(v.title) ?? '',
    summary: str(v.summary) ?? '',
    action: str(v.action) ?? '',
    evidence: list(v.evidence)
      .map(normEvidence)
      .filter((e): e is Evidence => e !== null),
    unknown_reason: str(v.unknown_reason),
  }
}

function normChecklistItem(raw: unknown): ChecklistItem {
  const v = obj(raw)
  return { when: str(v.when) ?? '', date: str(v.date), title: str(v.title) ?? '' }
}

export function normReport(raw: unknown): Report {
  const v = obj(raw)
  const overall = obj(v.overall)
  const counts = obj(v.counts)
  return {
    mode: v.mode === 'demo' ? 'demo' : 'live',
    generated_at: str(v.generated_at) ?? '',
    today: str(v.today) ?? '',
    overall: {
      level: oneOf(overall.level, ['red', 'yellow', 'green'] as const) ?? 'yellow',
      title: str(overall.title) ?? '',
      message: str(overall.message) ?? '',
      unknown_note: str(overall.unknown_note),
    },
    counts: {
      red: num(counts.red) ?? 0,
      yellow: num(counts.yellow) ?? 0,
      unknown: num(counts.unknown) ?? 0,
      green: num(counts.green) ?? 0,
    },
    results: list(v.results).map(normRule),
    request_message: str(v.request_message),
    special_terms: strList(v.special_terms),
    checklist: list(v.checklist).map(normChecklistItem),
    disclaimer: str(v.disclaimer) ?? '',
  }
}
