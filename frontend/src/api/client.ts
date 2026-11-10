// 백엔드 API 호출 (PRD 9장). 개발 서버는 /api를 http://127.0.0.1:8000으로 넘긴다 (vite.config.ts).
//
// 주소에 ?mock=1이 있을 때만 src/mocks의 가짜 데이터를 쓴다. 기본값은 항상 실제 백엔드다.

import { ApiError, ERROR_MESSAGES } from './errors'
import { normCheckRequest, normExtractResponse, normReport } from './normalize'
import type {
  ChecklistItem,
  CheckRequest,
  DemoScenario,
  ExtractResponse,
  HealthResponse,
  IcsRequest,
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
  const detail = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error
  if (detail && typeof detail.message === 'string' && detail.message.trim() !== '') {
    const code = typeof detail.code === 'string' ? detail.code : null
    return new ApiError(detail.message, code, res.status)
  }
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

/** POST /api/extract (multipart: registry 필수, contract 선택) */
export async function extract(
  registry: File,
  contract?: File | null,
  signal?: AbortSignal,
): Promise<ExtractResponse> {
  let data: unknown
  if (IS_MOCK) {
    data = await (await loadMocks()).extract(registry, contract ?? null, signal)
  } else {
    const form = new FormData()
    form.append('registry', registry, registry.name)
    if (contract) form.append('contract', contract, contract.name)
    data = await sendJson('/api/extract', { method: 'POST', body: form, signal })
  }
  return normExtractResponse(data)
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
