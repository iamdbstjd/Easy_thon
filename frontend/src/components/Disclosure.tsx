import { useId, useState } from 'react'
import type { ReactNode } from 'react'

/**
 * 접어 두는 구역. 제목 줄 전체가 버튼이고, 오른쪽에 "펼치기 / 접기"를 밑줄 글자로 둔다.
 * 제목(h2·h3) 안에 aria-expanded 버튼을 두어 제목 목차가 유지되고 키보드·화면 낭독기로 쓸 수 있다.
 * defaultOpen은 처음 그릴 때만 쓴다.
 */
export function Fold({
  title,
  level = 3,
  defaultOpen = false,
  className,
  children,
}: {
  title: ReactNode
  level?: 2 | 3
  defaultOpen?: boolean
  className?: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  const Heading = level === 2 ? 'h2' : 'h3'
  return (
    <section className={className ? `fold ${className}` : 'fold'}>
      <Heading className="fold-heading">
        <button
          type="button"
          className="fold-button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="fold-title">{title}</span>
          <span className="fold-toggle" aria-hidden="true">
            {open ? '접기' : '펼치기'}
          </span>
        </button>
      </Heading>
      <div id={bodyId} className="fold-body" hidden={!open}>
        {children}
      </div>
    </section>
  )
}

/** 표 안의 한 줄로 여닫는 묶음 (S2 "계약서가 아직 없으면 직접 입력 …… 펼치기") */
export function ToggleGroup({
  label,
  defaultOpen = false,
  children,
}: {
  label: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  return (
    <div className="toggle-group">
      <button
        type="button"
        className="fold-button toggle-row"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="fold-title">{label}</span>
        <span className="fold-toggle" aria-hidden="true">
          {open ? '접기' : '펼치기'}
        </span>
      </button>
      <div id={bodyId} hidden={!open}>
        {children}
      </div>
    </div>
  )
}

/** 글 사이의 작은 펼치기: "근거 (등기부 2쪽, 계약서) …… 펼치기" */
export function Reveal({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="reveal">
      <summary>
        <span>{label}</span>
        <span className="reveal-toggle">
          <span className="when-closed">펼치기</span>
          <span className="when-open">접기</span>
        </span>
      </summary>
      <div className="reveal-body">{children}</div>
    </details>
  )
}
