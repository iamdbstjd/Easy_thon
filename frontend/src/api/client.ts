// 백엔드 API 호출. 개발 서버는 /api를 http://127.0.0.1:8000으로 넘긴다 (vite.config.ts).
//
// 주소에 ?mock=1이 있을 때만 src/mocks의 가짜 데이터를 쓴다. 기본값은 항상 실제 백엔드다.

import { ApiError, ERROR_MESSAGES } from './errors'
import {
  normCheckRequest,
  normCompareReport,
  normCompareRequest,
  normContract,
  normExtractResponse,
  normMarketInsight,
  normRecheckReport,
  normRecheckRequest,
  normReport,
} from './normalize'
import type {
  ChecklistItem,
  CheckRequest,
  CompareReport,
  CompareRequest,
  ContractExtract,
  DemoScenario,
  ExtractResponse,
  HealthResponse,
  IcsRequest,
  MarketInsight,
  RecheckReport,
  RecheckRequest,
  Report,
} from './types'

export const IS_MOCK = new URLSearchParams(window.location.search).get('mock') === '1'

function loadMocks() {
  return import('../mocks/mockApi')
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    // 본문이 JSON이 아니다 (프록시 오류 등)
  }
  const detail = (body as { error?: { code?: unknown; message?: unknown; document?: unknown } } | null)?.error
  if (detail && typeof detail.message === 'string' && detail.message.trim() !== '') {
    const code = typeof detail.code === 'string' ? detail.code : null
    const document = detail.document === 'registry' || detail.document === 'contract' ? detail.document : null
    return new ApiError(detail.message, code, res.status, document)
  }
  // 서류를 읽는 요청이 몰렸다: 같은 파일로 다시 시도하면 된다
  if (detail?.code === 'BUSY') return new ApiError(ERROR_MESSAGES.busy, 'BUSY', res.status)
  if (res.status === 422) return new ApiError(ERROR_MESSAGES.invalid, 'INVALID', res.status)
  // Vite 프록시는 백엔드에 연결하지 못하면 502를 돌려준다.
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    return new ApiError(ERROR_MESSAGES.network, 'NETWORK', res.status)
  }
  return new ApiError(ERROR_MESSAGES.generic, null, res.status)
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch (err) {
    // 호출한 쪽이 취소했으면(시간 초과 포함) 그대로 올려 보낸다.
    if (init.signal?.aborted) throw err
    throw new ApiError(ERROR_MESSAGES.network, 'NETWORK')
  }
  if (!res.ok) throw await toApiError(res)
  return res
}

async function sendJson(path: string, init: RequestInit = {}): Promise<unknown> {
  const res = await send(path, init)
  try {
    return await res.json()
  } catch {
    throw new ApiError(ERROR_MESSAGES.generic, null, res.status)
  }
}

/** GET /api/health */
export async function health(signal?: AbortSignal): Promise<HealthResponse> {
  const data = IS_MOCK
    ? await (await loadMocks()).health(signal)
    : await sendJson('/api/health', { signal })
  const v = (data ?? {}) as Partial<HealthResponse>
  return { ai_ready: v.ai_ready === true, public_api_ready: v.public_api_ready === true }
}

/**
 * POST /api/extract (multipart: registry 필수, contract 선택).
 * 한 서류가 여러 파일이면 같은 필드 이름으로 올린 순서대로 붙인다. 서버가 한 서류로 이어서 읽는다.
 */
export async function extract(
  registry: File[],
  contract: File[] = [],
  signal?: AbortSignal,
): Promise<ExtractResponse> {
  let data: unknown
  if (IS_MOCK) {
    data = await (await loadMocks()).extract(registry, contract, signal)
  } else {
    const form = new FormData()
    for (const file of registry) form.append('registry', file, file.name)
    for (const file of contract) form.append('contract', file, file.name)
    data = await sendJson('/api/extract', { method: 'POST', body: form, signal })
  }
  return normExtractResponse(data)
}

/** POST /api/extract/contract: 계약서만 읽는다 (multipart 필드 contract, 여러 파일이면 올린 순서대로) */
export async function extractContract(contract: File[], signal?: AbortSignal): Promise<ContractExtract> {
  let data: unknown
  if (IS_MOCK) {
    data = await (await loadMocks()).extractContract(contract, signal)
  } else {
    const form = new FormData()
    for (const file of contract) form.append('contract', file, file.name)
    data = await sendJson('/api/extract/contract', { method: 'POST', body: form, signal })
  }
  const result = normContract(data)
  if (!result) throw new ApiError(
      '계약서를 읽지 못했어요. 계약서 사진이나 PDF를 다시 올려 주세요.',
      'NOT_CONTRACT',
      null,
      'contract',
    )
  return result
}

