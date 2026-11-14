import type { MouseEvent } from 'react'
import { IS_MOCK } from '../api/client'
import logo from '../assets/logo.png'

/**
 * 머리글: 왼쪽에 서비스 로고(집키미, 누르면 처음 화면으로), 오른쪽 구석에 "예시" 표시. 테두리 없는 보조 글자다.
 * 로고는 "/" 링크라서 새 탭으로도 열 수 있고, 그냥 누르면 지금 화면의 서류·결과를 버리고 처음 화면으로 간다.
 */
export function Header({ demo, onHome }: { demo: boolean; onHome: () => void }) {
  const marks = [demo ? '예시' : null, IS_MOCK ? '모의 데이터' : null].filter(Boolean)
  function onClick(e: MouseEvent<HTMLAnchorElement>) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    onHome()
  }
  return (
    <header className="site-header">
      <div className="site-header-inner">
        <a className="site-home" href="/" onClick={onClick}>
          <img className="site-logo" src={logo} alt="집키미 처음 화면" width={98} height={44} />
        </a>
        {marks.length > 0 && <span className="mode-marker">{marks.join(' · ')}</span>}
      </div>
    </header>
  )
}
