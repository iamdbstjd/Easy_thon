// ?mock=1일 때 src/api/client.ts가 백엔드 대신 부르는 가짜 API.
// 이 파일은 동적 import로만 불러서, 평소에는 내려받지도 않는다.
//
// 추가 주소 옵션 (개발용)
// - mockError=AI_FAILED (또는 BUSY, NOT_REGISTRY 등): /api/extract와 /api/extract/contract가 그 오류를 낸다
// - mockErrorDoc=contract (또는 registry): 위 오류에 어느 서류 때문인지 붙인다 (/api/extract/contract는 늘 contract)
// - mockExtractMs=95000: /api/extract 응답을 그만큼 늦춘다 (90초 시간 초과 화면 확인용)
// - mockCheckMs=3000: /api/check 응답을 그만큼 늦춘다 (기본 700ms)

import { ApiError } from '../api/errors'
import type {
  CheckRequest,
  CompareReport,
  CompareRequest,
  ContractChange,
  ContractExtract,
  Level,
  RequestFulfillment,
  RuleChange,
  RuleDelta,
  RecheckChange,
  RecheckReport,
  RecheckRequest,
  TermCheck,
  DemoScenario,
  ErrorCode,
  ExtractResponse,
  BuildingInsight,
  HealthResponse,
  IcsRequest,
  MarketInsight,
  Report,
} from '../api/types'
import { formatDate, formatWon } from '../lib/format'
import { ruleNumber } from '../content/labels'
import {
  amendmentText,
  C_REVISED_CONTRACT,
  DISCLAIMER,
  REPORT_C_AFTER,
  REQUEST_COMPARE_C,
  REQUEST_RECHECK_A,
  REPORT_A,
  REPORT_A_INCOMPLETE,
  REPORT_B,
  REPORT_C,
  REQUEST_A,
  REQUEST_B,
  REQUEST_C,
} from './scenarios'

const params = new URLSearchParams(window.location.search)

const ERROR_TEXT: Record<ErrorCode, string> = {
  UNSUPPORTED_FILE: 'PDF나 사진(JPG·PNG)만, 파일 하나 10MB·서류마다 30쪽 이하로 올릴 수 있어요.',
  NOT_REGISTRY: '등기부등본이 아닌 것 같아요. 인터넷등기소에서 받은 PDF를 올려주세요.',
  LAND_REGISTRY: '토지 등기부예요. 건물(또는 집합건물) 등기부를 올려주세요.',
  NOT_CONTRACT: '임대차 계약서가 아닌 것 같아요.',
  AI_FAILED: '문서를 읽지 못했어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.',
  BUSY: '지금 서류를 읽는 사람이 많아요. 잠시 후 다시 시도해 주세요.',
  NOT_FOUND: '예시 데이터를 찾지 못했어요. 예시는 A, B, C예요.',
  INVALID_REQUEST: '요청을 처리하지 못했어요. 페이지를 새로 고친 뒤 다시 시도해 주세요.',
  INTERNAL_ERROR: '일시적인 오류가 생겼어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.',
}

// backend/app/errors.py의 HTTP 상태
const ERROR_STATUS: Record<ErrorCode, number> = {
  UNSUPPORTED_FILE: 400,
  NOT_REGISTRY: 422,
  LAND_REGISTRY: 422,
  NOT_CONTRACT: 422,
  AI_FAILED: 502,
  BUSY: 503,
  NOT_FOUND: 404,
  INVALID_REQUEST: 400,
  INTERNAL_ERROR: 500,
}

const REQUESTS: Record<DemoScenario, CheckRequest> = { A: REQUEST_A, B: REQUEST_B, C: REQUEST_C }
const REPORTS: Record<DemoScenario, Report> = { A: REPORT_A, B: REPORT_B, C: REPORT_C }

