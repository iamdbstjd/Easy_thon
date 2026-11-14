// 검토 결과를 글로 요약해 공유한다 (카톡·문자·메일). 서버에 저장하지 않고, 휴대폰 공유창이나 클립보드로만 보낸다.
// 이름이 섞일 수 있는 설명은 빼고 위험 신호의 제목만 넣는다. 주민등록번호·전화번호 모양은 가린다.

import type { MarketInsight, Report } from '../api/types'
import { LEVEL_LABEL, ruleNumber } from '../content/labels'
import { copyText } from './clipboard'
import { formatDate, formatWon } from './format'
import { maskPersonal } from './mask'

export const SHARE_TITLE = '보증금 위험 검토 결과'

export function buildShareText(
  report: Report,
  target: { address: string | null; baseDate: string } | null,
  market: MarketInsight | null,
  origin: string | null,
): string {
  const lines = ['[자취방 보증금 지킴이] 보증금 위험 검토 결과']
  if (target?.address) lines.push(`검토 대상: ${maskPersonal(target.address)}`)
  if (target?.baseDate) lines.push(`기준일: ${formatDate(target.baseDate)}`)
  lines.push(`종합 판정: ${report.overall.title}`)
  const { red, yellow, unknown } = report.counts
  lines.push(`위험 ${red}건 · 주의 ${yellow}건 · 확인 못 함 ${unknown}건`)
  const flagged = [...report.results]
    .filter((r) => r.level === 'red' || r.level === 'yellow')
    .sort((a, b) => (a.level === b.level ? ruleNumber(a.id) - ruleNumber(b.id) : a.level === 'red' ? -1 : 1))
  for (const r of flagged) lines.push(`- ${LEVEL_LABEL[r.level]}: ${maskPersonal(r.title || r.name)}`)
  if (market?.status === 'ok') {
    if (market.sale) lines.push(`시세(실거래 매매 중간값): ${formatWon(market.sale.median)}`)
    if (market.jeonse) lines.push(`주변 전세 보증금 중간값: ${formatWon(market.jeonse.median)}`)
  }
  lines.push('')
  lines.push('올린 서류와 공개 자료로 확인한 참고 정보예요. 법률 자문이 아니에요.')
  if (origin) lines.push(`직접 확인해 보기: ${origin}`)
  return lines.join('\n')
}

export type ShareResult = 'shared' | 'copied' | 'cancelled' | 'failed'

/** 휴대폰처럼 공유창이 있으면 공유창(카톡·문자·메일), 없으면 클립보드에 복사한다 */
export async function shareText(text: string): Promise<ShareResult> {
  if (typeof navigator.share === 'function') {
    try {
      await navigator.share({ title: SHARE_TITLE, text })
      return 'shared'
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return 'cancelled'
      // 공유창을 못 열면 복사로 대신한다
    }
  }
  return (await copyText(text)) ? 'copied' : 'failed'
}

/** 메일 앱을 바로 연다 (컴퓨터용). 본문은 받는 사람 없이 채워 둔다 */
export function mailtoHref(text: string): string {
  return `mailto:?subject=${encodeURIComponent(SHARE_TITLE)}&body=${encodeURIComponent(text)}`
}
