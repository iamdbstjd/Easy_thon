import { useEffect, useRef, useState } from 'react'
import { copyText } from '../lib/clipboard'

type CopyState = 'idle' | 'done' | 'failed'

const LINK_TEXT: Record<CopyState, string> = {
  idle: '복사',
  done: '복사됨',
  failed: '복사 실패',
}

/** "복사" 글자 링크. 누르면 2.5초 동안 "복사됨"으로 바뀐다. */
export function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<CopyState>('idle')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  async function onClick() {
    const ok = await copyText(text)
    setState(ok ? 'done' : 'failed')
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setState('idle'), 2500)
  }

  return (
    <>
      <button
        type="button"
        className="link"
        aria-label={state === 'idle' ? label : undefined}
        onClick={onClick}
      >
        {LINK_TEXT[state]}
      </button>
      <span className="visually-hidden" role="status">
        {state === 'idle' ? '' : LINK_TEXT[state]}
      </span>
    </>
  )
}
