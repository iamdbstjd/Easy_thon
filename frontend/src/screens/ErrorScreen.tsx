import type { ErrorDocument } from '../api/errors'
import type { DemoScenario } from '../api/types'
import { ExampleLinks } from '../components/ExampleLinks'
import { useScreenFocus } from '../lib/useScreenFocus'

export type ErrorPhase =
  | 'extract'
  | 'check'
  | 'demo'
  | 'recheck-extract'
  | 'recheck'
  | 'recheck-demo'
  | 'compare-extract'
  | 'compare'
  | 'compare-demo'

const TITLES: Record<ErrorPhase, string> = {
  extract: '분석 실패',
  check: '검사 실패',
  demo: '예시 결과 불러오기 실패',
  'recheck-extract': '분석 실패',
  recheck: '재확인 실패',
  'recheck-demo': '예시 결과 불러오기 실패',
  'compare-extract': '분석 실패',
  compare: '비교 실패',
  'compare-demo': '예시 결과 불러오기 실패',
}

/**
 * UNSUPPORTED_FILE일 때는 서버 문장 대신 원인과 해결 방법을 한 번에 쓴다 (같은 말을 두 번 하지 않게).
 * 어느 서류 때문인지 모르면 서버 문장(등기부·계약서 둘 다 안내)을 그대로 쓴다.
 */
const UNSUPPORTED_FILE_TEXT: Record<ErrorDocument, string> = {
  registry:
    "등기부 파일이 열리지 않거나, 파일 하나가 10MB를 넘거나, 모두 합쳐 30쪽(사진은 한 장이 한 쪽)을 넘으면 올릴 수 없어요. 인터넷등기소에서 '현재 유효사항'으로 다시 열람해 PDF로 저장해 보세요.",
  contract:
    '계약서 파일을 열지 못했어요. 사진(JPG·PNG 등)이나 PDF로, 파일 하나 10MB·모두 합쳐 30쪽까지 올릴 수 있어요. PDF가 열리지 않으면 계약서를 사진으로 찍어 올려 보세요.',
}

const BACK_LABELS: Record<ErrorPhase, string> = {
  extract: '서류 다시 고르기',
  check: '내용 확인으로',
  demo: '처음으로',
  'recheck-extract': '서류 다시 고르기',
  recheck: '날짜 확인으로',
  'recheck-demo': '처음으로',
  'compare-extract': '계약서 다시 고르기',
  compare: '검토서로 돌아가기',
  'compare-demo': '처음으로',
}

/** S3 오류: [다시 시도] + 예시 결과 보기 */
export function ErrorScreen({
  phase,
  message,
  code,
  document,
  fileError,
  retrying,
  onRetry,
  onBack,
  onDemo,
  demoLoading,
}: {
  phase: ErrorPhase
  message: string
  /** 서버 오류 코드 (예: UNSUPPORTED_FILE). 없으면 null */
  code: string | null
  /** 파일·문서 오류가 어느 서류 때문인지. 모르면 null */
  document: ErrorDocument | null
  /** 같은 파일로는 다시 시도해도 소용없는 오류인지 (다른 파일을 골라야 함) */
  fileError: boolean
  /** 다시 시도한 요청이 아직 진행 중인지 (검사·재확인은 잠깐 이 화면에 머문다) */
  retrying: boolean
  onRetry: () => void
  /** extract: 서류 다시 고르기, check: 내용 확인으로, demo: 처음으로 */
  onBack: () => void
  onDemo: (scenario: DemoScenario) => void
  demoLoading: DemoScenario | null
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const busy = demoLoading !== null || retrying
  // 수정된 계약서 올리기는 계약서 하나만 보낸다
  const doc: ErrorDocument | null = phase === 'compare-extract' ? 'contract' : document
  const reading = phase === 'extract' || phase === 'recheck-extract' || phase === 'compare-extract'
  const text = reading && code === 'UNSUPPORTED_FILE' && doc ? UNSUPPORTED_FILE_TEXT[doc] : message
  const backLabel = reading && fileError && doc === 'contract' ? '계약서 다시 고르기' : BACK_LABELS[phase]

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          {TITLES[phase]}
        </h1>
        <p role="alert">{text}</p>
      </div>

      <div className="actions">
        {fileError ? (
          <button type="button" className="btn-primary" onClick={onBack}>
            {backLabel}
          </button>
        ) : (
          <>
            <button type="button" className="btn-primary" disabled={busy} onClick={onRetry}>
              {retrying ? '다시 시도하는 중' : phase === 'demo' && busy ? '불러오는 중' : '다시 시도'}
            </button>
            <button type="button" className="link" disabled={demoLoading !== null} onClick={onBack}>
              {backLabel}
            </button>
          </>
        )}
      </div>

      {phase !== 'demo' && phase !== 'recheck-demo' && phase !== 'compare-demo' && (
        <section className="doc-section" aria-labelledby="error-example-title">
          <h2 id="error-example-title">예시 결과 보기</h2>
          <ExampleLinks loading={demoLoading} onSelect={onDemo} />
        </section>
      )}
    </>
  )
}
