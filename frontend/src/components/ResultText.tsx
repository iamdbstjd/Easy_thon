import type { Level } from '../api/types'
import { COUNT_LABEL } from '../content/labels'
import { maskIds } from '../lib/mask'

/**
 * 표의 결과·판정 칸.
 * 🔴·🟡: 등급 단어 + 결과 ("위험 불일치"). 🟢·⚪: 결과만 등급 색으로 ("일치", "확인 못 함").
 */
export function ResultText({ level, note }: { level: Level; note: string }) {
  const word = COUNT_LABEL[level]
  const text = maskIds(note.trim())
  if (level === 'red' || level === 'yellow') {
    return (
      <>
        <span className={`grade grade-${level}`}>{word}</span>
        {text && text !== word && ` ${text}`}
      </>
    )
  }
  return <span className={`grade-${level}`}>{text || word}</span>
}
