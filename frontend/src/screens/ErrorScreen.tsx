import type { DemoScenario } from '../api/types'
import { ExampleLinks } from '../components/ExampleLinks'
import { useScreenFocus } from '../lib/useScreenFocus'

export type ErrorPhase = 'extract' | 'check' | 'demo'

const TITLES: Record<ErrorPhase, string> = {
  extract: '분석 실패',
  check: '검사 실패',
  demo: '예시 결과 불러오기 실패',
}

/** UNSUPPORTED_FILE일 때는 서버 문장 대신 원인과 해결 방법을 한 번에 쓴다 (같은 말을 두 번 하지 않게) */
const UNSUPPORTED_FILE_TEXT =
  "PDF가 열리지 않거나 10MB·30쪽을 넘으면 올릴 수 없어요. 인터넷등기소에서 '현재 유효사항'으로 다시 열람해 PDF로 저장해 보세요."

const BACK_LABELS: Record<ErrorPhase, string> = {
  extract: '서류 다시 고르기',
  check: '내용 확인으로',
  demo: '처음으로',
}

/** S3 오류: [다시 시도] + 예시 결과 보기 */
export function ErrorScreen({
  phase,
  message,
  code,
  fileError,
  onRetry,
  onBack,
  onDemo,
  demoLoading,
}: {
  phase: ErrorPhase
  message: string
  /** 서버 오류 코드 (예: UNSUPPORTED_FILE). 없으면 null */
  code: string | null
  /** 같은 파일로는 다시 시도해도 소용없는 오류인지 (다른 파일을 골라야 함) */
  fileError: boolean
  onRetry: () => void
  /** extract: 서류 다시 고르기, check: 내용 확인으로, demo: 처음으로 */
  onBack: () => void
  onDemo: (scenario: DemoScenario) => void
  demoLoading: DemoScenario | null
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const busy = demoLoading !== null

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          {TITLES[phase]}
        </h1>
        <p role="alert">
          {phase === 'extract' && code === 'UNSUPPORTED_FILE' ? UNSUPPORTED_FILE_TEXT : message}
        </p>
      </div>

      <div className="actions">
        {fileError ? (
          <button type="button" className="btn-primary" onClick={onBack}>
            {BACK_LABELS[phase]}
          </button>
        ) : (
          <>
            <button type="button" className="btn-primary" disabled={busy} onClick={onRetry}>
              {phase === 'demo' && busy ? '불러오는 중' : '다시 시도'}
            </button>
            <button type="button" className="link" disabled={busy} onClick={onBack}>
              {BACK_LABELS[phase]}
            </button>
          </>
        )}
      </div>

      {phase !== 'demo' && (
        <section className="doc-section" aria-labelledby="error-example-title">
          <h2 id="error-example-title">예시 결과 보기</h2>
          <ExampleLinks loading={demoLoading} onSelect={onDemo} />
        </section>
      )}
    </>
  )
}
