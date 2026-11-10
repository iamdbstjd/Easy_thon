import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'
import { checklistIcs } from '../api/client'
import { errorMessage } from '../api/errors'
import type {
  ChecklistItem,
  CheckRequest,
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
import { maskIds } from '../lib/mask'
import { useScreenFocus } from '../lib/useScreenFocus'

/** S5 리포트: 보증금 위험 검토서 (PRD 4.2 S5, 4.3 와이어프레임) */
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

  // 본문 절: 내용이 없는 절은 빼고 번호를 다시 매긴다
  const sections: { key: string; render: (n: number) => ReactNode }[] = []
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
  if (report.request_message) {
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
  if (report.special_terms.length > 0) {
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

/** 등급별 개수: 위험 3건 · 주의 2건 · 해당 없음 8건 · 확인 못 함 1건 (0인 등급은 뺀다, PRD 4.2 S5) */
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

/** 지번("789-1")이 줄 끝에서 갈라지지 않게 묶는다 */
function keepTogether(text: string): ReactNode[] {
  return text.split(/(\d+(?:-\d+)+)/).map((part, i) =>
    i % 2 === 1 ? (
      <span key={i} className="nowrap">
        {part}
      </span>
    ) : (
      part
    ),
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

  // 기준일 (PRD 7.1): 계약서의 계약일 → 직접 입력한 계약 예정일 → 검사한 날(today)
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
