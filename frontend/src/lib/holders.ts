import { createElement, Fragment } from 'react'
import type { ReactNode } from 'react'
import { maskPersonal } from './mask'

/** 권리자 이름 목록: 이름마다 줄바꿈 없이 묶고 ", "로 잇는다 ("○○ / 은행"처럼 갈라지지 않게). 가림 처리 포함 */
export function holderList(holders: string[]): ReactNode {
  return holders.map((name, i) =>
    createElement(
      Fragment,
      { key: i },
      i > 0 ? ', ' : null,
      createElement('span', { className: 'nowrap' }, maskPersonal(name)),
    ),
  )
}
