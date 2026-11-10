import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'
import { checklistIcs } from '../api/client'
import { errorMessage } from '../api/errors'
import type {
  Amendment,
  ChecklistItem,
  CheckRequest,
  ComparisonRow,
  Counts,
  Evidence,
  ManualInput,
  Report,
  RuleResult,
} from '../api/types'
import { CopyButton } from '../components/CopyButton'
import { Fold, Reveal } from '../components/Disclosure'
import { Excerpt } from '../components/Excerpt'
import { Grade } from '../components/Grade'
import { CHECKLIST_WHEN_ORDER, COUNT_LABEL, DOC_LABEL, LEVEL_LABEL, ruleNumber } from '../content/labels'
import { HELP_LINKS, OFF_REGISTRY_ROWS, SPECIAL_TERMS_NOTE } from '../content/static'
import { formatDate, isoToLocalInput } from '../lib/format'
import { keepTogether } from '../lib/keepTogether'
import { maskIds } from '../lib/mask'
import { useScreenFocus } from '../lib/useScreenFocus'

/** S5 리포트: 보증금 위험 검토서 */
export function ReportScreen({
  report,
  request,
  onEdit,
  onFillMissing,
  onHome,
}: {
  report: Report
  request: CheckRequest | null
  onEdit: () => void
  /** [빠진 내용 채우기]: 확인하지 못한 규칙 ID를 넘겨 S4에서 관련 칸으로 바로 이동한다 */
  onFillMissing: (unknownRuleIds: string[]) => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const { overall, counts } = report

  // 🔴 → 🟡, 같은 등급 안에서는 규칙 ID 순서 (R2 다음이 R10이 되도록 숫자로 비교)
  const sorted = [...report.results].sort((a, b) => ruleNumber(a.id) - ruleNumber(b.id))
  const flagged = [
    ...sorted.filter((r) => r.level === 'red'),
    ...sorted.filter((r) => r.level === 'yellow'),
  ]
  const unknown = sorted.filter((r) => r.level === 'unknown')
  const green = sorted.filter((r) => r.level === 'green')
  // 🔴·🟡가 없고 ⚪만 있으면: ⚪ 목록을 펼쳐 두고 종합 판정 칸에 [빠진 내용 채우기]를 둔다
  const missingOnly = flagged.length === 0 && unknown.length > 0

  const target = request ? reviewTarget(request, report) : null
  const icsAddress =
    request?.contract?.address ?? request?.registry.address_road ?? request?.registry.address_jibun ?? null

  // 본문 절: 1 대조 → 2 위험 신호 → 3 요청서 → 4 일정 → 5 참고.
  // 내용이 없는 절은 빼고 번호를 다시 매긴다.
  const sections: { key: string; render: (n: number) => ReactNode }[] = []
  if (report.comparison.length > 0) {
    sections.push({
      key: 'comparison',
      render: (n) => (
        <Comparison number={n} rows={report.comparison} hasContract={!!request?.contract} />
      ),
    })
  }
  if (sorted.length > 0) {
    sections.push({
      key: 'signals',
      render: (n) => (
        <section className="doc-section" aria-labelledby="sec-signals">
          <h2 id="sec-signals">
            {n}. 위험 신호 ({flagged.length}건)
          </h2>
          {flagged.map((result, i) => (
            <Finding key={result.id} result={result} number={i + 1} />
          ))}
          {unknown.length > 0 && (
            <Fold
              className="finding-fold"
              title={<CountTitle level="unknown" count={unknown.length} />}
              defaultOpen={missingOnly}
            >
              <ul className="ruled-list">
                {unknown.map((r) => (
                  <li key={r.id}>
                    {r.name}
                    {r.unknown_reason && <p className="item-detail">{maskIds(r.unknown_reason)}</p>}
                  </li>
                ))}
              </ul>
            </Fold>
          )}
          {green.length > 0 && (
            <Fold className="finding-fold" title={<CountTitle level="green" count={green.length} />}>
              <ul className="ruled-list">
                {green.map((r) => (
                  <li key={r.id}>
                    {r.name}
                    {r.id === 'R5' && r.summary && <p className="item-detail">{maskIds(r.summary)}</p>}
                  </li>
                ))}
              </ul>
            </Fold>
          )}
        </section>
      ),
    })
  }
  const { amendment } = report
  if (amendment) {
    sections.push({
      key: 'amendment',
      render: (n) => (
        <AmendmentSection
          number={n}
          amendment={amendment}
          address={target?.address ?? null}
          date={formatDate(report.today)}
        />
      ),
    })
  }
  // amendment가 없는 예전 백엔드: 예전 두 절(메시지, 특약)로 보여준다
  if (!amendment && report.request_message) {
    const message = maskIds(report.request_message)
    sections.push({
      key: 'message',
      render: (n) => (
        <section className="doc-section" aria-labelledby="sec-message">
          <div className="section-head">
            <h2 id="sec-message">{n}. 집주인에게 보낼 메시지</h2>
            <CopyButton text={message} label="집주인에게 보낼 메시지 복사" />
          </div>
          <p className="message-text">{keepTogether(message)}</p>
        </section>
      ),
    })
  }
  if (!amendment && report.special_terms.length > 0) {
    sections.push({
      key: 'terms',
      render: (n) => (
        <section className="doc-section" aria-labelledby="sec-terms">
          <div className="section-head">
            <h2 id="sec-terms">{n}. 추천 특약</h2>
            <CopyButton
              text={report.special_terms.map((t, i) => `${i + 1}. ${t}`).join('\n')}
              label="추천 특약 복사"
            />
          </div>
          <ol className="num-list">
            {report.special_terms.map((term, i) => (
              <li key={i}>{term}</li>
            ))}
          </ol>
          <p className="muted">{SPECIAL_TERMS_NOTE}</p>
        </section>
      ),
    })
  }
  if (report.checklist.length > 0) {
    sections.push({
      key: 'schedule',
      render: (n) => <Schedule number={n} items={report.checklist} address={icsAddress} />,
    })
  }
  sections.push({
    key: 'off-registry',
    render: (n) => (
      <Fold level={2} className="doc-section" title={`${n}. 참고: 등기부만으로는 알 수 없는 것`}>
        {OFF_REGISTRY_ROWS.map((row) => (
          <div key={row.info} className="info-item">
            <h3>{row.info}</h3>
            <dl className="rows">
              <div className="row">
                <dt>왜 중요한가</dt>
                <dd>{row.why}</dd>
              </div>
              <div className="row">
                <dt>확인 방법</dt>
                <dd>{row.how}</dd>
              </div>
            </dl>
          </div>
        ))}
      </Fold>
    ),
  })

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1} className="report-title">
          보증금 위험 검토서
        </h1>
        <dl className="rows doc-meta">
          {target?.address && (
            <div className="row">
              <dt>검토 대상</dt>
              <dd>{keepTogether(maskIds(target.address))}</dd>
            </div>
          )}
          {target && (
            <>
              <div className="row">
                <dt>기준일</dt>
                <dd>{formatDate(target.baseDate)}</dd>
              </div>
              <div className="row">
                <dt>확인한 서류</dt>
                <dd className="sep-list">
                  {target.docs.map((doc) => (
                    <span key={doc}>{doc}</span>
                  ))}
                </dd>
              </div>
            </>
          )}
          <div className="row">
            <dt>종합 판정</dt>
            <dd className="verdict-detail">
              <p className={`verdict verdict-${overall.level}`}>{overall.title}</p>
              {overall.message && <p>{overall.message}</p>}
              <CountsLine counts={counts} />
              {missingOnly && (
                <p>
                  <button
                    type="button"
                    className="link"
                    onClick={() => onFillMissing(unknown.map((r) => r.id))}
                  >
                    빠진 내용 채우기
                  </button>
                </p>
              )}
            </dd>
          </div>
        </dl>
      </div>

      {sections.map((section, i) => (
        <Fragment key={section.key}>{section.render(i + 1)}</Fragment>
      ))}

      {report.disclaimer && <p className="footnote">{report.disclaimer}</p>}
      <ul className="link-list help-list mt-2 muted">
        {HELP_LINKS.map((link) => (
          <li key={link.href}>
            <p>
              {link.name} ({link.detail})
            </p>
            {link.tel && (
              <p>
                <a className="tap-target" href={`tel:${link.tel}`}>
                  전화 {link.tel}
                </a>
              </p>
            )}
            <p>
              <a className="tap-target" href={link.href} target="_blank" rel="noopener noreferrer">
                {link.label}
              </a>
            </p>
          </li>
        ))}
      </ul>

      <div className="actions">
        <button type="button" className="btn-primary" onClick={onEdit}>
          내용 고쳐서 다시 검사
        </button>
        <button type="button" className="link" onClick={onHome}>
          처음으로
        </button>
      </div>
    </>
  )
}

