import type { ReactNode } from 'react'
import type { CompareReport, ContractChange, RequestFulfillment, RuleDelta } from '../api/types'
import { Fold } from '../components/Disclosure'
import { Excerpt } from '../components/Excerpt'
import { COUNT_LABEL, ruleLabel } from '../content/labels'
import { formatDate } from '../lib/format'
import { keepTogether } from '../lib/keepTogether'
import { maskPersonal } from '../lib/mask'
import { useScreenFocus } from '../lib/useScreenFocus'

/** 반영은 해당 없음 색(초록), 미반영은 위험 색(빨강), 직접 확인은 확인 못 함 색(회색) */
const STATUS_CLASS: Record<RequestFulfillment['status'], string> = {
  반영: 'grade-green',
  미반영: 'grade-red',
  '직접 확인': 'grade-unknown',
}

const stillFlagged = (d: RuleDelta) => d.after === 'red' || d.after === 'yellow'

/** S8 수정 전·후 비교서 */
export function CompareReportScreen({
  report,
  onOpenAfter,
  onHome,
}: {
  report: CompareReport
  /** [수정된 계약서로 검토서 보기]: 수정 후 결과로 S5 */
  onOpenAfter: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const before = report.before_overall
  const after = report.after_overall
  const sameVerdict = before.level === after.level && before.title === after.title

  // 남은 위험: 수정 후에도 위험·주의인 규칙 (위험 먼저). 반영률만 보고 "다 해결됐다"고 오해하지 않게 머리에 쓴다
  const remaining = [
    ...report.rule_deltas.filter((d) => d.after === 'red'),
    ...report.rule_deltas.filter((d) => d.after === 'yellow'),
  ]
  // 수정 후 판단하지 못하게 된 규칙. 개선으로 세지 않고 따로 쓴다
  const turnedUnknown = report.rule_deltas.filter((d) => d.change === '확인 못 함')
  // 2절: 해당 없음으로 그대로인 것만 접는다. 남은 위험·확인 못 함·바뀐 것은 펼쳐 둔다
  const foldedDelta = (d: RuleDelta) => d.change === '그대로' && d.after === 'green'
  const shown = report.rule_deltas.filter((d) => !foldedDelta(d))
  const folded = report.rule_deltas.filter(foldedDelta)

  const fieldChanges = report.contract_changes.filter((c) => !c.field.startsWith('특약'))
  const termChanges = report.contract_changes.filter((c) => c.field.startsWith('특약'))

  const { done, total } = report.rate
  const rateClass = total === 0 ? '' : done === total ? 'grade-green' : done === 0 ? 'grade-red' : 'grade-yellow'

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1} className="report-title">
          수정 전·후 비교서
        </h1>
        <dl className="rows doc-meta">
          {report.address && (
            <div className="row">
              <dt>대상</dt>
              <dd>{keepTogether(maskPersonal(report.address))}</dd>
            </div>
          )}
          <div className="row">
            <dt>요청 반영</dt>
            <dd>
              {total > 0 ? (
                <p className={`rate-figure ${rateClass}`}>
                  {total}건 중 {done}건 반영
                </p>
              ) : (
                <p>반영을 확인할 요청이 없어요.</p>
              )}
            </dd>
          </div>
          <div className="row">
            <dt>남은 위험</dt>
            <dd>
              {remaining.length > 0 ? (
                <p className="sep-list remaining-list">
                  {remaining.map((d) => (
                    <span key={d.id} className={`grade grade-${d.after}`}>
                      {ruleLabel(d.id, d.name)}
                    </span>
                  ))}
                </p>
              ) : (
                <p>없음</p>
              )}
            </dd>
          </div>
          {turnedUnknown.length > 0 && (
            <div className="row">
              <dt>확인 못 함</dt>
              <dd>
                <p className="sep-list remaining-list">
                  {turnedUnknown.map((d) => (
                    <span key={d.id} className="grade grade-unknown">
                      {ruleLabel(d.id, d.name)}
                    </span>
                  ))}
                </p>
                <p className="muted">수정된 계약서로는 판단하지 못했어요. 직접 확인하세요.</p>
              </dd>
            </div>
          )}
          <div className="row">
            <dt>종합 판정</dt>
            <dd className="verdict-detail cmp-verdict">
              {sameVerdict ? (
                <p className="verdict-line">
                  <span className={`verdict verdict-${after.level}`}>{after.title}</span>{' '}
                  <span className="muted nowrap">수정 전과 같아요</span>
                </p>
              ) : (
                <>
                  <p className="muted">
                    수정 전: <span className="nowrap">{before.title}</span>
                  </p>
                  <p className={`verdict verdict-${after.level}`}>
                    <span className="visually-hidden">수정 후: </span>
                    {after.title}
                  </p>
                </>
              )}
              {after.message && <p>{after.message}</p>}
            </dd>
          </div>
          <div className="row">
            <dt>개수 변화</dt>
            <dd className="counts sep-list">
              {(['red', 'yellow', 'green', 'unknown'] as const)
                .filter((level) => report.before_counts[level] > 0 || report.after_counts[level] > 0)
                .map((level) => (
                  <span key={level}>
                    <span className={`grade grade-${level}`}>{COUNT_LABEL[level]}</span>{' '}
                    {report.before_counts[level]}건 → {report.after_counts[level]}건
                  </span>
                ))}
            </dd>
          </div>
          <div className="row">
            <dt>기준일</dt>
            <dd>{formatDate(report.today) || '—'}</dd>
          </div>
        </dl>
      </div>

      <section className="doc-section" aria-labelledby="cmp-fulfillment">
        <h2 id="cmp-fulfillment">1. 요청서 반영</h2>
        {report.fulfillment.length > 0 ? <FulfillmentGroups items={report.fulfillment} /> : <p>없음</p>}
      </section>

      <section className="doc-section" aria-labelledby="cmp-deltas">
        <h2 id="cmp-deltas">2. 위험 신호 변화</h2>
        {shown.length > 0 ? <DeltaTable deltas={shown} /> : <p>바뀐 위험 신호가 없어요.</p>}
        {folded.length > 0 && (
          <Fold
            className="finding-fold"
            title={
              <>
                <span className="grade grade-green">{COUNT_LABEL.green}</span> 그대로 ({folded.length}건)
              </>
            }
          >
            <DeltaTable deltas={folded} />
          </Fold>
        )}
      </section>

      <section className="doc-section" aria-labelledby="cmp-contract">
        <h2 id="cmp-contract">3. 바뀐 계약 내용</h2>
        {fieldChanges.length === 0 && termChanges.length === 0 && <p>없음</p>}
        {fieldChanges.length > 0 && (
          <table className="cmp-table wrap-items">
            <caption className="visually-hidden">바뀐 계약 내용</caption>
            <thead>
              <tr>
                <th scope="col">항목</th>
                <th scope="col">수정 전</th>
                <th scope="col">수정 후</th>
              </tr>
            </thead>
            <tbody>
              {fieldChanges.map((c, i) => (
                <tr key={i} className="cmp-row">
                  <th scope="row" className="c-item">
                    {c.field}
                  </th>
                  <td className="c-val" data-label="수정 전">
                    <span className="c-text">{value(c.before)}</span>
                  </td>
                  <td className="c-val" data-label="수정 후">
                    <span className="c-text">{value(c.after)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {termChanges.map((c, i) => (
          <TermChange key={i} change={c} />
        ))}
      </section>

      {report.disclaimer && <p className="footnote">{report.disclaimer}</p>}

      <div className="actions">
        <button type="button" className="btn-primary" onClick={onOpenAfter}>
          수정된 계약서로 검토서 보기
        </button>
        <button type="button" className="link" onClick={onHome}>
          처음으로
        </button>
      </div>
    </>
  )
}

function value(v: string | null): ReactNode {
  return v ? keepTogether(maskPersonal(v)) : '—'
}

/** 상황 한 줄은 마침표로 끝나는 문장으로 쓴다 (S5 위험 신호와 같게) */
function withPeriod(text: string): string {
  const t = text.trim()
  return /[.?!]$/.test(t) ? t : `${t}.`
}

/** 짧은 이름이 없으면 문안을 그대로 쓴다 */
function labelOf(f: RequestFulfillment): string {
  return maskPersonal(f.label || f.item)
}

/**
 * 1절: 종류별로 묶는다. 고칠 곳·특약은 "n건 중 m건 반영"과 항목별 상태,
 * 받을 서류는 한 줄 목록과 설명 한 번. 특약 원문은 3절(추가된 특약)에만 둔다.
 */
function FulfillmentGroups({ items }: { items: RequestFulfillment[] }) {
  const fixes = items.filter((f) => f.kind === 'fix')
  const terms = items.filter((f) => f.kind === 'term')
  const docs = items.filter((f) => f.kind === 'document')
  const doneOf = (list: RequestFulfillment[]) => list.filter((f) => f.status === '반영').length
  const docNote = docs.find((f) => f.note)?.note

  return (
    <>
      {fixes.length > 0 && (
        <div className="fulfil-group">
          <h3>
            고칠 곳 <span className="nowrap">{fixes.length}건 중 {doneOf(fixes)}건 반영</span>
          </h3>
          <FulfilList items={fixes} showNote={() => true} />
        </div>
      )}
      {terms.length > 0 && (
        <div className="fulfil-group">
          <h3>
            특약 <span className="nowrap">{terms.length}건 중 {doneOf(terms)}건 반영</span>
          </h3>
          <FulfilList items={terms} showNote={(f) => f.status !== '반영'} />
        </div>
      )}
      {docs.length > 0 && (
        <div className="fulfil-group">
          <h3>
            받을 서류 <span className="nowrap">{docs.length}건</span> ·{' '}
            <span className="grade grade-unknown nowrap">직접 확인</span>
          </h3>
          <p className="sep-list doc-list">
            {docs.map((f, i) => (
              <span key={i}>{labelOf(f)}</span>
            ))}
          </p>
          {docNote && <p className="muted">{maskPersonal(docNote)}</p>}
        </div>
      )}
    </>
  )
}

function FulfilList({
  items,
  showNote,
}: {
  items: RequestFulfillment[]
  showNote: (f: RequestFulfillment) => boolean
}) {
  return (
    <ul className="fulfil-list">
      {items.map((f, i) => (
        <li key={i}>
          <span className="fulfil-label">{labelOf(f)}</span>
          <span className={`fulfil-status grade ${STATUS_CLASS[f.status]}`}>{f.status}</span>
          {f.note && showNote(f) && <span className="fulfil-note muted">{maskPersonal(f.note)}</span>}
        </li>
      ))}
    </ul>
  )
}

/** 변화 칸: 개선·악화·확인 못 함, 그대로인데 아직 위험·주의면 "위험 남음 / 주의 남음" */
function changeText(d: RuleDelta): { text: string; className: string } {
  if (d.change === '개선') return { text: '개선', className: 'grade grade-green' }
  if (d.change === '악화') return { text: '악화', className: 'grade grade-red' }
  if (d.change === '확인 못 함') return { text: '확인 못 함', className: 'grade grade-unknown' }
  if (d.after === 'red') return { text: '위험 남음', className: 'grade grade-red' }
  if (d.after === 'yellow') return { text: '주의 남음', className: 'grade grade-yellow' }
  return { text: '그대로', className: 'muted' }
}

/** 규칙 · 수정 전 · 수정 후 · 변화. 수정 후에도 위험·주의면 그 상황 문장을 행 아래 본문으로 쓴다 */
function DeltaTable({ deltas }: { deltas: RuleDelta[] }) {
  return (
    <table className="cmp-table wrap-items delta-table">
      <caption className="visually-hidden">규칙별 수정 전·후 등급</caption>
      <thead>
        <tr>
          <th scope="col">규칙</th>
          <th scope="col">수정 전</th>
          <th scope="col">수정 후</th>
          <th scope="col">변화</th>
        </tr>
      </thead>
      <tbody>
        {deltas.flatMap((d) => {
          const change = changeText(d)
          const situation = stillFlagged(d) && d.after_title ? withPeriod(maskPersonal(d.after_title)) : ''
          const rows = [
            <tr key={d.id} className={`cmp-row${situation ? ' has-note' : ''}`}>
              <th scope="row" className="c-item">
                {ruleLabel(d.id, d.name)}
              </th>
              <td className="c-val" data-label="수정 전">
                <span className={`c-text grade-${d.before}`}>{COUNT_LABEL[d.before]}</span>
              </td>
              <td className="c-val" data-label="수정 후">
                <span className={`c-text grade-${d.after}`}>{COUNT_LABEL[d.after]}</span>
              </td>
              <td className="c-result">
                <span className={change.className}>{change.text}</span>
              </td>
            </tr>,
          ]
          if (situation) {
            rows.push(
              <tr key={`${d.id}-note`} className="delta-note">
                <td colSpan={4}>{situation}</td>
              </tr>,
            )
          }
          return rows
        })}
      </tbody>
    </table>
  )
}

/** 특약 추가·삭제: 원문 인용 상자로 */
function TermChange({ change }: { change: ContractChange }) {
  const added = change.field === '특약 추가'
  const text = added ? change.after : change.before
  if (!text) return null
  return <Excerpt caption={added ? '추가된 특약' : '삭제된 특약'} text={text} />
}