/** POST /api/compare: 수정 전·후 검사 입력 → 비교서 */
export async function compare(req: CompareRequest, signal?: AbortSignal): Promise<CompareReport> {
  // 서버도 422로 거절한다. 계약서 없이 검사한 결과는 비교할 수 없다
  if (!req.before.contract || !req.after.contract) {
    throw new ApiError('수정 전·후 모두 계약서가 있어야 비교할 수 있어요.', 'INVALID', 422)
  }
  const data = IS_MOCK
    ? await (await loadMocks()).compare(req, signal)
    : await sendJson('/api/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
        signal,
      })
  return normCompareReport(data)
}

/** GET /api/demo/compare-C (예시) → 비교 입력. 예시의 today·mode를 그대로 쓴다 */
export async function demoCompare(signal?: AbortSignal): Promise<CompareRequest> {
  const data = IS_MOCK
    ? await (await loadMocks()).demoCompare(signal)
    : await sendJson('/api/demo/compare-C', { signal })
  return normCompareRequest(data)
}

/**
 * POST /api/market: 등기부 주소로 국토교통부 실거래를 찾아 시세와 주변 보증금을 받는다 (AI를 부르지 않는다).
 * 실패해도 검사는 막지 않는다. 오류는 "불러오지 못함"으로 바꿔 돌려준다.
 */
export async function marketLookup(req: CheckRequest, signal?: AbortSignal): Promise<MarketInsight> {
  try {
    const data = IS_MOCK
      ? await (await loadMocks()).market(req, signal)
      : await sendJson('/api/market', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(req),
          signal,
        })
    return normMarketInsight(data)
  } catch (err) {
    if (signal?.aborted) throw err
    return normMarketInsight({ status: 'unavailable', message: '지금은 실거래 정보를 불러오지 못했어요.' })
  }
}

/** POST /api/check (JSON) → 리포트 */
export async function check(req: CheckRequest, signal?: AbortSignal): Promise<Report> {
  const data = IS_MOCK
    ? await (await loadMocks()).check(req, signal)
    : await sendJson('/api/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
        signal,
      })
  return normReport(data)
}

/** GET /api/demo/{scenario} → /api/check 입력 전체. 데모 경로이므로 mode는 항상 "demo"다. */
export async function demo(scenario: DemoScenario, signal?: AbortSignal): Promise<CheckRequest> {
  const data = IS_MOCK
    ? await (await loadMocks()).demo(scenario, signal)
    : await sendJson(`/api/demo/${scenario}`, { signal })
  return { ...normCheckRequest(data), mode: 'demo' }
}

/** POST /api/recheck: 오늘 뗀 등기부를 계약서와 맞춰 본다 */
export async function recheck(req: RecheckRequest, signal?: AbortSignal): Promise<RecheckReport> {
  const data = IS_MOCK
    ? await (await loadMocks()).recheck(req, signal)
    : await sendJson('/api/recheck', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
        signal,
      })
  return normRecheckReport(data)
}

/** GET /api/demo/recheck-A: 재확인 예시 (A 집, 잔금 이틀 전 근저당). 예시의 today·mode를 그대로 쓴다 */
export async function demoRecheck(signal?: AbortSignal): Promise<RecheckRequest> {
  const data = IS_MOCK
    ? await (await loadMocks()).demoRecheck(signal)
    : await sendJson('/api/demo/recheck-A', { signal })
  const req = normRecheckRequest(data)
  if (!req) throw new ApiError(ERROR_MESSAGES.generic, null)
  return req
}

/** POST /api/checklist.ics → 받은 .ics 파일을 내려받게 한다. */
export async function checklistIcs(
  checklist: ChecklistItem[],
  address: string | null,
): Promise<void> {
  const body: IcsRequest = {
    checklist: checklist.map(({ when, date, title }) => ({ when, date, title })),
    address,
  }
  if (IS_MOCK) {
    downloadBlob(await (await loadMocks()).checklistIcs(body), 'checklist.ics')
    return
  }
  const res = await send('/api/checklist.ics', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const blob = await res.blob()
  const name = filenameFromDisposition(res.headers.get('Content-Disposition')) ?? 'checklist.ics'
  downloadBlob(blob.type ? blob : new Blob([blob], { type: 'text/calendar' }), name)
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header)
  if (star) {
    try {
      return decodeURIComponent(star[1].trim())
    } catch {
      // 잘못된 인코딩이면 아래의 일반 filename을 쓴다
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/.exec(header)
  return plain ? plain[1].trim() : null
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
