// 서버에서 받은 JSON을 types.ts 형태로 맞춘다.
// - 빠진 필드는 schemas.py의 기본값으로 채운다.
// - schemas.py에 없는 필드는 버린다. 이 값을 그대로 /api/check로 돌려보내므로,
//   여기서 걸러 두면 extra="forbid" 때문에 요청이 거절되는 일이 없다.

import type {
  Amendment,
  CompareReport,
  CompareRequest,
  Counts,
  Overall,
  RecheckChange,
  RecheckReport,
  RecheckRequest,
  TermCheck,
  BuildingRegister,
  ComparisonRow,
  ChecklistItem,
  CheckRequest,
  ContractExtract,
  Evidence,
  EvidenceDoc,
  Entry,
  ExtractResponse,
  Level,
  ManualInput,
  MarketDeal,
  MarketInsight,
  MarketPrice,
  MarketStats,
  Report,
  RegistryExtract,
  RuleChange,
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

function normComparisonRow(raw: unknown): ComparisonRow {
  const v = obj(raw)
  return {
    item: str(v.item) ?? '',
    rule_id: str(v.rule_id) ?? '',
    contract: str(v.contract),
    registry: str(v.registry),
    level: oneOf<Level>(v.level, LEVELS) ?? 'unknown',
    note: str(v.note) ?? '',
  }
}

function normAmendment(raw: unknown): Amendment | null {
  if (raw === null || raw === undefined) return null
  const v = obj(raw)
  return {
    title: str(v.title) ?? '계약서 수정 요청서',
    fixes: list(v.fixes).map((f) => {
      const x = obj(f)
      return {
        item: str(x.item) ?? '',
        current: str(x.current),
        proposed: str(x.proposed) ?? '',
        reason: str(x.reason) ?? '',
      }
    }),
    terms: strList(v.terms),
    documents: strList(v.documents),
    text: str(v.text) ?? '',
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
    comparison: list(v.comparison).map(normComparisonRow),
    amendment: normAmendment(v.amendment),
    request_message: str(v.request_message),
    special_terms: strList(v.special_terms),
    checklist: list(v.checklist).map(normChecklistItem),
    disclaimer: str(v.disclaimer) ?? '',
  }
}

// ---------------------------------------------------------------------------
// 계약 후 재확인
// ---------------------------------------------------------------------------

/** 재확인 요청 (예시 데이터). 계약서가 없으면 재확인할 수 없으므로 null */
export function normRecheckRequest(raw: unknown): RecheckRequest | null {
  const v = obj(raw)
  const contract = normContract(v.contract)
  if (!contract) return null
  return {
    registry: normRegistry(v.registry),
    contract,
    baseline_viewed_at: str(v.baseline_viewed_at),
    today: str(v.today),
    mode: v.mode === 'demo' ? 'demo' : 'live',
  }
}

function normRecheckChange(raw: unknown): RecheckChange {
  const v = obj(raw)
  return {
    section: v.section === 'gapgu' ? 'gapgu' : 'eulgu',
    rank: str(v.rank) ?? '',
    purpose: str(v.purpose) ?? '',
    received_at: str(v.received_at),
    holders: strList(v.holders),
    amount: num(v.amount),
    level: oneOf<Level>(v.level, LEVELS) ?? 'unknown',
    note: str(v.note) ?? '',
    page: num(v.page),
    source_text: str(v.source_text) ?? '',
  }
}

function normTermCheck(raw: unknown): TermCheck {
  const v = obj(raw)
  return {
    term: str(v.term) ?? '',
    status: oneOf(v.status, ['위반', '미이행', '이행', '확인 필요'] as const) ?? '확인 필요',
    level: oneOf<Level>(v.level, LEVELS) ?? 'unknown',
    note: str(v.note) ?? '',
  }
}

export function normRecheckReport(raw: unknown): RecheckReport {
  const v = obj(raw)
  const overall = obj(v.overall)
  return {
    mode: v.mode === 'demo' ? 'demo' : 'live',
    generated_at: str(v.generated_at) ?? '',
    today: str(v.today) ?? '',
    phase: oneOf(v.phase, ['before_balance', 'balance_day', 'after_move_in'] as const) ?? 'before_balance',
    baseline_date: str(v.baseline_date),
    contract_date: str(v.contract_date),
    balance_date: str(v.balance_date),
    move_in_date: str(v.move_in_date),
    address: str(v.address),
    overall: {
      level: oneOf(overall.level, ['red', 'yellow', 'green'] as const) ?? 'yellow',
      title: str(overall.title) ?? '',
      message: str(overall.message) ?? '',
      unknown_note: str(overall.unknown_note),
    },
    changes: list(v.changes).map(normRecheckChange),
    term_checks: list(v.term_checks).map(normTermCheck),
    actions: strList(v.actions),
    disclaimer: str(v.disclaimer) ?? '',
  }
}

// ---------------------------------------------------------------------------
// 계약서 변경 추적
// ---------------------------------------------------------------------------

export function normCompareRequest(raw: unknown): CompareRequest {
  const v = obj(raw)
  return {
    before: normCheckRequest(v.before),
    after: normCheckRequest(v.after),
    today: str(v.today),
    mode: v.mode === 'demo' ? 'demo' : 'live',
  }
}

function normOverall(raw: unknown): Overall {
  const v = obj(raw)
  return {
    level: oneOf(v.level, ['red', 'yellow', 'green'] as const) ?? 'yellow',
    title: str(v.title) ?? '',
    message: str(v.message) ?? '',
    unknown_note: str(v.unknown_note),
  }
}

function normCounts(raw: unknown): Counts {
  const v = obj(raw)
  return {
    red: num(v.red) ?? 0,
    yellow: num(v.yellow) ?? 0,
    unknown: num(v.unknown) ?? 0,
    green: num(v.green) ?? 0,
  }
}

export function normCompareReport(raw: unknown): CompareReport {
  const v = obj(raw)
  const rate = obj(v.rate)
  return {
    mode: v.mode === 'demo' ? 'demo' : 'live',
    generated_at: str(v.generated_at) ?? '',
    today: str(v.today) ?? '',
    address: str(v.address),
    before_overall: normOverall(v.before_overall),
    after_overall: normOverall(v.after_overall),
    before_counts: normCounts(v.before_counts),
    after_counts: normCounts(v.after_counts),
    rate: { done: num(rate.done) ?? 0, total: num(rate.total) ?? 0 },
    headline: str(v.headline) ?? '',
    fulfillment: list(v.fulfillment).map((f) => {
      const x = obj(f)
      return {
        kind: oneOf(x.kind, ['fix', 'term', 'document'] as const) ?? 'term',
        item: str(x.item) ?? '',
        label: str(x.label) ?? '',
        status: oneOf(x.status, ['반영', '미반영', '직접 확인'] as const) ?? '직접 확인',
        note: str(x.note) ?? '',
      }
    }),
    rule_deltas: list(v.rule_deltas).map((d) => {
      const x = obj(d)
      const before = oneOf<Level>(x.before, LEVELS) ?? 'unknown'
      const after = oneOf<Level>(x.after, LEVELS) ?? 'unknown'
      const change = oneOf<RuleChange>(x.change, ['개선', '악화', '그대로', '확인 못 함']) ?? '그대로'
      return {
        id: str(x.id) ?? '',
        name: str(x.name) ?? '',
        before,
        after,
        // 판단하지 못하게 된 것은 개선·악화로 세지 않는다 (예전 서버는 위험 → 확인 못 함을 개선으로 보냈다)
        change: after === 'unknown' && before !== 'unknown' ? '확인 못 함' : change,
        after_title: str(x.after_title) ?? '',
      }
    }),
    contract_changes: list(v.contract_changes).map((c) => {
      const x = obj(c)
      return { field: str(x.field) ?? '', before: str(x.before), after: str(x.after) }
    }),
    disclaimer: str(v.disclaimer) ?? '',
  }
}

// ---------------------------------------------------------------------------
// /api/market
// ---------------------------------------------------------------------------

const SCOPES = ['same_building', 'same_dong'] as const
const HOUSING_TYPES = ['아파트', '연립다세대', '오피스텔', '단독다가구'] as const

function normMarketStats(raw: unknown): MarketStats | null {
  const v = obj(raw)
  const scope = oneOf(v.scope, SCOPES)
  const median = num(v.median)
  if (!scope || median === null) return null
  return {
    scope,
    similar_area: bool(v.similar_area, true),
    per_m2: bool(v.per_m2, false),
    period: str(v.period),
    count: num(v.count) ?? 0,
    median,
    low: num(v.low) ?? median,
    high: num(v.high) ?? median,
  }
}

function normMarketDeal(raw: unknown): MarketDeal | null {
  const v = obj(raw)
  const kind = oneOf(v.kind, ['sale', 'jeonse', 'monthly'] as const)
  const date = str(v.date)
  if (!kind || !date) return null
  return {
    kind,
    date,
    name: str(v.name),
    floor: str(v.floor),
    area_m2: num(v.area_m2),
    price: num(v.price),
    deposit: num(v.deposit),
    monthly_rent: num(v.monthly_rent),
    contract_type: str(v.contract_type),
    same_building: bool(v.same_building, false),
  }
}

/** 응답이 이상하면 "불러오지 못함"으로 본다 (검사는 그대로 진행한다) */
export function normMarketInsight(raw: unknown): MarketInsight {
  const v = obj(raw)
  return {
    status: oneOf(v.status, ['ok', 'no_deals', 'unavailable'] as const) ?? 'unavailable',
    message: str(v.message),
    housing_type: oneOf(v.housing_type, HOUSING_TYPES),
    area_name: str(v.area_name),
    period: str(v.period),
    market: normMarket(v.market),
    sale: normMarketStats(v.sale),
    jeonse: normMarketStats(v.jeonse),
    monthly_deposit: normMarketStats(v.monthly_deposit),
    monthly_rent: normMarketStats(v.monthly_rent),
    deals: list(v.deals)
      .map(normMarketDeal)
      .filter((d): d is MarketDeal => d !== null),
    notes: strList(v.notes),
  }
}
