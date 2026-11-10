// ?mock=1일 때 src/api/client.ts가 백엔드 대신 부르는 가짜 API.
// 이 파일은 동적 import로만 불러서, 평소에는 내려받지도 않는다.
//
// 추가 주소 옵션 (개발용)
// - mockError=AI_FAILED (또는 NOT_REGISTRY 등): /api/extract가 그 오류를 낸다
// - mockExtractMs=95000: /api/extract 응답을 그만큼 늦춘다 (90초 시간 초과 화면 확인용)
// - mockCheckMs=3000: /api/check 응답을 그만큼 늦춘다 (기본 700ms)

import { ApiError } from '../api/errors'
import type {
  CheckRequest,
  DemoScenario,
  ErrorCode,
  ExtractResponse,
  HealthResponse,
  IcsRequest,
  Report,
} from '../api/types'
import { formatDate, formatWon } from '../lib/format'
import {
  amendmentText,
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
  UNSUPPORTED_FILE: '등기부는 PDF, 계약서는 사진이나 PDF로 10MB 이하만 올릴 수 있어요.',
  NOT_REGISTRY: '등기부등본이 아닌 것 같아요. 인터넷등기소에서 받은 PDF를 올려주세요.',
  LAND_REGISTRY: '토지 등기부예요. 건물(또는 집합건물) 등기부를 올려주세요.',
  NOT_CONTRACT: '임대차 계약서가 아닌 것 같아요.',
  AI_FAILED: '문서를 읽지 못했어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.',
  NOT_FOUND: '예시 데이터를 찾지 못했어요. 예시는 A, B, C예요.',
  INTERNAL_ERROR: '일시적인 오류가 생겼어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.',
}

// backend/app/errors.py의 HTTP 상태
const ERROR_STATUS: Record<ErrorCode, number> = {
  UNSUPPORTED_FILE: 400,
  NOT_REGISTRY: 422,
  LAND_REGISTRY: 422,
  NOT_CONTRACT: 422,
  AI_FAILED: 502,
  NOT_FOUND: 404,
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

export async function health(signal?: AbortSignal): Promise<HealthResponse> {
  await wait(50, signal)
  return { ai_ready: true, public_api_ready: true }
}

export async function extract(
  _registry: File,
  contract: File | null,
  signal?: AbortSignal,
): Promise<ExtractResponse> {
  const delay = Number(params.get('mockExtractMs') ?? '') || 4000
  await wait(delay, signal)
  const code = params.get('mockError') as ErrorCode | null
  if (code && code in ERROR_TEXT) throw new ApiError(ERROR_TEXT[code], code, ERROR_STATUS[code])

  lastScenario = 'C'
  const source = structuredClone(REQUEST_C)
  return {
    registry: { ...source.registry, unreadable: ['2쪽 오른쪽 아래 도장 부분이 흐려서 일부를 읽지 못했어요.'] },
    contract: contract ? source.contract : null,
  }
}

export async function check(req: CheckRequest, signal?: AbortSignal): Promise<Report> {
  await wait(Number(params.get('mockCheckMs') ?? '') || 700, signal)
  // 시나리오 A에서 임대인 이름을 모두 지우면 "확인이 끝나지 않았어요" 리포트를 돌려준다.
  const noLandlord =
    (req.contract === null || req.contract.landlord_names.length === 0) && !req.manual.landlord_name
  const source = lastScenario === 'A' && noLandlord ? REPORT_A_INCOMPLETE : REPORTS[lastScenario]
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
