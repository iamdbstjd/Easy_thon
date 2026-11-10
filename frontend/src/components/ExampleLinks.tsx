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
}: {
  loading: DemoScenario | null
  onSelect: (scenario: DemoScenario) => void
}) {
  return (
    <ul className="link-list" aria-label="예시 결과">
      {EXAMPLES.map((example) => (
        <li key={example.id}>
          <button
            type="button"
            className="link"
            disabled={loading !== null}
            onClick={() => onSelect(example.id)}
          >
            {loading === example.id ? `${example.id} 불러오는 중` : example.label}
          </button>
        </li>
      ))}
    </ul>
  )
}
