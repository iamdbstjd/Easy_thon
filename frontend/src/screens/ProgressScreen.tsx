import { useEffect, useState } from 'react'
import type { Mode } from '../api/types'
import { useScreenFocus } from '../lib/useScreenFocus'

export type ProgressPhase = 'extract' | 'check'

/** 이 시간이 지나면 "보통 1분 안에 끝나요" 대신 솔직한 안내를 보여준다 */
const SLOW_AFTER_S = 60

interface Step {
  label: string
  status: string
  active: boolean
}

/**
 * 실제로 진행 중인 일만 "진행 중"으로 보여준다 (PRD 4.2 S3: 상태는 대기 / 진행 중 / 완료).
 * - extract: /api/extract 동안. 서버는 등기부와 계약서를 동시에 읽으므로 두 단계가 함께 진행 중이다.
 * - check: /api/check 동안. 앞의 두 단계는 이미 끝났거나(실제 서류) 데모 값을 쓴다.
 */
function stepsFor(phase: ProgressPhase, hasContract: boolean, source: Mode): Step[] {
  if (phase === 'extract') {
    return [
      { label: '등기부', status: '진행 중', active: true },
      hasContract
        ? { label: '계약서', status: '진행 중', active: true }
        : { label: '계약서', status: '없음', active: false },
      { label: '위험 신호 확인', status: '대기', active: false },
    ]
  }
  const done = source === 'demo' ? '예시 값' : '완료'
  return [
    { label: '등기부', status: done, active: false },
    { label: '계약서', status: hasContract ? done : '없음', active: false },
    { label: '위험 신호 확인', status: '진행 중', active: true },
  ]
}

/** S3 분석 중 */
export function ProgressScreen({
  phase,
  startedAt,
  hasContract,
  source,
  onCancel,
}: {
  phase: ProgressPhase
  startedAt: number
  hasContract: boolean
  source: Mode
  onCancel: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
  const steps = stepsFor(phase, hasContract, source)
  const note =
    seconds >= SLOW_AFTER_S
      ? '조금 더 걸리고 있어요. 90초가 지나면 다시 시도할 수 있어요.'
      : phase === 'extract'
        ? '보통 1분 안에 끝나요.'
        : null

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          {phase === 'extract' ? '서류 읽는 중' : '위험 신호 확인 중'} · {seconds}초
        </h1>
        {note && <p className="muted">{note}</p>}
      </div>

      <dl className="rows mt-3">
        {steps.map((step) => (
          <div key={step.label} className="row">
            <dt>{step.label}</dt>
            <dd className={step.active ? 'step-active' : 'muted'}>{step.status}</dd>
          </div>
        ))}
      </dl>

      <div className="actions mt-2">
        <button type="button" className="link" onClick={onCancel}>
          취소
        </button>
      </div>
    </>
  )
}
