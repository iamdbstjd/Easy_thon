import type { EvidenceDoc, Level, MarketMethod } from '../api/types'

/** 등급 글자 배지. 이모지는 쓰지 않는다. */
export const LEVEL_LABEL: Record<Level, string> = {
  red: '위험',
  yellow: '주의',
  green: '해당 없음',
  unknown: '확인 불가',
}

/** 검토서의 등급별 개수와 접힌 목록 제목 */
export const COUNT_LABEL: Record<Level, string> = {
  red: '위험',
  yellow: '주의',
  green: '해당 없음',
  unknown: '확인 못 함',
}

/** 근거 문서 이름 */
export const DOC_LABEL: Record<EvidenceDoc, string> = {
  registry: '등기부',
  contract: '계약서',
  building: '건축물대장',
  market: '시세',
  manual: '직접 입력',
}

/** 시세 추정 방법 */
export const MARKET_METHOD_LABEL: Record<MarketMethod, string> = {
  same_building: '같은 건물 매매 거래',
  same_dong: '같은 동 비슷한 집 매매 거래 (추정)',
  manual: '직접 입력',
}

/** 체크리스트 시점 순서 */
export const CHECKLIST_WHEN_ORDER = ['계약 전', '계약일', '잔금일', '입주일', '입주 후']

/** "R12" → 12. 같은 등급 안에서 규칙 ID 순서로 정렬할 때 쓴다. */
export function ruleNumber(id: string): number {
  const n = Number.parseInt(id.replace(/\D/g, ''), 10)
  return Number.isNaN(n) ? Number.MAX_SAFE_INTEGER : n
}
