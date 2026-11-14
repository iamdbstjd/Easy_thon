import { useEffect, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { health } from '../api/client'
import type { HealthResponse } from '../api/types'
import { ConsentNotice } from '../components/ConsentNotice'
import { ToggleGroup } from '../components/Disclosure'
import { DocFilesField } from '../components/DocFilesField'
import { DateField, MoneyField, TextField } from '../components/fields'
import { IROS_URL } from '../content/static'
import { MAX_TOTAL_BYTES, totalBytes } from '../lib/files'
import { useScreenFocus } from '../lib/useScreenFocus'
import { hasManualValues } from '../state/upload'
import type { ManualDraft, UploadDraft } from '../state/upload'

type ServerState = HealthResponse | 'offline' | null

/** S2 업로드 */
export function UploadScreen({
  draft,
  setDraft,
  onSubmit,
  onHome,
  onPrivacy,
}: {
  draft: UploadDraft
  setDraft: Dispatch<SetStateAction<UploadDraft>>
  onSubmit: () => void
  onHome: () => void
  /** 개인정보 처리 안내 */
  onPrivacy: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [registryBusy, setRegistryBusy] = useState(false)
  const [contractBusy, setContractBusy] = useState(false)
  const [server, setServer] = useState<ServerState>(null)
  const [manualOpenAtStart] = useState(() => hasManualValues(draft.manual))

  useEffect(() => {
    const controller = new AbortController()
    health(controller.signal).then(setServer, () => {
      if (!controller.signal.aborted) setServer('offline')
    })
    return () => controller.abort()
  }, [])

  function setManual(key: keyof ManualDraft) {
    return (value: string) => setDraft((d) => ({ ...d, manual: { ...d.manual, [key]: value } }))
  }

  const tooBig = totalBytes([...draft.registry, ...draft.contract].map((p) => p.file)) > MAX_TOTAL_BYTES
  const hasRegistry = draft.registry.length > 0
  const canSubmit = hasRegistry && !registryBusy && !contractBusy && !tooBig && draft.consent

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          서류 올리기
        </h1>
        {server === 'offline' && (
          <p className="form-error" role="status">
            서버에 연결하지 못했어요. 지금은 분석이 되지 않을 수 있어요.
          </p>
        )}
        {server !== null && server !== 'offline' && !server.ai_ready && (
          <p className="form-error" role="status">
            지금은 서류를 읽을 수 없어요. 처음 화면의 예시 결과는 볼 수 있어요.
          </p>
        )}
      </div>

      <div className="rows mt-3">
        <DocFilesField
          label="등기부등본"
          doc="registry"
          required
          maskable={false}
          picks={draft.registry}
          describedBy="file-note"
          onChange={(update) => setDraft((d) => ({ ...d, registry: update(d.registry) }))}
          onBusyChange={setRegistryBusy}
        />
        <DocFilesField
          label="계약서"
          doc="contract"
          required={false}
          maskable
          picks={draft.contract}
          describedBy="file-note"
          hint="계약서를 함께 올리면 임대인·호수·특약을 등기부와 대조해요."
          onChange={(update) => setDraft((d) => ({ ...d, contract: update(d.contract) }))}
          onBusyChange={setContractBusy}
        />
      </div>
      <p id="file-note" className="muted mt-1">
        PDF나 사진(JPG·PNG 등). 여러 장이면 한 번에 골라도 돼요. 파일 하나 10MB, 서류마다 30쪽까지
      </p>
      {tooBig && (
        <p className="form-error" role="alert">
          올린 파일이 모두 합쳐 20MB를 넘어요. 파일 수를 줄여 주세요.
        </p>
      )}

      <div className="mt-2">
        <ToggleGroup label="계약서가 아직 없으면 직접 입력" defaultOpen={manualOpenAtStart}>
          <div className="rows-continued">
            <MoneyField label="보증금" value={draft.manual.deposit} onChange={setManual('deposit')} />
            <MoneyField
              label="월세"
              value={draft.manual.monthly_rent}
              onChange={setManual('monthly_rent')}
            />
            <DateField
              label="계약 예정일"
              value={draft.manual.contract_date}
              onChange={setManual('contract_date')}
            />
            <TextField
              label="임대인 이름"
              value={draft.manual.landlord_name}
              onChange={setManual('landlord_name')}
            />
            <MoneyField
              label="선순위 보증금"
              gloss="먼저 들어온 세입자 보증금"
              value={draft.manual.prior_deposits}
              onChange={setManual('prior_deposits')}
            />
          </div>
        </ToggleGroup>
      </div>

      <section className="sub-section" aria-labelledby="iros-title">
        <h2 id="iros-title">등기부 받는 방법</h2>
        <ol className="num-list">
          <li>
            <a className="tap-target" href={IROS_URL} target="_blank" rel="noopener noreferrer">
              인터넷등기소
            </a>
            에서 주소로 등기부 찾기
          </li>
          <li>'현재 유효사항'으로 열람</li>
          <li>열람 화면에서 PDF로 저장</li>
        </ol>
        <p className="muted mt-1">종이로 받은 등기부는 쪽마다 사진으로 찍어 한 번에 올려도 돼요.</p>
      </section>

      <ConsentNotice
        checked={draft.consent}
        onChange={(consent) => setDraft((d) => ({ ...d, consent }))}
        onPrivacy={onPrivacy}
      />

      <div className="actions mt-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!canSubmit}
          aria-describedby={canSubmit ? undefined : 'submit-reason'}
          onClick={onSubmit}
        >
          분석하기
        </button>
        <button type="button" className="link" onClick={onHome}>
          처음으로
        </button>
      </div>
      {!canSubmit && (
        <p id="submit-reason" className="visually-hidden">
          {submitReason(hasRegistry, draft.consent, tooBig)}
        </p>
      )}
    </>
  )
}

function submitReason(hasRegistry: boolean, consent: boolean, tooBig: boolean): string {
  if (!hasRegistry && !consent) return '등기부등본을 고르고 위 내용을 확인하면 분석할 수 있어요.'
  if (!hasRegistry) return '등기부등본을 고르면 분석할 수 있어요.'
  if (tooBig) return '올린 파일이 모두 합쳐 20MB를 넘어요.'
  if (!consent) return '위 내용을 확인하면 분석할 수 있어요.'
  return '사진을 준비하고 있어요.'
}
