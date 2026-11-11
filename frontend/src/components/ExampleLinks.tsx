import type { DemoScenario } from '../api/types'

// S1 예시 결과 보기 — A 위험 신호 없는 집 / B 확인할 게 있는 집 / C 위험 신호가 있는 집.
// "안전" 같은 단정 표현은 쓰지 않는다. 데모 시나리오를 불러오는 글자 링크다.
const EXAMPLES: { id: DemoScenario; label: string }[] = [
  { id: 'A', label: 'A 위험 신호 없는 집' },
  { id: 'B', label: 'B 확인할 게 있는 집' },
  { id: 'C', label: 'C 위험 신호가 있는 집' },
]

/** 예시 결과(데모 시나리오 A·B·C) 글자 링크 */
export function ExampleLinks({
  loading,
  onSelect,
  extra,
}: {
  loading: DemoScenario | null
  onSelect: (scenario: DemoScenario) => void
  /** 계약 후 재확인 예시: "A 집, 잔금 이틀 전 근저당이 생긴 경우" */
  extra?: { label: string; loading: boolean; onSelect: () => void }
}) {
  const busy = loading !== null || extra?.loading === true
  return (
    <>
      <ul className="link-list" aria-label="예시 결과">
        {EXAMPLES.map((example) => (
          <li key={example.id}>
            <button type="button" className="link" disabled={busy} onClick={() => onSelect(example.id)}>
              {loading === example.id ? `${example.id} 불러오는 중` : example.label}
            </button>
          </li>
        ))}
      </ul>
      {/* 재확인 예시는 검토서 예시(A·B·C)와 구분되게 따로 한 줄, 앞말을 붙인다 */}
      {extra && (
        <p className="example-extra">
          <span className="muted">계약 후 재확인 예시: </span>
          <button type="button" className="link" disabled={busy} onClick={extra.onSelect}>
            {extra.loading ? '불러오는 중' : extra.label}
          </button>
        </p>
      )}
    </>
  )
}
