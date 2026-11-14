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

/**
 * 위험 신호 이름을 화면에 보일 때: 쉬운 말을 앞에, 공식 이름(등기·계약 용어)은 괄호에 둔다.
 * 이미 쉬운 이름(시세 대비 보증금 비율, 주소·호수 불일치, 보호 특약 없음, 오래된 등기부)은 그대로 쓴다.
 */
const RULE_LABEL: Record<string, string> = {
  R1: '집주인이 아닌 사람과 계약 (임대인·소유자 불일치)',
  R2: '신탁회사 소유 (신탁등기)',
  R3: '빚 때문에 묶인 집 (압류·경매)',
  R4: '전 세입자가 보증금을 못 받음 (임차권등기)',
  R6: '먼저 잡힌 빚 (근저당·전세권)',
  R7: '여러 세입자가 사는 건물 (다가구·단독)',
  R8: '최근 집주인이 바뀜 (소유권 변동)',
  R9: '불법으로 고친 건물 (위반건축물)',
  R10: '집이 아닌 용도 (근린생활시설 등)',
}

export function ruleLabel(id: string, name: string): string {
  return RULE_LABEL[id] ?? name
}

/** "R12" → 12. 같은 등급 안에서 규칙 ID 순서로 정렬할 때 쓴다. */
export function ruleNumber(id: string): number {
  const n = Number.parseInt(id.replace(/\D/g, ''), 10)
  return Number.isNaN(n) ? Number.MAX_SAFE_INTEGER : n
}