/** 대조표 값: 없으면 "—", 주민등록번호 모양은 가리고 지번은 한 줄로 묶는다 */
function cellValue(value: string | null): ReactNode {
  return value ? keepTogether(maskIds(value)) : '—'
}

/** 1절: 계약서·등기부 대조표 (F14). 항목 | 계약서 | 등기부·시세 | 결과 */
function Comparison({
  number,
  rows,
  hasContract,
}: {
  number: number
  rows: ComparisonRow[]
  hasContract: boolean
}) {
  return (
    <section className="doc-section" aria-labelledby="sec-compare">
      <h2 id="sec-compare">{number}. 계약서·등기부 대조</h2>
      <table className="cmp-table">
        <caption className="visually-hidden">계약서 값과 등기부·시세 값을 나란히 놓은 대조표</caption>
        <thead>
          <tr>
            <th scope="col">항목</th>
            <th scope="col">계약서</th>
            <th scope="col">등기부·시세</th>
            <th scope="col">결과</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const word = COUNT_LABEL[row.level]
            const note = maskIds(row.note.trim())
            // 🔴·🟡: 등급 단어 + 결과 ("위험 불일치"). 🟢·⚪: 결과만 등급 색으로 ("일치", "확인 못 함")
            const flaggedRow = row.level === 'red' || row.level === 'yellow'
            return (
              <tr key={`${row.rule_id}-${row.item}`} className={`cmp-row cmp-${row.level}`}>
                <th scope="row" className="c-item">
                  {row.item}
                </th>
                <td className="c-val" data-label="계약서">
                  <span className="c-text">{cellValue(row.contract)}</span>
                </td>
                <td className="c-val" data-label="등기부·시세">
                  <span className="c-text">{cellValue(row.registry)}</span>
                </td>
                <td className="c-result">
                  {flaggedRow ? (
                    <>
                      <span className={`grade grade-${row.level}`}>{word}</span>
                      {note && note !== word && ` ${note}`}
                    </>
                  ) : (
                    <span className={`grade-${row.level}`}>{note || word}</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {!hasContract && <p className="muted">계약서를 올리면 임대인·호수·특약을 대조할 수 있어요.</p>}
    </section>
  )
}

const PART_MARKS = ['가', '나', '다']

/**
 * 3절: 계약서 수정 요청서 (F15). 계약서가 없으면 서버가 제목을 "계약 전 요청서"로 보낸다.
 * [복사]는 amendment.text 전체, [인쇄]는 이 절만 A4로 인쇄한다 (styles.css의 @media print).
 */
function AmendmentSection({
  number,
  amendment,
  address,
  date,
}: {
  number: number
  amendment: Amendment
  address: string | null
  date: string
}) {
  const parts: { key: string; title: string; body: ReactNode }[] = []
  if (amendment.fixes.length > 0) {
    parts.push({
      key: 'fixes',
      title: '계약서에서 고칠 곳',
      body: (
        <ul className="fix-list">
          {amendment.fixes.map((fix, i) => (
            <li key={i}>
              <p>
                <strong>{fix.item}</strong>: {fix.current ? maskIds(fix.current) : '없음'} →{' '}
                {maskIds(fix.proposed)}
              </p>
              {fix.reason && <p className="muted">이유: {maskIds(fix.reason)}</p>}
            </li>
          ))}
        </ul>
      ),
    })
  }
  if (amendment.terms.length > 0) {
    parts.push({
      key: 'terms',
      title: '넣어 주실 특약',
      body: (
        <ol className="paren-list">
          {amendment.terms.map((term, i) => (
            <li key={i}>{term}</li>
          ))}
        </ol>
      ),
    })
  }
  if (amendment.documents.length > 0) {
    parts.push({
      key: 'documents',
      title: '계약 전에 받을 서류',
      body: (
        <ol className="paren-list">
          {amendment.documents.map((doc, i) => (
            <li key={i}>{doc}</li>
          ))}
        </ol>
      ),
    })
  }

  return (
    <section className="doc-section amendment" aria-labelledby="sec-amendment">
      <div className="section-head">
        <h2 id="sec-amendment">
          <span className="no-print">{number}. </span>
          {amendment.title}
        </h2>
        <span className="head-links no-print">
          <CopyButton text={maskIds(amendment.text)} label={`${amendment.title} 복사`} />
          <button type="button" className="link" onClick={() => window.print()}>
            인쇄
          </button>
        </span>
      </div>
      <dl className="rows print-only">
        {address && (
          <div className="row">
            <dt>대상</dt>
            <dd>{keepTogether(maskIds(address))}</dd>
          </div>
        )}
        <div className="row">
          <dt>작성일</dt>
          <dd>{date}</dd>
        </div>
      </dl>
      {parts.map((part, i) => (
        <div key={part.key} className="amend-part">
          {/* 화면: 검토서 절 번호와 겹치지 않게 가·나·다. 인쇄: 12.6 문안대로 1·2·3 */}
          <h3>
            <span className="no-print">{PART_MARKS[i]}. </span>
            <span className="print-inline">{i + 1}. </span>
            {part.title}
          </h3>
          {part.body}
        </div>
      ))}
      <p className="muted no-print">{SPECIAL_TERMS_NOTE}</p>
      <p className="print-only">위 내용을 반영해 주시면 계약을 진행하고 싶습니다. 감사합니다.</p>
      <dl className="rows print-only sign-rows">
        <div className="row">
          <dt>받는 분</dt>
          <dd>
            <span className="sign-line" />
          </dd>
        </div>
        <div className="row">
          <dt>요청인</dt>
          <dd>
            <span className="sign-line" /> (서명)
          </dd>
        </div>
      </dl>
      <p className="print-only print-foot">
        이 요청서는 서류를 기준으로 만든 참고 자료이며 법률 자문이 아닙니다.
      </p>
    </section>
  )
}

/** 등급별 개수: 위험 3건 · 주의 2건 · 해당 없음 8건 · 확인 못 함 1건 */
function CountsLine({ counts }: { counts: Counts }) {
  const items: ReactNode[] = []
  for (const level of ['red', 'yellow', 'green', 'unknown'] as const) {
    if (counts[level] > 0) {
      items.push(
        <span key={level}>
          <span className={`grade grade-${level}`}>{COUNT_LABEL[level]}</span> {counts[level]}건
        </span>,
      )
    }
  }
  if (items.length === 0) return null
  // 구분점(·)은 CSS(.sep-list)가 그린다. 줄이 바뀌어도 줄 끝·줄 앞에 점이 남지 않는다.
  return <p className="counts sep-list">{items}</p>
}

/** 접힌 목록 제목: "해당 없음 (8건)", "확인 못 함 (1건)" */
function CountTitle({ level, count }: { level: 'green' | 'unknown'; count: number }) {
  return (
    <>
      <span className={`grade grade-${level}`}>{COUNT_LABEL[level]}</span> ({count}건)
    </>
  )
}

/** 상황 한 줄은 마침표로 끝나는 문장으로 쓴다 */
function withPeriod(text: string): string {
  const t = text.trim()
  return /[.?!]$/.test(t) ? t : `${t}.`
}

/** "302" → "302호", "302호" → 그대로 */
function withSuffix(value: string | null, suffix: string): string | null {
  const v = value?.trim()
  if (!v) return null
  return /^\d+$/.test(v) ? `${v}${suffix}` : v
}

function hasManualValues(manual: ManualInput): boolean {
  return Object.values(manual).some((v) => v !== null)
}

/** 문서 머리: 어느 집을, 어떤 서류로, 언제 기준으로 봤는지 */
function reviewTarget(req: CheckRequest, report: Report) {
  const { registry, contract } = req

  // 검토 대상: 계약서 주소, 없으면 등기부 도로명(또는 지번) 주소 + 동·호
  let address = contract?.address?.trim() || null
  if (!address) {
    const unit = [withSuffix(registry.unit.dong, '동'), withSuffix(registry.unit.ho, '호')]
    address =
      [(registry.address_road ?? registry.address_jibun)?.trim(), ...unit].filter(Boolean).join(' ') ||
      null
  }

  // 기준일: 계약서의 계약일 → 직접 입력한 계약 예정일 → 검사한 날(today)
  const baseDate = contract?.contract_date ?? req.manual.contract_date ?? report.today

  // 확인한 서류: 등기부(열람일) · 계약서 · 직접 입력 · 건축물대장 · 시세
  const docs: string[] = []
  const viewed = isoToLocalInput(registry.viewed_at)
  if (viewed) {
    const year = viewed.slice(0, 4)
    const month = Number(viewed.slice(5, 7))
    const day = Number(viewed.slice(8, 10))
    const yearText = year === baseDate.slice(0, 4) ? '' : `${year}년 `
    docs.push(`등기부(${yearText}${month}월 ${day}일 열람)`)
  } else {
    docs.push('등기부')
  }
  if (contract) docs.push('계약서')
  if (hasManualValues(req.manual)) docs.push('직접 입력')
  if (req.building) docs.push('건축물대장')
  if (req.market && req.market.price !== null) docs.push('시세')

  return { address, baseDate, docs }
}

/** "등기부 2쪽, 계약서" 처럼 근거 문서를 줄여 쓴다. 같은 문서의 쪽은 "2·3쪽"으로 묶는다. */
function evidenceSummary(evidence: Evidence[]): string {
  const pagesByDoc = new Map<Evidence['doc'], number[]>()
  for (const ev of evidence) {
    const pages = pagesByDoc.get(ev.doc) ?? []
    if (ev.page !== null && !pages.includes(ev.page)) pages.push(ev.page)
    pagesByDoc.set(ev.doc, pages)
  }
  return [...pagesByDoc]
    .map(([doc, pages]) => (pages.length ? `${DOC_LABEL[doc]} ${pages.join('·')}쪽` : DOC_LABEL[doc]))
    .join(', ')
}

/** 위험 신호 한 항목: 번호 · 판정 · 제목, 설명, 할 일, 근거 */
function Finding({ result, number }: { result: RuleResult; number: number }) {
  const titleId = `finding-${result.id}`
  return (
    <article className="finding" aria-labelledby={titleId}>
      <div className="finding-head">
        <span className="finding-num" aria-hidden="true">
          {number}
        </span>
        <Grade level={result.level} decorative />
        <h3 id={titleId} className="finding-title">
          <span className="visually-hidden">
            {number}. {LEVEL_LABEL[result.level]}:{' '}
          </span>
          {result.name || maskIds(result.title)}
        </h3>
      </div>
      <div className="finding-body">
        {result.title && result.name && <p>{maskIds(withPeriod(result.title))}</p>}
        {result.summary && <p>{maskIds(result.summary)}</p>}
        {result.action && (
          <p>
            <span className="finding-action-label">할 일:</span> {maskIds(result.action)}
          </p>
        )}
        {result.evidence.length > 0 && (
          <Reveal label={`근거 (${evidenceSummary(result.evidence)})`}>
            {result.evidence.map((ev, i) => (
              <Excerpt
                key={i}
                caption={`${DOC_LABEL[ev.doc]}${ev.page !== null ? ` ${ev.page}쪽` : ''}`}
                text={ev.text}
              />
            ))}
          </Reveal>
        )}
      </div>
    </article>
  )
}

/** 계약 일정: 시점(when)별 줄. "캘린더에 저장"은 .ics 파일을 내려받는다 */
function Schedule({
  number,
  items,
  address,
}: {
  number: number
  items: ChecklistItem[]
  address: string | null
}) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const groups: { when: string; items: ChecklistItem[] }[] = []
  for (const item of items) {
    const group = groups.find((g) => g.when === item.when)
    if (group) group.items.push(item)
    else groups.push({ when: item.when, items: [item] })
  }
  const order = (when: string) => {
    const i = CHECKLIST_WHEN_ORDER.indexOf(when)
    return i === -1 ? CHECKLIST_WHEN_ORDER.length : i
  }
  groups.sort((a, b) => order(a.when) - order(b.when))
  const hasDates = items.some((item) => item.date)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await checklistIcs(items, address)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="doc-section" aria-labelledby="sec-schedule">
      <div className="section-head">
        <h2 id="sec-schedule">{number}. 계약 일정</h2>
        {hasDates && (
          <button type="button" className="link" disabled={saving} onClick={save}>
            {saving ? '저장 중' : '캘린더에 저장'}
          </button>
        )}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <dl className="rows">
        {groups.map((group) => {
          const dates = [...new Set(group.items.map((item) => item.date ?? ''))]
          const sharedDate = dates.length === 1 ? dates[0] : ''
          return (
            <div key={group.when} className="row">
              <dt>{group.when}</dt>
              <dd>
                {sharedDate && <p className="muted">{formatDate(sharedDate, true)}</p>}
                <ul className="dot-list">
                  {group.items.map((item, i) => (
                    <li key={i}>
                      {item.title}
                      {!sharedDate && item.date && (
                        <span className="muted"> ({formatDate(item.date, true)})</span>
                      )}
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}
