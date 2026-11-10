// backend/app/schemas.py를 그대로 옮긴 타입. 필드 이름과 타입은 schemas.py가 기준이다.
// 백엔드는 모르는 필드가 오면 요청을 거절한다(extra="forbid"). 여기 없는 필드는 보내지 않는다.
//
// - 날짜(date): "YYYY-MM-DD" 문자열
// - 일시(datetime): ISO 8601 문자열 (예: "2026-11-14T10:31:00+09:00")
// - 값이 없을 수 있는 필드: `| null`

/** "YYYY-MM-DD" */
export type ISODate = string
/** ISO 8601 일시 */
export type ISODateTime = string

export type Level = 'red' | 'yellow' | 'green' | 'unknown'
export type OverallLevel = 'red' | 'yellow' | 'green'
export type Mode = 'live' | 'demo'

// ---------------------------------------------------------------------------
// 8.1 등기부 추출
// ---------------------------------------------------------------------------

/** 갑구·을구의 한 항목 */
export interface Entry {
  /** 순위번호 (예: "3", "3-1") */
  rank: string
  /** 등기목적 원문 (예: 소유권이전, 근저당권설정, 가압류) */
  purpose: string
  /** 접수일 */
  received_at: ISODate | null
  /** 등기원인 (예: 매매, 신탁, 임차권등기명령) */
  cause: string | null
  /** 권리자 이름 (역할어 제외) */
  holders: string[]
  /** 채권최고액·전세금·임차보증금 (원) */
  amount: number | null
  /** 말소 표시 여부 */
  is_cancelled: boolean
  /** 페이지 번호 */
  page: number | null
  /** 원문 그대로 */
  source_text: string
}

/** 전유부분 (집합건물의 내 호실) */
export interface RegistryUnit {
  dong: string | null
  ho: string | null
  floor: string | null
  area_m2: number | null
}

export type RegistryType = '집합건물' | '건물' | '토지'

export interface RegistryExtract {
  is_registry: boolean
  registry_type: RegistryType | null
  viewed_at: ISODateTime | null
  address_jibun: string | null
  address_road: string | null
  building_name: string | null
  unit: RegistryUnit
  building_use_lines: string[]
  gapgu: Entry[]
  eulgu: Entry[]
  unreadable: string[]
}

// ---------------------------------------------------------------------------
// 8.2 계약서 추출
// ---------------------------------------------------------------------------

export interface ContractUnit {
  dong: string | null
  ho: string | null
}

/** 주요 값의 근거 원문 */
export interface ContractSources {
  landlord: string | null
  address: string | null
  deposit: string | null
  special_terms: string | null
}

export type LeaseType = '전세' | '월세'

export interface ContractExtract {
  is_contract: boolean
  landlord_names: string[]
  agent_name: string | null
  address: string | null
  unit: ContractUnit
  lease_type: LeaseType | null
  deposit: number | null
  monthly_rent: number | null
  contract_date: ISODate | null
  balance_date: ISODate | null
  move_in_date: ISODate | null
  lease_end: ISODate | null
  special_terms: string[]
  sources: ContractSources
}

// ---------------------------------------------------------------------------
// 8.3 건축물대장 (P1) / 8.4 시세 (P1) / 8.5 직접 입력
// ---------------------------------------------------------------------------

export interface BuildingRegister {
  main_use: string | null
  unit_use: string | null
  is_violating: boolean | null
  source: 'api' | 'pdf'
  source_text: string | null
}

export type MarketMethod = 'same_building' | 'same_dong' | 'manual'

export interface MarketPrice {
  price: number | null
  method: MarketMethod
  deals: number
  period: string | null
}

export interface ManualInput {
  deposit: number | null
  monthly_rent: number | null
  contract_date: ISODate | null
  landlord_name: string | null
  prior_deposits: number | null
  market_price: number | null
}

// ---------------------------------------------------------------------------
// 9장 /api/check 입력
// ---------------------------------------------------------------------------

export interface CheckRequest {
  registry: RegistryExtract
  contract: ContractExtract | null
  manual: ManualInput
  building: BuildingRegister | null
  market: MarketPrice | null
  /** 없으면 서버가 현재 한국 날짜로 채운다 */
  today: ISODate | null
  mode: Mode
}

// ---------------------------------------------------------------------------
// 8.6 리포트
// ---------------------------------------------------------------------------

export type EvidenceDoc = 'registry' | 'contract' | 'building' | 'market' | 'manual'

export interface Evidence {
  doc: EvidenceDoc
  page: number | null
  text: string
}

export interface RuleResult {
  /** "R1" ~ "R13" */
  id: string
  /** 규칙 이름 (RULE_NAMES) */
  name: string
  level: Level
  title: string
  summary: string
  action: string
  evidence: Evidence[]
  unknown_reason: string | null
}

export interface Overall {
  level: OverallLevel
  title: string
  message: string
  unknown_note: string | null
}

export interface Counts {
  red: number
  yellow: number
  unknown: number
  green: number
}

export interface ChecklistItem {
  /** "계약 전" · "계약일" · "잔금일" · "입주일" · "입주 후" */
  when: string
  date: ISODate | null
  title: string
}

export interface Report {
  mode: Mode
  generated_at: ISODateTime
  today: ISODate
  overall: Overall
  counts: Counts
  results: RuleResult[]
  request_message: string | null
  special_terms: string[]
  checklist: ChecklistItem[]
  disclaimer: string
}

// ---------------------------------------------------------------------------
// 9장 기타 응답과 오류
// ---------------------------------------------------------------------------

export interface ExtractResponse {
  registry: RegistryExtract
  contract: ContractExtract | null
}

export interface HealthResponse {
  ai_ready: boolean
  public_api_ready: boolean
}

/** /api/checklist.ics 입력 */
export interface IcsRequest {
  checklist: ChecklistItem[]
  address: string | null
}

export type ErrorCode =
  | 'UNSUPPORTED_FILE'
  | 'NOT_REGISTRY'
  | 'LAND_REGISTRY'
  | 'NOT_CONTRACT'
  | 'AI_FAILED'
  | 'NOT_FOUND'
  | 'INTERNAL_ERROR'

export interface ErrorDetail {
  code: ErrorCode
  message: string
}

export interface ErrorResponse {
  error: ErrorDetail
}

/** 규칙 ID와 이름 */
export const RULE_NAMES: Record<string, string> = {
  R1: '임대인·소유자 불일치',
  R2: '신탁등기',
  R3: '압류·경매 등 제한',
  R4: '임차권등기',
  R5: '시세 대비 보증금 비율',
  R6: '먼저 잡힌 담보·전세권',
  R7: '다가구·단독',
  R8: '최근 소유권 변동',
  R9: '위반건축물',
  R10: '주거용이 아닌 용도',
  R11: '주소·호수 불일치',
  R12: '보호 특약 없음',
  R13: '오래된 등기부',
}

export type DemoScenario = 'A' | 'B' | 'C'
