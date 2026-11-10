import type { Level } from '../api/types'
import { LEVEL_LABEL } from '../content/labels'

/**
 * 등급 표시: 색 글자만 쓴다 (위험·주의·해당 없음·확인 불가). 배경색 배지는 쓰지 않는다 (PRD 4.4, F6).
 * decorative: 같은 등급 글자를 제목 안에 따로 넣어 둔 경우, 화면 낭독기가 두 번 읽지 않게 숨긴다.
 */
export function Grade({ level, decorative = false }: { level: Level; decorative?: boolean }) {
  return (
    <span className={`grade grade-${level}`} aria-hidden={decorative || undefined}>
      {LEVEL_LABEL[level]}
    </span>
  )
}
