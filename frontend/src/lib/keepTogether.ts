import { createElement } from 'react'
import type { ReactNode } from 'react'

// 지번("789-1"), 문서 번호("제2026-5678호"), 날짜("2026년 8월 26일")가 줄 끝에서 갈라지지 않게 묶는다.
const TOGETHER = /(\d+(?:-\d+)+|\d{4}년 \d{1,2}월 \d{1,2}일)/

/** 글 속의 번호·날짜를 줄바꿈 없는 묶음(span.nowrap)으로 감싼다. 화면 표시에만 쓴다. */
export function keepTogether(text: string): ReactNode[] {
  return text
    .split(TOGETHER)
    .map((part, i) => (i % 2 === 1 ? createElement('span', { key: i, className: 'nowrap' }, part) : part))
}
