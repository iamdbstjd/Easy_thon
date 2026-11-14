import { Fragment, useRef, useState } from 'react'
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
  MarketDeal,
  MarketInsight,
  MarketStats,
  Report,
  RuleResult,
} from '../api/types'
import { CopyButton } from '../components/CopyButton'
import { Fold, Reveal } from '../components/Disclosure'
import { Excerpt } from '../components/Excerpt'
import { Grade } from '../components/Grade'
import { ResultText } from '../components/ResultText'
import { CHECKLIST_WHEN_ORDER, COUNT_LABEL, DOC_LABEL, LEVEL_LABEL, ruleNumber } from '../content/labels'
import { HELP_LINKS, OFF_REGISTRY_ROWS, SPECIAL_TERMS_NOTE, quickLinks } from '../content/static'
import { formatArea, formatDate, formatPeriod, formatWon, isoToLocalInput } from '../lib/format'
import { keepTogether } from '../lib/keepTogether'
import { maskPersonal } from '../lib/mask'
import { reportPdf } from '../lib/reportPdf'
import { buildShareText, canShareFiles, downloadFile, mailtoHref, shareFile, shareText } from '../lib/share'
import { useScreenFocus } from '../lib/useScreenFocus'

/** S5 리포트: 보증금 위험 검토서 */
export function ReportScreen({
  report,
  request,
  marketInsight = null,
  onEdit,
  onFillMissing,
  onRecheck,
  onCompare,
  onHome,
}: {
  report: Report
  request: CheckRequest | null
  /** 실제 분석에서 찾은 실거래 (예시에는 없다). 1절 대조표 아래에 보여 준다 */
  marketInsight?: MarketInsight | null
  onEdit: () => void
  /** 4절 아래 "잔금 전 재확인" → S6 (지금 계약서를 이어 쓴다) */
  onRecheck: () => void
  /** 3절 아래 "수정된 계약서 올리기" → 고친 계약서만 올려 수정 전·후 비교 */
  onCompare: () => void
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
  // 지도 검색에는 동·호수 없이 건물 주소만 쓴다
  const mapAddress = request ? (request.registry.address_road ?? request.registry.address_jibun ?? null) : null
  const shareBody = () => {
    const host = window.location.hostname
    const origin = host === 'localhost' || host === '127.0.0.1' ? null : window.location.origin
    return buildShareText(report, target, marketInsight, origin)
  }
  // 같은 검토서는 PDF를 한 번만 만든다 (메모리에만 둔다)
  const pdfCache = useRef<{ key: unknown[]; file: File } | null>(null)
  /** 검토서 전체를 PDF 파일로 (lib/reportPdf.ts) */
  async function makePdf(): Promise<File> {
    const key = [report, request, marketInsight]
    const cached = pdfCache.current
    if (cached && cached.key.every((v, i) => v === key[i])) return cached.file
    const source = document.querySelector<HTMLElement>('main.page')
    if (!source) throw new Error('report not on screen')
    const file = await reportPdf(source, {
      fileName: `집키미_검토서_${report.today}.pdf`,
      title: `집키미 보증금 위험 검토서 ${report.today}`,
      footer: `집키미 · 보증금 위험 검토서 · ${formatDate(report.today)}`,
    })
    pdfCache.current = { key, file }
    return file
  }
  /** 검토서 전체를 인쇄 창으로 보낸다 (컴퓨터의 인쇄하기). 요청서 [인쇄]는 요청서만 뽑는다 */
  function onPrint() {
    const body = document.body
    const title = document.title
    // 접혀 있는 근거 원문(<details>)은 인쇄 때 펼쳤다가 끝나면 되돌린다
    const opened = [...document.querySelectorAll<HTMLDetailsElement>('main details:not([open])')]
    opened.forEach((d) => (d.open = true))
    body.classList.add('print-report')
    document.title = `집키미_검토서_${report.today}` // PDF 파일 이름이 된다
    const done = () => {
      body.classList.remove('print-report')
      document.title = title
      opened.forEach((d) => (d.open = false))
    }
    window.addEventListener('afterprint', done, { once: true })
    window.print()
  }
  const icsAddress =
    request?.contract?.address ?? request?.registry.address_road ?? request?.registry.address_jibun ?? null

  // 본문 절: 1 대조 → 2 위험 신호 → 3 요청서 → 4 일정 → 5 참고.
  // 내용이 없는 절은 빼고 번호를 다시 매긴다.
  const sections: { key: string; render: (n: number) => ReactNode }[] = []
  const deposit = request?.contract?.deposit ?? request?.manual.deposit ?? null
  const monthlyRent = request?.contract?.monthly_rent ?? request?.manual.monthly_rent ?? null
  const market = marketInsight ? (
    <MarketBlock insight={marketInsight} deposit={deposit} monthlyRent={monthlyRent} />
  ) : null
  if (report.comparison.length > 0 || market) {
    sections.push({
      key: 'comparison',
      render: (n) => (
        <Comparison number={n} rows={report.comparison} hasContract={!!request?.contract}>
          {market}
        </Comparison>
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
                    {r.unknown_reason && <p className="item-detail">{maskPersonal(r.unknown_reason)}</p>}
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
                    {r.id === 'R5' && r.summary && <p className="item-detail">{maskPersonal(r.summary)}</p>}
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
          hasContract={Boolean(request?.contract)}
          onCompare={onCompare}
        />
      ),
    })
  }
  // amendment가 없는 예전 백엔드: 예전 두 절(메시지, 특약)로 보여준다
  if (!amendment && report.request_message) {
    const message = maskPersonal(report.request_message)
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
      render: (n) => (
        <Schedule number={n} items={report.checklist} address={icsAddress} onRecheck={onRecheck} />
      ),
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
              <dd>{keepTogether(maskPersonal(target.address))}</dd>
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
              <ShareActions getText={shareBody} makePdf={makePdf} onPrint={onPrint} />
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
          <div className="row quick-row">
            <dt>바로가기</dt>
            <dd className="sep-list">
              {quickLinks(mapAddress).map((link) => (
                <a key={link.label} href={link.href} target="_blank" rel="noopener noreferrer">
                  {link.label}
                </a>
              ))}
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

      <ShareActions getText={shareBody} makePdf={makePdf} onPrint={onPrint} />

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

/**
 * 검토서 보내기 한 줄 (검토서 위·아래에 둔다). 알림은 누른 줄에만 뜬다.
 * 휴대폰: PDF로 공유하기(공유창으로 카톡·메일) · 요약 글 공유하기
 * 컴퓨터: PDF 내려받기 · 요약 글 공유하기 · 메일로 보내기 · 인쇄하기
 */
function ShareActions({
  getText,
  makePdf,
  onPrint,
}: {
  getText: () => string
  makePdf: () => Promise<File>
  onPrint: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const sendsFiles = canShareFiles()

  async function onPdf() {
    setBusy(true)
    setNote('PDF를 만들고 있어요…')
    let file: File
    try {
      file = await makePdf()
    } catch {
      setNote('PDF를 만들지 못했어요. 잠시 뒤 다시 눌러 보세요.')
      return
    } finally {
      setBusy(false)
    }
    const result = sendsFiles ? await shareFile(file) : 'failed'
    if (result === 'failed') {
      downloadFile(file)
      setNote('PDF를 내려받았어요. 카톡이나 메일에 첨부해 보내세요.')
    } else {
      setNote(result === 'blocked' ? 'PDF를 만들었어요. 한 번 더 누르면 공유창이 열려요.' : '')
    }
  }

  async function onText() {
    const result = await shareText(getText())
    setNote(
      result === 'copied'
        ? '요약 글을 복사했어요. 카톡이나 문자에 붙여 넣으세요.'
        : result === 'failed'
          ? '복사하지 못했어요.'
          : '',
    )
  }

  return (
    <p className="share-line">
      <button type="button" className="link" disabled={busy} onClick={onPdf}>
        {sendsFiles ? 'PDF로 공유하기' : 'PDF 내려받기'}
      </button>
      <button type="button" className="link" onClick={onText}>
        요약 글 공유하기
      </button>
      {!sendsFiles && (
        <>
          <a className="link" href={mailtoHref(getText())}>
            메일로 보내기
          </a>
          <button type="button" className="link" onClick={onPrint}>
            인쇄하기
          </button>
        </>
      )}
      <span className="muted" role="status">
        {note}
      </span>
    </p>
  )
}

/** 대조표 값: 없으면 "—", 주민등록번호 모양은 가리고 지번은 한 줄로 묶는다 */
function cellValue(value: string | null): ReactNode {
  return value ? keepTogether(maskPersonal(value)) : '—'
}

/** 1절: 계약서·등기부 대조표. 항목 | 계약서 | 등기부·시세 | 결과. 아래에 실거래(children)를 붙인다 */
function Comparison({
  number,
  rows,
  hasContract,
  children,
}: {
  number: number
  rows: ComparisonRow[]
  hasContract: boolean
  children?: ReactNode
}) {
  return (
    <section className="doc-section" aria-labelledby="sec-compare">
      <h2 id="sec-compare">{number}. 계약서·등기부 대조</h2>
      {rows.length > 0 && (
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
                  <ResultText level={row.level} note={row.note} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      )}
      {!hasContract && <p className="muted">계약서를 올리면 임대인·호수·특약을 대조할 수 있어요.</p>}
      {children}
    </section>
  )
}

const DEAL_KIND: Record<MarketDeal['kind'], string> = { sale: '매매', jeonse: '전세', monthly: '월세' }

function scopeText(stats: MarketStats): string {
  if (stats.scope === 'same_building') return `같은 건물 ${stats.count}건`
  return stats.similar_area ? `같은 동 비슷한 면적 ${stats.count}건` : `같은 동 ${stats.count}건`
}

/** "2023-12 ~ 2026-11" → 36 (개월). 모르면 0 */
function periodMonths(period: string | null): number {
  const m = /(\d{4})-(\d{1,2})\s*~\s*(\d{4})-(\d{1,2})/.exec(period ?? '')
  return m ? (Number(m[3]) - Number(m[1])) * 12 + Number(m[4]) - Number(m[2]) + 1 : 0
}

function statsText(stats: MarketStats): string {
  const range = stats.count > 1 ? `, ${formatWon(stats.low)} ~ ${formatWon(stats.high)}` : ''
  const months = periodMonths(stats.period)
  const when = months > 12 ? ` · 최근 ${Math.round(months / 12)}년` : ''
  const basis = stats.per_m2 ? '을 ㎡당 가격으로 이 집 면적에 맞춘' : ''
  return `${scopeText(stats)}${basis} 중간값${range}${when}`
}

/** 이 집 보증금과 주변 중간값의 차이 (판단은 하지 않고 숫자만) */
function gapText(deposit: number, median: number): string {
  const diff = deposit - median
  if (median <= 0 || Math.abs(diff) / median < 0.05) return '주변 중간값과 비슷해요'
  const pct = Math.round((Math.abs(diff) / median) * 100)
  return `주변 중간값보다 ${formatWon(Math.abs(diff))}(${pct}%) ${diff > 0 ? '높아요' : '낮아요'}`
}

function floorText(floor: string | null): string {
  if (!floor) return ''
  if (!/^-?\d+$/.test(floor)) return floor
  const n = Number(floor)
  return n < 0 ? `지하 ${-n}층` : `${n}층`
}

function dealAmount(deal: MarketDeal): string {
  if (deal.kind === 'sale') return formatWon(deal.price)
  if (deal.kind === 'jeonse') return formatWon(deal.deposit)
  return `${formatWon(deal.deposit)} / 월 ${formatWon(deal.monthly_rent)}`
}

/**
 * 1절 아래: 국토교통부 실거래로 본 시세와 보증금. 시세는 검사 입력에도 들어가 R5가 쓴다.
 * 판단은 하지 않고, 이 집 보증금과 주변 중간값의 차이만 숫자로 보여 준다.
 */
function MarketBlock({
  insight,
  deposit,
  monthlyRent,
}: {
  insight: MarketInsight
  deposit: number | null
  monthlyRent: number | null
}) {
  if (insight.status !== 'ok') {
    return (
      <div className="market-block">
        <h3>실거래로 본 시세와 보증금</h3>
        <p className="muted">{insight.message ?? '실거래 정보를 찾지 못했어요.'}</p>
      </div>
    )
  }
  const monthly = (monthlyRent ?? 0) > 0
  const rent = monthly ? insight.monthly_deposit : insight.jeonse
  const where = [insight.area_name, insight.housing_type, insight.period ? formatPeriod(insight.period) : null]
    .filter(Boolean)
    .join(' · ')
  return (
    <div className="market-block">
      <h3>실거래로 본 시세와 보증금</h3>
      <p className="muted">{where} 국토교통부 실거래가</p>
      <dl className="market-summary">
        <div>
          <dt>시세 (매매)</dt>
          <dd>
            {insight.sale ? (
              <>
                {formatWon(insight.sale.median)} <span className="muted">{statsText(insight.sale)}</span>
              </>
            ) : (
              <span className="muted">{insight.housing_type === '단독다가구' ? '건물 단위 거래라 보지 않아요' : '찾지 못했어요'}</span>
            )}
          </dd>
        </div>
        <div>
          <dt>{monthly ? '주변 월세 보증금' : '주변 전세 보증금'}</dt>
          <dd>
            {rent ? (
              <>
                {formatWon(rent.median)} <span className="muted">{statsText(rent)}</span>
              </>
            ) : (
              <span className="muted">찾지 못했어요</span>
            )}
          </dd>
        </div>
        {monthly && insight.monthly_rent && (
          <div>
            <dt>주변 월세</dt>
            <dd>
              월 {formatWon(insight.monthly_rent.median)} <span className="muted">중간값</span>
            </dd>
          </div>
        )}
        {/* 전세는 보증금끼리 비교한다. 월세는 보증금과 월세를 함께 봐야 해서 나란히 두기만 한다 */}
        {!monthly && deposit !== null && deposit > 0 && rent && (
          <div>
            <dt>이 집 보증금</dt>
            <dd>
              {formatWon(deposit)} <span className="muted">{gapText(deposit, rent.median)}</span>
            </dd>
          </div>
        )}
        {monthly && deposit !== null && deposit > 0 && (
          <div>
            <dt>이 집</dt>
            <dd>
              보증금 {formatWon(deposit)} / 월 {formatWon(monthlyRent)}
            </dd>
          </div>
        )}
      </dl>
      {insight.deals.length > 0 && (
        <div className="table-scroll">
          <table className="deal-table">
            <caption className="visually-hidden">찾은 실거래 (같은 건물 먼저, 최근 순)</caption>
            <thead>
              <tr>
                <th scope="col">계약일</th>
                <th scope="col">구분</th>
                <th scope="col">건물</th>
                <th scope="col">층·면적</th>
                <th scope="col" className="num">
                  금액
                </th>
              </tr>
            </thead>
            <tbody>
              {insight.deals.map((deal, i) => (
                <tr key={`${deal.kind}-${deal.date}-${i}`}>
                  <td>{formatDate(deal.date)}</td>
                  <td>
                    {DEAL_KIND[deal.kind]}
                    {deal.contract_type === '갱신' ? ' (갱신)' : ''}
                  </td>
                  <td>
                    {deal.name ?? '—'}
                    {deal.same_building && <span className="tag">같은 건물</span>}
                  </td>
                  <td>{[floorText(deal.floor), formatArea(deal.area_m2)].filter(Boolean).join(' · ')}</td>
                  <td className="num">{dealAmount(deal)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {insight.notes.map((note) => (
        <p key={note} className="muted mt-1">
          {note}
        </p>
      ))}
    </div>
  )
}

const PART_MARKS = ['가', '나', '다']

/**
 * 3절: 계약서 수정 요청서. 계약서가 없으면 서버가 제목을 "계약 전 요청서"로 보낸다.
 * [복사]는 amendment.text 전체, [인쇄]는 이 절만 A4로 인쇄한다 (styles.css의 @media print).
 */
function AmendmentSection({
  number,
  amendment,
  address,
  date,
  hasContract,
  onCompare,
}: {
  number: number
  amendment: Amendment
  address: string | null
  date: string
  /** 지금 검사에 계약서가 있었는지. 없으면(계약 전 요청서) 고친 계약서와 비교할 수 없다 */
  hasContract: boolean
  onCompare: () => void
}) {
  // 계약서로 검사했고, 고칠 곳이나 특약이 있어야 "고친 계약서"를 비교할 수 있다
  const canCompare = hasContract && (amendment.fixes.length > 0 || amendment.terms.length > 0)
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
                <strong>{fix.item}</strong>: {fix.current ? maskPersonal(fix.current) : '없음'} →{' '}
                {maskPersonal(fix.proposed)}
              </p>
              {fix.reason && <p className="muted">이유: {maskPersonal(fix.reason)}</p>}
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
          <CopyButton text={maskPersonal(amendment.text)} label={`${amendment.title} 복사`} />
          <button type="button" className="link" onClick={() => window.print()}>
            인쇄
          </button>
        </span>
      </div>
      <dl className="rows print-only">
        {address && (
          <div className="row">
            <dt>대상</dt>
            <dd>{keepTogether(maskPersonal(address))}</dd>
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
      {canCompare && (
        <p className="no-print">
          요청서대로 고친 계약서를 받았나요?{' '}
          <button type="button" className="link" onClick={onCompare}>
            수정된 계약서 올리기
          </button>
        </p>
      )}
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
          {result.name || maskPersonal(result.title)}
        </h3>
      </div>
      <div className="finding-body">
        {result.title && result.name && <p>{maskPersonal(withPeriod(result.title))}</p>}
        {result.summary && <p>{maskPersonal(result.summary)}</p>}
        {result.action && (
          <p>
            <span className="finding-action-label">할 일:</span> {maskPersonal(result.action)}
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
  onRecheck,
}: {
  number: number
  items: ChecklistItem[]
  address: string | null
  onRecheck: () => void
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

  const hasBalanceRow = groups.some((g) => g.when === '잔금일')
  const recheckLink = (
    <p>
      <button type="button" className="link" onClick={onRecheck}>
        잔금 전 재확인
      </button>
    </p>
  )

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
                {/* "잔금 보내기 전 등기부 다시 떼기" 바로 옆: 오늘 뗀 등기부로 계약 후 재확인 */}
                {group.when === '잔금일' && recheckLink}
              </dd>
            </div>
          )
        })}
      </dl>
      {!hasBalanceRow && recheckLink}
    </section>
  )
}
