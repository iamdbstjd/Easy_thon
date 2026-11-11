import { Fragment, useId, useState } from 'react'
import type { ReactNode } from 'react'
import type { RecheckChange, RecheckPhase, RecheckReport } from '../api/types'
import { Excerpt } from '../components/Excerpt'
import { ResultText } from '../components/ResultText'
import { formatDate, formatWon } from '../lib/format'
import { keepTogether } from '../lib/keepTogether'
import { holderList } from '../lib/holders'
import { maskIds } from '../lib/mask'
import { useScreenFocus } from '../lib/useScreenFocus'

const PHASE_LABEL: Record<RecheckPhase, string> = {
  before_balance: '잔금 전',
  balance_day: '잔금 당일',
  after_move_in: '입주 후',
}

const SECTION_LABEL: Record<RecheckChange['section'], string> = {
  gapgu: '갑구',
  eulgu: '을구',
}

/** S7 계약 후 재확인서 */
export function RecheckReportScreen({
  report,
  onAgain,
  onHome,
}: {
  report: RecheckReport
  /** [다른 등기부로 다시 확인]: 계약서는 그대로 두고 S6으로 */
  onAgain: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const { overall } = report

  // 절: 1 새로 생긴 권리, 2 특약 점검은 항상 둔다 ("없음"도 결과다). 3 할 일은 있을 때만.
  const sections: { key: string; render: (n: number) => ReactNode }[] = [
    {
      key: 'changes',
      render: (n) => (
        <section className="doc-section" aria-labelledby="rc-changes">
          <h2 id="rc-changes">
            {n}. 계약 후 새로 생긴 권리 ({report.changes.length}건)
          </h2>
          {/* 없을 때의 설명은 머리의 종합 판정 문장이 한다. 여기서는 "없음"만 */}
          {report.changes.length > 0 ? <ChangeTable changes={report.changes} /> : <p>없음</p>}
        </section>
      ),
    },
    {
      key: 'terms',
      render: (n) => (
        <section className="doc-section" aria-labelledby="rc-terms">
          <h2 id="rc-terms">{n}. 특약 점검</h2>
          {report.term_checks.length > 0 ? (
            <ul className="ruled-list term-checks">
              {report.term_checks.map((t, i) => (
                <li key={i}>
                  {/* 상태를 먼저(등급 색), 특약 원문은 근거처럼 인용 상자로 */}
                  <p className="term-status">
                    <span className={`grade grade-${t.level}`}>{t.status}</span>
                    {t.note && ` · ${maskIds(t.note)}`}
                  </p>
                  <Excerpt caption="계약서 특약" text={t.term} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">계약서에서 특약을 찾지 못했어요.</p>
          )}
        </section>
      ),
    },
  ]
  if (report.actions.length > 0) {
    sections.push({
      key: 'actions',
      render: (n) => (
        <section className="doc-section" aria-labelledby="rc-actions">
          <h2 id="rc-actions">{n}. 할 일</h2>
          <ol className="num-list">
            {report.actions.map((a, i) => (
              <li key={i}>{maskIds(a)}</li>
            ))}
          </ol>
        </section>
      ),
    })
  }

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1} className="report-title">
          계약 후 재확인서
        </h1>
        <dl className="rows doc-meta">
          {report.address && (
            <div className="row">
              <dt>대상</dt>
              <dd>{keepTogether(maskIds(report.address))}</dd>
            </div>
          )}
          <div className="row">
            <dt>계약일</dt>
            <dd>{formatDate(report.contract_date) || '—'}</dd>
          </div>
          <div className="row">
            <dt>잔금일</dt>
            <dd>{formatDate(report.balance_date) || '—'}</dd>
          </div>
          <div className="row">
            <dt>오늘</dt>
            <dd>
              {formatDate(report.today)} <span className="muted">({PHASE_LABEL[report.phase]})</span>
            </dd>
          </div>
          <div className="row">
            <dt>비교 기준일</dt>
            <dd>{formatDate(report.baseline_date) || '—'}</dd>
          </div>
          <div className="row">
            <dt>종합 판정</dt>
            <dd className="verdict-detail">
              <p className={`verdict verdict-${overall.level}`}>{overall.title}</p>
              {overall.message && <p>{maskIds(overall.message)}</p>}
            </dd>
          </div>
        </dl>
      </div>

      {sections.map((section, i) => (
        <Fragment key={section.key}>{section.render(i + 1)}</Fragment>
      ))}

      {report.disclaimer && <p className="footnote">{report.disclaimer}</p>}

      <div className="actions">
        <button type="button" className="btn-primary" onClick={onAgain}>
          다른 등기부로 다시 확인
        </button>
        <button type="button" className="link" onClick={onHome}>
          처음으로
        </button>
      </div>
    </>
  )
}

/** 새로 생긴 권리 표: 구분 · 등기목적 · 접수일 · 권리자 · 금액 · 판정, 줄마다 [원문] */
function ChangeTable({ changes }: { changes: RecheckChange[] }) {
  const baseId = useId()
  const [open, setOpen] = useState<ReadonlySet<number>>(() => new Set())

  function toggle(i: number) {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  return (
    <table className="entry-table">
      <caption className="visually-hidden">계약 후 새로 생긴 권리</caption>
      <thead>
        <tr>
          <th scope="col">구분</th>
          <th scope="col">등기목적</th>
          <th scope="col">접수일</th>
          <th scope="col">권리자</th>
          <th scope="col">금액</th>
          <th scope="col">판정</th>
          <th scope="col">
            <span className="visually-hidden">원문</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {changes.map((c, i) => {
          const sourceId = `${baseId}-source-${i}`
          const isOpen = open.has(i)
          return (
            <Fragment key={`${c.section}-${c.rank}-${i}`}>
              <tr className="entry-row">
                <td className="c-rank c-nowrap">{SECTION_LABEL[c.section]}</td>
                <td className="c-purpose">
                  <span className="entry-purpose">{c.purpose || '목적 없음'}</span>
                </td>
                <td className="c-nowrap" data-label="접수일">
                  {formatDate(c.received_at)}
                </td>
                <td data-label="권리자">{holderList(c.holders)}</td>
                <td className="c-nowrap" data-label="금액">
                  {c.amount !== null ? formatWon(c.amount) : ''}
                </td>
                <td data-label="판정">
                  <ResultText level={c.level} note={c.note} />
                </td>
                <td className="c-source">
                  {c.source_text && (
                    <button
                      type="button"
                      className="link"
                      aria-expanded={isOpen}
                      aria-controls={sourceId}
                      onClick={() => toggle(i)}
                    >
                      원문
                    </button>
                  )}
                </td>
              </tr>
              <tr id={sourceId} className="entry-source-row" hidden={!isOpen}>
                <td colSpan={7}>
                  {isOpen && (
                    <Excerpt caption={c.page ? `등기부 ${c.page}쪽` : '등기부'} text={c.source_text} />
                  )}
                </td>
              </tr>
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}