// 마지막으로 불러온 시나리오의 리포트를 돌려준다 (가짜 API라 규칙 계산은 하지 않는다).
let lastScenario: DemoScenario = 'C'

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abortError = () => signal?.reason ?? new DOMException('Aborted', 'AbortError')
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    const onAbort = () => {
      window.clearTimeout(timer)
      reject(abortError())
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/** 주소의 mockError로 오류를 낸다. 파일·문서 오류에는 어느 서류인지 붙인다 */
function throwMockError(doc: string | null) {
  const code = params.get('mockError') as ErrorCode | null
  if (!code || !(code in ERROR_TEXT)) return
  const fileError = ['UNSUPPORTED_FILE', 'NOT_REGISTRY', 'LAND_REGISTRY', 'NOT_CONTRACT'].includes(code)
  const document = fileError && (doc === 'registry' || doc === 'contract') ? doc : null
  throw new ApiError(ERROR_TEXT[code], code, ERROR_STATUS[code], document)
}

export async function health(signal?: AbortSignal): Promise<HealthResponse> {
  await wait(50, signal)
  return { ai_ready: true, public_api_ready: true }
}

export async function extract(
  _registry: File[],
  contract: File[],
  signal?: AbortSignal,
): Promise<ExtractResponse> {
  const delay = Number(params.get('mockExtractMs') ?? '') || 4000
  await wait(delay, signal)
  throwMockError(params.get('mockErrorDoc'))

  lastScenario = 'C'
  const source = structuredClone(REQUEST_C)
  return {
    registry: { ...source.registry, unreadable: ['2쪽 오른쪽 아래 도장 부분이 흐려서 일부를 읽지 못했어요.'] },
    contract: contract.length > 0 ? source.contract : null,
  }
}

export async function check(req: CheckRequest, signal?: AbortSignal): Promise<Report> {
  await wait(Number(params.get('mockCheckMs') ?? '') || 700, signal)
  // 시나리오 A에서 임대인 이름을 모두 지우면 "확인이 끝나지 않았어요" 리포트를 돌려준다.
  const noLandlord =
    (req.contract === null || req.contract.landlord_names.length === 0) && !req.manual.landlord_name
  return reportFor(req, noLandlord)
}

/** 가짜 검사: 마지막 시나리오의 리포트. C에서 임대인이 신탁회사로 고쳐져 있으면 고친 뒤 리포트 */
function reportFor(req: CheckRequest, noLandlord = false): Report {
  const revisedC = lastScenario === 'C' && req.contract?.landlord_names.includes('○○부동산신탁(주)')
  const source =
    lastScenario === 'A' && noLandlord ? REPORT_A_INCOMPLETE : revisedC ? REPORT_C_AFTER : REPORTS[lastScenario]
  const report = structuredClone(source)
  if (req.contract === null) withoutContract(report, req)
  return { ...report, mode: req.mode, today: req.today ?? report.today }
}

/** 계약서 없이 검사했을 때: 대조표 계약서 칸은 직접 입력한 값, 없으면 null (화면 "—"). 요청서는 "계약 전 요청서" */
function withoutContract(report: Report, req: CheckRequest) {
  const m = req.manual
  const manualValue: Record<string, string | null> = {
    R1: m.landlord_name,
    R5: m.deposit !== null ? formatWon(m.deposit) : null,
    R8: m.contract_date ? formatDate(m.contract_date) : null,
  }
  report.comparison = report.comparison.map((row) => {
    const value = manualValue[row.rule_id] ?? null
    if (value) return { ...row, contract: value }
    return { ...row, contract: null, level: 'unknown', note: '확인 못 함' }
  })
  if (report.amendment) {
    const base = { ...report.amendment, title: '계약 전 요청서', fixes: [] }
    const address = req.registry.address_road ?? req.registry.address_jibun ?? '계약하려는 집'
    report.amendment = { ...base, text: amendmentText(base, address, '2026년 11월 14일') }
  }
}

export async function demo(scenario: DemoScenario, signal?: AbortSignal): Promise<CheckRequest> {
  await wait(250, signal)
  lastScenario = scenario
  return structuredClone(REQUESTS[scenario])
}

function icsDate(iso: string): string {
  return iso.replaceAll('-', '')
}

export async function checklistIcs(body: IcsRequest): Promise<Blob> {
  await wait(200)
  const events = body.checklist
    .filter((item) => item.date)
    .map((item, i) =>
      [
        'BEGIN:VEVENT',
        `UID:mock-${i}@deposit-guard.local`,
        'DTSTAMP:20261114T000000Z',
        `DTSTART;VALUE=DATE:${icsDate(item.date ?? '')}`,
        `SUMMARY:${item.when}: ${item.title}`,
        ...(body.address ? [`LOCATION:${body.address}`] : []),
        'END:VEVENT',
      ].join('\r\n'),
    )
  const text = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//deposit-guard//mock//KO', ...events, 'END:VCALENDAR', ''].join('\r\n')
  return new Blob([text], { type: 'text/calendar' })
}

// ---------------------------------------------------------------------------
// 계약 후 재확인 (가짜 API): 서버 판정 규칙을 간단히 흉내 낸다
// ---------------------------------------------------------------------------

export async function demoRecheck(signal?: AbortSignal): Promise<RecheckRequest> {
  await wait(250, signal)
  return structuredClone(REQUEST_RECHECK_A)
}

export async function recheck(req: RecheckRequest, signal?: AbortSignal): Promise<RecheckReport> {
  await wait(Number(params.get('mockCheckMs') ?? '') || 700, signal)
  const c = req.contract
  const today = req.today ?? '2026-11-14'
  const viewed = req.baseline_viewed_at ? req.baseline_viewed_at.slice(0, 10) : null
  const baseline = [c.contract_date, viewed].filter((d): d is string => !!d).sort()[0] ?? null
  const balance = c.balance_date
  const phase: RecheckReport['phase'] =
    !balance || today < balance ? 'before_balance' : today === balance ? 'balance_day' : 'after_move_in'

  const entries = [
    ...req.registry.gapgu.map((e) => ({ e, section: 'gapgu' as const })),
    ...req.registry.eulgu.map((e) => ({ e, section: 'eulgu' as const })),
  ].filter(({ e }) => !e.is_cancelled && baseline && (!e.received_at || e.received_at >= baseline))
  const changes: RecheckChange[] = entries.map(({ e, section }) => {
    const sameDay = e.received_at === baseline
    return {
      section,
      rank: e.rank,
      purpose: e.purpose,
      received_at: e.received_at,
      holders: e.holders,
      amount: e.amount,
      // 접수일을 읽지 못하면 계약 후에 생긴 것인지 알 수 없다
      level: !e.received_at ? 'unknown' : sameDay ? 'yellow' : 'red',
      note: !e.received_at
        ? '접수일을 읽지 못해 계약 후에 생긴 것인지 알 수 없어요'
        : sameDay
          ? '계약 당일 접수: 계약 때 본 등기부에 있었는지 확인하세요'
          : '계약 후 새로 생김',
      page: e.page,
      source_text: e.source_text,
    }
  })
  const newMortgage = changes.some((ch) => ch.level === 'red' && ch.purpose.includes('저당'))
  // 보증금을 지키는 특약(담보 설정 금지)만 본다. 기준일을 모르면 점검하지 않는다
  const termChecks: TermCheck[] = baseline
    ? c.special_terms
        .filter((term) => /담보|저당|설정하지/.test(term))
        .map((term) =>
          newMortgage
            ? { term, status: '위반', level: 'red', note: '계약 후 2026년 11월 27일에 근저당권(채권최고액 1억 2,000만 원)이 새로 설정됐어요.' }
            : { term, status: '이행', level: 'green', note: '계약 후 새로 설정된 담보가 없어요' },
        )
    : []
  const reds = changes.filter((ch) => ch.level === 'red').length + termChecks.filter((t) => t.level === 'red').length
  const yellows = changes.filter((ch) => ch.level === 'yellow').length
  const unread = changes.filter((ch) => ch.level === 'unknown').length
  const afterMoveIn = phase === 'after_move_in'
  // 모르면 "없음"이라고 말하지 않는다 (확인 미완료)
  const overall: RecheckReport['overall'] = !baseline
    ? {
        level: 'yellow',
        title: '확인 미완료',
        message: '계약일을 확인하지 못해 계약 후 새로 생긴 권리를 가려내지 못했어요. 계약일을 확인한 뒤 다시 확인하세요.',
        unknown_note: null,
      }
    : reds > 0
      ? {
          level: 'red',
          title: afterMoveIn ? '보증금 보호 확인 필요' : '잔금 보류 권장',
          message: `계약 뒤에 새로 생긴 권리가 ${changes.length}건 있어요. 해결되기 전에는 잔금을 미루는 걸 권해요.`,
          unknown_note: null,
        }
      : yellows > 0
        ? { level: 'yellow', title: '추가 확인 필요', message: `계약 전후로 확인할 것이 ${yellows}건 있어요.`, unknown_note: null }
        : unread > 0
          ? {
              level: 'yellow',
              title: '확인 미완료',
              message: `새로 생긴 권리는 찾지 못했지만, 접수일을 읽지 못한 항목 ${unread}건을 확인하지 못했어요. 등기부 원문에서 날짜를 확인하세요.`,
              unknown_note: `확인하지 못한 항목 ${unread}개`,
            }
          : {
              level: 'green',
              title: '새로 생긴 권리 없음',
              message: '계약일 이후 새로 접수된 권리를 찾지 못했어요. 안전을 보장하는 것은 아니니 아래 할 일은 꼭 챙기세요.',
              unknown_note: null,
            }
  const actions: string[] = []
  if (reds > 0 && !afterMoveIn) actions.push('잔금을 보내기 전에 임대인에게 말소를 요구하고, 해결되기 전에는 잔금을 미루세요.')
  if (termChecks.some((x) => x.status === '위반')) {
    actions.push('계약서 특약(담보 설정 금지)에 어긋나요. 공인중개사·대한법률구조공단(국번 없이 132)과 상의해 대응하세요.')
  }
  if (reds > 0 && afterMoveIn) actions.push('전입신고·확정일자를 받았는지 확인하고, 대한법률구조공단이나 전세피해지원센터에 상담하세요.')
  if (!baseline) actions.push('계약서의 계약일을 확인한 뒤 다시 확인하세요.')
  if (actions.length === 0) {
    actions.push(
      afterMoveIn
        ? '전입신고 다음 날에도 한 번 더 확인하세요.'
        : '잔금 보내기 직전에 한 번 더 떼어 보고, 입주 당일 전입신고와 확정일자를 받으세요.',
    )
  }
  if (unread > 0) actions.push('접수일을 읽지 못한 항목은 등기부 원문에서 날짜를 직접 확인하세요.')
  return {
    mode: req.mode,
    generated_at: `${today}T09:10:00+09:00`,
    today,
    phase,
    baseline_date: baseline,
    contract_date: c.contract_date,
    balance_date: c.balance_date,
    move_in_date: c.move_in_date,
    address: c.address,
    overall,
    changes,
    term_checks: termChecks,
    actions,
    disclaimer: DISCLAIMER,
  }
}

// ---------------------------------------------------------------------------
// 수정 전·후 비교 (가짜 API): 비교 규칙을 간단히 흉내 낸다
// ---------------------------------------------------------------------------

/** 계약서 하나만 읽기. C에서는 요청서대로 고친 계약서를, 그 밖에는 원래 계약서를 돌려준다 */
export async function extractContract(_contract: File[], signal?: AbortSignal): Promise<ContractExtract> {
  await wait(Number(params.get('mockExtractMs') ?? '') || 3000, signal)
  throwMockError('contract')
  if (lastScenario === 'C') return structuredClone(C_REVISED_CONTRACT)
  return structuredClone(REQUESTS[lastScenario].contract as ContractExtract)
}

/** 건축물대장 (가짜): 다세대 302호. ?mockBuilding=none이면 불러오지 못함 */
export async function building(req: CheckRequest, signal?: AbortSignal): Promise<BuildingInsight> {
  await wait(500, signal)
  if (params.get('mockBuilding') === 'none' || req.mode === 'demo') {
    return { status: 'unavailable', message: '지금은 건축물대장을 불러오지 못했어요.', building: null, name: null,
      use_approval_date: null, households: null, families: null, units: null, notes: [] }
  }
  return {
    status: 'ok',
    message: null,
    building: { main_use: '공동주택(다세대주택)', unit_use: '공동주택(다세대주택)', is_violating: null, source: 'api',
      source_text: '건축물대장(국토교통부) 302호 전유부 용도: 공동주택(다세대주택)' },
    name: '○○파크빌',
    use_approval_date: '2015-03-20',
    households: 8,
    families: null,
    units: 8,
    notes: ['공개 건축물대장 자료에는 위반건축물 표시가 없어요. 정부24나 세움터에서 건축물대장을 떼어 확인하세요.'],
  }
}

/** 실거래 (가짜): 같은 건물 매매 3건, 전세 2건. ?mockMarket=none이면 찾지 못함 */
export async function market(req: CheckRequest, signal?: AbortSignal): Promise<MarketInsight> {
  await wait(600, signal)
  if (params.get('mockMarket') === 'none' || req.mode === 'demo') {
    return { status: 'unavailable', message: '지금은 실거래 정보를 불러오지 못했어요.', housing_type: null,
      area_name: null, period: null, market: null, sale: null, jeonse: null, monthly_deposit: null,
      monthly_rent: null, deals: [], notes: [] }
  }
  const period = '2025-12 ~ 2026-11'
  const deal = (kind: 'sale' | 'jeonse', date: string, amount: number, floor: string) => ({
    kind, date, name: '○○파크빌', floor, area_m2: 59.5, same_building: true, contract_type: kind === 'sale' ? null : '신규',
    price: kind === 'sale' ? amount : null, deposit: kind === 'sale' ? null : amount, monthly_rent: kind === 'sale' ? null : 0,
  })
  return {
    status: 'ok',
    message: null,
    housing_type: '연립다세대',
    area_name: '용인시 수지구 죽전동',
    period,
    market: { price: 230_000_000, method: 'same_building', deals: 3, period },
    sale: { scope: 'same_building', similar_area: true, per_m2: false, period, count: 3, median: 230_000_000, low: 215_000_000, high: 240_000_000 },
    jeonse: { scope: 'same_building', similar_area: true, per_m2: false, period, count: 2, median: 160_000_000, low: 150_000_000, high: 170_000_000 },
    monthly_deposit: null,
    monthly_rent: null,
    deals: [
      deal('sale', '2026-10-20', 230_000_000, '2'),
      deal('sale', '2026-07-03', 240_000_000, '4'),
      deal('sale', '2026-02-11', 215_000_000, '1'),
      deal('jeonse', '2026-09-28', 170_000_000, '3'),
      deal('jeonse', '2026-03-15', 150_000_000, '2'),
    ],
    notes: ['동·호수는 공개되지 않아 같은 건물 거래는 번지로 찾았어요.'],
  }
}

export async function demoCompare(signal?: AbortSignal): Promise<CompareRequest> {
  await wait(250, signal)
  lastScenario = 'C'
  return structuredClone(REQUEST_COMPARE_C)
}

const SEVERITY: Record<Level, number> = { red: 3, yellow: 2, unknown: 1, green: 0 }
const CHANGE_ORDER: Record<RuleChange, number> = { 개선: 0, 악화: 1, '확인 못 함': 2, 그대로: 3 }
// 특약 반영 여부를 볼 핵심어 (backend rules/compare.py와 같은 기준). 위에서부터 처음 맞는 묶음으로 특약 종류를 정한다
const TERM_KINDS: { label: string; words: string[] }[] = [
  { label: '신탁회사 동의서', words: ['동의서', '수탁자'] },
  { label: '근저당 말소', words: ['말소'] },
  { label: '반환보증 불가 시 무효', words: ['반환보증', '보증보험'] },
  { label: '납세증명서·확정일자 제시', words: ['납세증명서', '확정일자'] },
  { label: '담보 설정 금지', words: ['담보', '저당', '설정하지'] },
]
const FIX_RULE: Record<string, string> = { 임대인: 'R1', 소재지: 'R11' }
const FIX_DONE: Record<string, string> = {
  R1: '수정 후 임대인이 등기부상 소유자와 같아요',
  R11: '수정 후 소재지·호수가 등기부와 같아요',
}
const FIX_NOT_DONE: Record<string, string> = {
  'R1:red': '수정 후에도 임대인이 등기부상 소유자와 달라요',
  'R1:yellow': '수정 후에도 공동 소유자 모두의 동의를 계약서로 확인할 수 없어요',
  'R11:red': '수정 후에도 호수가 등기부와 달라요',
  'R11:yellow': '수정 후에도 주소가 등기부와 같은지 확인이 필요해요',
}
const NOTE_TERM_DONE = '수정 후 계약서 특약에 있어요'
const NOTE_TERM_MISSING = '수정 후 계약서 특약에 없어요'
const NOTE_TERM_ALREADY = '수정 전 계약서에도 있던 특약이라 새로 반영된 것은 아니에요'
const NOTE_DOCUMENT = '계약서로는 확인할 수 없어요. 받았는지 직접 확인하세요.'

function hasKind(clause: string, words: string[]): boolean {
  // 말소를 약속하는 문장의 "저당"은 담보 설정 금지가 아니다
  if (words.includes('설정하지')) return clause.includes('담보') || clause.includes('설정하지') || (clause.includes('저당') && !clause.includes('말소'))
  return words.some((w) => clause.includes(w))
}

export async function compare(req: CompareRequest, signal?: AbortSignal): Promise<CompareReport> {
  await wait(Number(params.get('mockCheckMs') ?? '') || 700, signal)
  if (!req.before.contract || !req.after.contract) {
    throw new ApiError('수정 전·후 모두 계약서가 있어야 비교할 수 있어요.', 'INVALID', 422)
  }
  const before = reportFor(req.before)
  const after = reportFor(req.after)
  const afterLevel = new Map(after.results.map((r) => [r.id, r]))
  const beforeKeys = new Set((req.before.contract?.special_terms ?? []).map((t) => t.replace(/\s+/g, '')))
  const afterTerms = req.after.contract?.special_terms ?? []

  const fulfillment: RequestFulfillment[] = []
  for (const fix of before.amendment?.fixes ?? []) {
    const rule = FIX_RULE[fix.item]
    const level = rule ? afterLevel.get(rule)?.level : undefined
    if (rule && level === 'green') fulfillment.push({ kind: 'fix', item: fix.item, label: fix.item, status: '반영', note: FIX_DONE[rule] })
    else fulfillment.push({ kind: 'fix', item: fix.item, label: fix.item, status: '미반영', note: FIX_NOT_DONE[`${rule}:${level}`] ?? '수정 후 결과를 확인하지 못했어요' })
  }
  for (const term of before.amendment?.terms ?? []) {
    const termKind = TERM_KINDS.find((k) => k.words.some((w) => term.includes(w)))
    const words = termKind?.words ?? []
    const matching = afterTerms.filter((t) => hasKind(t, words))
    const fresh = matching.filter((t) => !beforeKeys.has(t.replace(/\s+/g, '')))
    const [status, note] = fresh.length ? (['반영', NOTE_TERM_DONE] as const) : matching.length ? (['미반영', NOTE_TERM_ALREADY] as const) : (['미반영', NOTE_TERM_MISSING] as const)
    fulfillment.push({ kind: 'term', item: term, label: termKind?.label ?? '추가 특약', status, note })
  }
  for (const doc of before.amendment?.documents ?? []) {
    fulfillment.push({ kind: 'document', item: doc, label: doc, status: '직접 확인', note: NOTE_DOCUMENT })
  }
  const counted = fulfillment.filter((f) => f.kind !== 'document')
  const rate = { done: counted.filter((f) => f.status === '반영').length, total: counted.length }

  const deltas: RuleDelta[] = before.results.map((b) => {
    const a = afterLevel.get(b.id) ?? b
    // 판단하지 못하게 된 것은 개선·악화가 아니라 "확인 못 함"이다
    const change: RuleChange =
      a.level === 'unknown' && b.level !== 'unknown'
        ? '확인 못 함'
        : SEVERITY[a.level] < SEVERITY[b.level]
          ? '개선'
          : SEVERITY[a.level] > SEVERITY[b.level]
            ? '악화'
            : '그대로'
    return {
      id: b.id,
      name: b.name,
      before: b.level,
      after: a.level,
      change,
      after_title: a.level === 'red' || a.level === 'yellow' ? a.title : '',
    }
  })
  deltas.sort((x, y) => CHANGE_ORDER[x.change] - CHANGE_ORDER[y.change] || ruleNumber(x.id) - ruleNumber(y.id))

  const b = req.before.contract
  const a = req.after.contract
  const changes: ContractChange[] = []
  const field = (name: string, x: string | null | undefined, y: string | null | undefined) => {
    if ((x ?? null) !== (y ?? null)) changes.push({ field: name, before: x ?? null, after: y ?? null })
  }
  const unit = (c: ContractExtract | null) => (c ? [c.unit.dong, c.unit.ho].filter(Boolean).join(' ') || null : null)
  const won = (n: number | null | undefined) => (n === null || n === undefined ? null : formatWon(n))
  field('임대인', b?.landlord_names.join(', '), a?.landlord_names.join(', '))
  field('소재지', b?.address, a?.address)
  field('동·호', unit(b), unit(a))
  field('보증금', won(b?.deposit), won(a?.deposit))
  field('월세', won(b?.monthly_rent), won(a?.monthly_rent))
  field('계약일', b?.contract_date ? formatDate(b.contract_date) : null, a?.contract_date ? formatDate(a.contract_date) : null)
  field('잔금일', b?.balance_date ? formatDate(b.balance_date) : null, a?.balance_date ? formatDate(a.balance_date) : null)
  const beforeTerms = b?.special_terms ?? []
  for (const t of afterTerms.filter((t) => !beforeTerms.includes(t))) changes.push({ field: '특약 추가', before: null, after: t })
  for (const t of beforeTerms.filter((t) => !afterTerms.includes(t))) changes.push({ field: '특약 삭제', before: t, after: null })

  const parts: string[] = []
  if (before.counts.red || after.counts.red) parts.push(`위험 ${before.counts.red}건 → ${after.counts.red}건`)
  if (before.counts.yellow || after.counts.yellow) parts.push(`주의 ${before.counts.yellow}건 → ${after.counts.yellow}건`)
  if (rate.total) parts.push(`요청 ${rate.total}건 중 ${rate.done}건 반영`)

  return {
    mode: req.mode,
    generated_at: `${req.today ?? '2026-11-14'}T10:00:00+09:00`,
    today: req.today ?? req.before.today ?? '2026-11-14',
    address: a?.address ?? req.after.registry.address_road ?? null,
    before_overall: before.overall,
    after_overall: after.overall,
    before_counts: before.counts,
    after_counts: after.counts,
    rate,
    headline: parts.join(', '),
    fulfillment,
    rule_deltas: deltas,
    contract_changes: changes,
    disclaimer: DISCLAIMER,
  }
}
