import { IS_MOCK } from '../api/client'

/** 머리글: 왼쪽에 서비스 이름, 오른쪽 구석에 "예시" 표시 (PRD F7의 데모 표시). 테두리 없는 보조 글자다. */
export function Header({ demo }: { demo: boolean }) {
  const marks = [demo ? '예시' : null, IS_MOCK ? '모의 데이터' : null].filter(Boolean)
  return (
    <header className="site-header">
      <div className="site-header-inner">
        <span className="site-name">자취방 보증금 지킴이</span>
        {marks.length > 0 && <span className="mode-marker">{marks.join(' · ')}</span>}
      </div>
    </header>
  )
}
