import { Fragment, useEffect, useId, useState } from 'react'
import type { CheckRequest, Entry } from '../api/types'
import { Excerpt } from '../components/Excerpt'
import {
  DateField,
  DateTimeField,
  GrowingTextField,
  MoneyField,
  ReadRow,
  TextField,
} from '../components/fields'
import { MARKET_METHOD_LABEL } from '../content/labels'
import { formatArea, formatDateShort, formatPeriod, formatWon, groupNumber } from '../lib/format'
import { maskIds } from '../lib/mask'
import { useScreenFocus } from '../lib/useScreenFocus'
import { formFromRequest, missingField, requestFromForm } from '../state/review'
import type { ReviewForm } from '../state/review'

const LIVE_NOTE = 'AI가 읽은 내용이에요. 틀린 곳이 있으면 고친 뒤 검사하세요.'
const DEMO_NOTE =
  '미리 준비한 예시 서류의 내용이에요. 값을 바꿔 검사하면 결과가 어떻게 달라지는지 볼 수 있어요.'
const PRIOR_GLOSS = '먼저 들어온 세입자 보증금'
const MARKET_GLOSS = '매매 가격'

/** S4 내용 확인·수정 */
export function ReviewScreen({
  request,
  checking,
  focusRules,
  onCheck,
  onHome,
}: {
  request: CheckRequest
  checking: boolean
  /** [빠진 내용 채우기]로 왔을 때: 확인하지 못한 규칙 ID. 관련된 첫 빈 칸으로 이동한다 */
  focusRules: string[] | null
  onCheck: (req: CheckRequest) => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [initial] = useState(() => formFromRequest(request))
  const [form, setForm] = useState<ReviewForm>(initial)

  // 제목에 초점을 둔 뒤(useScreenFocus), 빠진 칸이 있으면 그 칸으로 옮긴다.
  // focusRules는 S4에 들어올 때 정해지고, 검사를 시작하면 null이 되므로 실제로는 처음 한 번만 움직인다.
  const hasContract = request.contract !== null
  useEffect(() => {
    if (!focusRules || focusRules.length === 0) return
    const key = missingField(focusRules, initial, hasContract)
    const el = key ? document.querySelector<HTMLElement>(`[data-field="${key}"]`) : null
    if (!el) return
    el.focus({ preventScroll: true })
    el.scrollIntoView({ block: 'center' })
  }, [focusRules, initial, hasContract])

  function bind(key: keyof ReviewForm) {
    return {
      value: form[key],
      onChange: (value: string) => setForm((f) => ({ ...f, [key]: value })),
      fieldKey: key,
    }
  }

  const { registry, contract, building, market } = request
  const floorAndArea = [registry.unit.floor, formatArea(registry.unit.area_m2)]
    .filter(Boolean)
    .join(' · ')

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          읽은 내용 확인
        </h1>
        <p>{request.mode === 'demo' ? DEMO_NOTE : LIVE_NOTE}</p>
        {registry.unreadable.length > 0 && (
          <div>
            <p>
              <strong>읽지 못한 부분</strong>
            </p>
            <ul className="dot-list">
              {registry.unreadable.map((text, i) => (
                <li key={i}>{maskIds(text)}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <section className="doc-section" aria-labelledby="review-registry">
        <h2 id="review-registry">등기부</h2>
        <div className="rows">
          <ReadRow label="종류">{registry.registry_type ?? '읽지 못함'}</ReadRow>
          {registry.building_name && <ReadRow label="건물 명칭">{registry.building_name}</ReadRow>}
          {floorAndArea && <ReadRow label="층·면적">{floorAndArea}</ReadRow>}
          <GrowingTextField label="소재지번" {...bind('regAddressJibun')} />
          <GrowingTextField label="도로명주소" {...bind('regAddressRoad')} />
          <TextField label="동" narrow {...bind('regDong')} />
          <TextField label="호" narrow {...bind('regHo')} />
          <DateTimeField label="열람 일시" {...bind('regViewedAt')} />
          <ReadRow label="건물 용도">
            {registry.building_use_lines.length > 0 ? (
              <ul className="row-lines">
                {registry.building_use_lines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            ) : (
              '읽지 못함'
            )}
          </ReadRow>
        </div>
      </section>

      <section className="doc-section" aria-labelledby="review-gapgu">
        <h2 id="review-gapgu">
          갑구 <span className="heading-note">소유권</span>
        </h2>
        <EntryTable entries={registry.gapgu} caption="갑구 (소유권에 관한 사항)" />
      </section>

      <section className="doc-section" aria-labelledby="review-eulgu">
        <h2 id="review-eulgu">
          을구 <span className="heading-note">근저당·전세권 등 소유권 외 권리</span>
        </h2>
        <EntryTable entries={registry.eulgu} caption="을구 (소유권 외의 권리에 관한 사항)" />
      </section>

      {contract ? (
        <>
          <section className="doc-section" aria-labelledby="review-contract">
            <h2 id="review-contract">계약서</h2>
            <div className="rows">
              {contract.lease_type && <ReadRow label="계약 종류">{contract.lease_type}</ReadRow>}
              {contract.agent_name && <ReadRow label="대리인">{maskIds(contract.agent_name)}</ReadRow>}
              <GrowingTextField label="임대인" {...bind('conLandlords')} />
              <GrowingTextField label="소재지" {...bind('conAddress')} />
              <TextField label="동" narrow {...bind('conDong')} />
              <TextField label="호" narrow {...bind('conHo')} />
              <MoneyField label="보증금" {...bind('conDeposit')} />
              <MoneyField label="월세" {...bind('conMonthlyRent')} />
              <DateField label="계약일" {...bind('conContractDate')} />
              <DateField label="잔금일" {...bind('conBalanceDate')} />
              <ReadRow label="특약">
                {contract.special_terms.length > 0 ? (
                  <ol className="num-list">
                    {contract.special_terms.map((term, i) => (
                      <li key={i}>{term}</li>
                    ))}
                  </ol>
                ) : (
                  '없음'
                )}
              </ReadRow>
            </div>
          </section>

          <section className="doc-section" aria-labelledby="review-extra">
            <h2 id="review-extra">
              알고 있는 금액 <span className="heading-note">(선택)</span>
            </h2>
            <div className="rows">
              <MoneyField label="선순위 보증금" gloss={PRIOR_GLOSS} {...bind('manPriorDeposits')} />
              <MoneyField label="시세" gloss={MARKET_GLOSS} {...bind('manMarketPrice')} />
            </div>
          </section>
        </>
      ) : (
        <section className="doc-section" aria-labelledby="review-manual">
          <h2 id="review-manual">
            직접 입력 <span className="heading-note">(선택)</span>
          </h2>
          <div className="rows">
            <MoneyField label="보증금" {...bind('manDeposit')} />
            <MoneyField label="월세" {...bind('manMonthlyRent')} />
            <DateField label="계약 예정일" {...bind('manContractDate')} />
            <GrowingTextField label="임대인 이름" {...bind('manLandlordName')} />
            <MoneyField label="선순위 보증금" gloss={PRIOR_GLOSS} {...bind('manPriorDeposits')} />
            <MoneyField label="시세" gloss={MARKET_GLOSS} {...bind('manMarketPrice')} />
          </div>
        </section>
      )}

      {(building || market) && (
        <section className="doc-section" aria-labelledby="review-public">
          <h2 id="review-public">함께 확인한 자료</h2>
          <div className="rows">
            {building && (
              <>
                <ReadRow label="건축물 용도">{building.main_use ?? '알 수 없음'}</ReadRow>
                {building.unit_use && <ReadRow label="호실 용도">{building.unit_use}</ReadRow>}
                <ReadRow label="위반건축물">
                  {building.is_violating === null ? '알 수 없음' : building.is_violating ? '있음' : '없음'}
                </ReadRow>
              </>
            )}
            {market && market.price !== null && (
              <ReadRow label="시세">
                {formatWon(market.price)}
                <span className="muted">
                  {' '}
                  ({MARKET_METHOD_LABEL[market.method]}
                  {market.deals > 0 ? ` ${groupNumber(market.deals)}건` : ''}
                  {market.period ? `, ${formatPeriod(market.period)}` : ''})
                </span>
              </ReadRow>
            )}
          </div>
        </section>
      )}

      <div className="sticky-actions">
        <button
          type="button"
          className="btn-primary"
          disabled={checking}
          onClick={() => onCheck(requestFromForm(request, form, initial))}
        >
          {checking ? '확인 중' : '위험 신호 검사'}
        </button>
        <button type="button" className="link" disabled={checking} onClick={onHome}>
          처음으로
        </button>
      </div>
    </>
  )
}

/** 갑구·을구 표: 순위 · 목적 · 접수일 · 권리자 · 금액, 줄마다 [원문] */
function EntryTable({ entries, caption }: { entries: Entry[]; caption: string }) {
  const baseId = useId()
  const [open, setOpen] = useState<ReadonlySet<number>>(() => new Set())

  if (entries.length === 0) return <p className="muted">기록 없음</p>

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
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          <th scope="col">순위</th>
          <th scope="col">목적</th>
          <th scope="col">접수일</th>
          <th scope="col">권리자</th>
          <th scope="col">금액</th>
          <th scope="col">
            <span className="visually-hidden">원문</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry, i) => {
          const sourceId = `${baseId}-source-${i}`
          const isOpen = open.has(i)
          return (
            <Fragment key={`${entry.rank}-${i}`}>
              <tr className={entry.is_cancelled ? 'entry-row entry-cancelled' : 'entry-row'}>
                <td className="c-rank c-nowrap">{entry.rank}</td>
                <td className="c-purpose">
                  <span className="entry-purpose">{entry.purpose || '목적 없음'}</span>
                  {entry.is_cancelled && ' (말소)'}
                  {/* 원인은 목적에 이미 들어 있지 않을 때만 덧붙인다 ("소유권이전, 신탁" + "신탁" → 생략) */}
                  {entry.cause && !entry.purpose.includes(entry.cause) && (
                    <span className="muted"> · {entry.cause}</span>
                  )}
                </td>
                <td className="c-nowrap" data-label="접수일">
                  {formatDateShort(entry.received_at)}
                </td>
                <td data-label="권리자">{entry.holders.map(maskIds).join(', ')}</td>
                <td className="c-nowrap" data-label="금액">
                  {entry.amount !== null ? formatWon(entry.amount) : ''}
                </td>
                <td className="c-source">
                  {entry.source_text && (
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
                <td colSpan={6}>
                  {isOpen && (
                    <Excerpt
                      caption={entry.page ? `등기부 ${entry.page}쪽` : '등기부'}
                      text={entry.source_text}
                    />
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
