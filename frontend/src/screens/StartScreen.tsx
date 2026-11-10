import type { DemoScenario } from '../api/types'
import { ExampleLinks } from '../components/ExampleLinks'
import { START_NOTICE } from '../content/static'
import { useScreenFocus } from '../lib/useScreenFocus'

/** S1 시작 */
export function StartScreen({
  onUpload,
  onDemo,
  demoLoading,
}: {
  onUpload: () => void
  onDemo: (scenario: DemoScenario) => void
  demoLoading: DemoScenario | null
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          보증금 위험 검토
        </h1>
        <p>
          등기부등본과 임대차 계약서를 올리면, 보증금을 잃을 수 있는 위험 신호를 근거와 함께
          보여줘요.
        </p>
      </div>

      <section className="sub-section" aria-labelledby="prep-title">
        <h2 id="prep-title">준비할 서류</h2>
        <dl className="rows">
          <div className="row">
            <dt>등기부등본</dt>
            <dd>PDF, 필수</dd>
          </div>
          <div className="row">
            <dt>임대차 계약서</dt>
            <dd>사진·PDF, 선택</dd>
          </div>
        </dl>
      </section>

      <div className="actions">
        <button type="button" className="btn-primary" onClick={onUpload}>
          서류 올리기
        </button>
      </div>

      <section className="doc-section" aria-labelledby="example-title">
        <h2 id="example-title">예시 결과 보기</h2>
        <ExampleLinks loading={demoLoading} onSelect={onDemo} />
      </section>

      <p className="footnote">{START_NOTICE}</p>
    </>
  )
}
