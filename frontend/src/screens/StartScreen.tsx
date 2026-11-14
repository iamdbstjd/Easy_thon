import type { DemoScenario } from '../api/types'
import { ExampleLinks } from '../components/ExampleLinks'
import { START_NOTICE } from '../content/static'
import { useScreenFocus } from '../lib/useScreenFocus'

/** S1 시작 */
export function StartScreen({
  onUpload,
  onDemo,
  demoLoading,
  onRecheck,
  onRecheckDemo,
  recheckDemoLoading,
  onCompareDemo,
  compareDemoLoading,
  onPrivacy,
}: {
  onUpload: () => void
  onDemo: (scenario: DemoScenario) => void
  demoLoading: DemoScenario | null
  /** 계약 후 재확인 (S6) */
  onRecheck: () => void
  /** 계약 후 재확인 예시 (S7) */
  onRecheckDemo: () => void
  recheckDemoLoading: boolean
  /** 수정 전·후 비교 예시 (S8) */
  onCompareDemo: () => void
  compareDemoLoading: boolean
  /** 개인정보 처리 안내 */
  onPrivacy: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          보증금 위험 검토
        </h1>
        <p>
          사인할 계약서를 등기부와 맞춰 보고, 보증금을 잃을 수 있는 위험 신호를 근거와 함께 보여
          줘요.
        </p>
      </div>

      <section className="sub-section" aria-labelledby="prep-title">
        <h2 id="prep-title">준비할 서류</h2>
        <dl className="rows">
          <div className="row">
            <dt>등기부등본</dt>
            <dd>
              PDF·사진 <span className="muted">(필수)</span>
            </dd>
          </div>
          <div className="row">
            <dt>임대차 계약서</dt>
            <dd>
              PDF·사진 <span className="muted">(선택)</span>
            </dd>
          </div>
        </dl>
      </section>

      <div className="actions">
        <button type="button" className="btn-primary" onClick={onUpload}>
          서류 올리기
        </button>
        <button type="button" className="link" onClick={onRecheck}>
          이미 계약했다면: 계약 후 재확인
        </button>
      </div>

      <section className="doc-section" aria-labelledby="example-title">
        <h2 id="example-title">예시 결과 보기</h2>
        <ExampleLinks
          loading={demoLoading}
          onSelect={onDemo}
          extras={[
            {
              lead: '계약 후 재확인 예시:',
              label: 'A 집, 잔금 이틀 전 근저당이 생긴 경우',
              loading: recheckDemoLoading,
              onSelect: onRecheckDemo,
            },
            {
              lead: '수정 전·후 비교 예시:',
              label: 'C 집, 요청서대로 계약서를 고친 경우',
              loading: compareDemoLoading,
              onSelect: onCompareDemo,
            },
          ]}
        />
      </section>

      <div className="footnote">
        <p>{START_NOTICE}</p>
        <p>
          <button type="button" className="link" onClick={onPrivacy}>
            개인정보 처리 안내
          </button>
        </p>
      </div>
    </>
  )
}
