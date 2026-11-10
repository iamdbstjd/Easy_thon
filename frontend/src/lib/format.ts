// 금액·날짜 표시 형식

const groupFormat = new Intl.NumberFormat('ko-KR')

/** 숫자에 천 단위 쉼표를 넣는다. 12345 → "12,345" */
export function groupNumber(n: number): string {
  return groupFormat.format(n)
}

/** 숫자 문자열에 천 단위 쉼표를 넣는다. "180000000" → "180,000,000" */
export function groupDigits(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/**
 * 원 단위 정수를 한국식 단위로 쓴다.
 * 120000000 → "1억 2,000만 원", 450000 → "45만 원", 12345678 → "1,234만 5,678원"
 */
export function formatWon(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return ''
  const sign = n < 0 ? '-' : ''
  let rest = Math.round(Math.abs(n))
  if (rest === 0) return '0원'
  const jo = Math.floor(rest / 1e12)
  rest %= 1e12
  const eok = Math.floor(rest / 1e8)
  rest %= 1e8
  const man = Math.floor(rest / 1e4)
  const won = rest % 1e4

  const parts: string[] = []
  if (jo) parts.push(`${groupNumber(jo)}조`)
  if (eok) parts.push(`${groupNumber(eok)}억`)
  if (man) parts.push(`${groupNumber(man)}만`)
  if (won) return sign + [...parts, `${groupNumber(won)}원`].join(' ')
  return `${sign}${parts.join(' ')} 원`
}

/** "180000000" 같은 숫자 문자열 → 숫자. 비어 있으면 null */
export function digitsToNumber(digits: string): number | null {
  if (digits === '') return null
  const n = Number(digits)
  return Number.isSafeInteger(n) ? n : null
}

/** 숫자 → 숫자 문자열. null이면 "" */
export function numberToDigits(n: number | null): string {
  return n === null ? '' : String(Math.round(n))
}

// ---------------------------------------------------------------------------
// 날짜
// ---------------------------------------------------------------------------

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})/

/** "2026-12-01" → "2026년 12월 1일", 요일을 붙이면 "2026년 12월 1일 (화)" */
export function formatDate(iso: string | null | undefined, withWeekday = false): string {
  if (!iso) return ''
  const m = DATE_RE.exec(iso)
  if (!m) return iso
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const text = `${y}년 ${mo}월 ${d}일`
  if (!withWeekday) return text
  const day = new Date(Date.UTC(y, mo - 1, d)).getUTCDay()
  return `${text} (${WEEKDAYS[day]})`
}

/** 표 안의 짧은 날짜: "2026-08-26" → "2026. 8. 26." */
export function formatDateShort(iso: string | null | undefined): string {
  if (!iso) return ''
  const m = DATE_RE.exec(iso)
  if (!m) return iso
  return `${Number(m[1])}. ${Number(m[2])}. ${Number(m[3])}.`
}

const DATETIME_RE =
  /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$/i
const KST_OFFSET_MS = 9 * 60 * 60 * 1000

/**
 * ISO 일시 → datetime-local 입력 값 "YYYY-MM-DDTHH:mm" (한국 시간 기준).
 * 시간대가 없는 값은 적힌 그대로 쓴다. 등기부 열람 일시는 한국 시간이기 때문이다.
 */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const m = DATETIME_RE.exec(iso.trim())
  if (!m) return ''
  const [, date, time, zone] = m
  if (!zone) return `${date}T${time ?? '00:00'}`
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return ''
  return new Date(ms + KST_OFFSET_MS).toISOString().slice(0, 16)
}

/** datetime-local 입력 값 "YYYY-MM-DDTHH:mm" → 한국 시간 ISO 일시 */
export function localInputToIso(value: string): string {
  return `${value}:00+09:00`
}

/** 조회 기간 표시. "2025-12 ~ 2026-11" → "2025년 12월 ~ 2026년 11월" */
export function formatPeriod(period: string): string {
  return period.replace(/(\d{4})-(\d{1,2})/g, (_, y: string, m: string) => `${y}년 ${Number(m)}월`)
}

/** 파일 크기 표시. 1234567 → "1.2MB" */
export function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  return `${Math.max(1, Math.round(bytes / 1024))}KB`
}

/** 면적 표시. 29.75 → "29.75㎡" */
export function formatArea(m2: number | null): string {
  if (m2 === null) return ''
  return `${groupFormat.format(m2)}㎡`
}
