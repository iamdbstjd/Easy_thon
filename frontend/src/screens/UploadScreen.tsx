import { useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { health } from '../api/client'
import type { HealthResponse } from '../api/types'
import { ToggleGroup } from '../components/Disclosure'
import { FilePicker } from '../components/FilePicker'
import { DateField, MoneyField, TextField } from '../components/fields'
import { IROS_URL } from '../content/static'
import {
  hasPdfHeader,
  isImageFile,
  isPdfFile,
  MAX_FILE_BYTES,
  resizeContractPhoto,
} from '../lib/files'
import { useScreenFocus } from '../lib/useScreenFocus'
import { hasManualValues } from '../state/upload'
import type { ManualDraft, UploadDraft } from '../state/upload'

type ServerState = HealthResponse | 'offline' | null

const TOO_BIG = '10MB 이하 파일만 올릴 수 있어요.'

/** S2 업로드 */
export function UploadScreen({
  draft,
  setDraft,
  onSubmit,
  onHome,
}: {
  draft: UploadDraft
  setDraft: Dispatch<SetStateAction<UploadDraft>>
  onSubmit: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [registryError, setRegistryError] = useState<string | null>(null)
  const [contractError, setContractError] = useState<string | null>(null)
  const [contractBusy, setContractBusy] = useState(false)
  const [server, setServer] = useState<ServerState>(null)
  const [manualOpenAtStart] = useState(() => hasManualValues(draft.manual))
  const contractPick = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    health(controller.signal).then(setServer, () => {
      if (!controller.signal.aborted) setServer('offline')
    })
    return () => controller.abort()
  }, [])

  async function pickRegistry(file: File) {
    setRegistryError(null)
    if (!isPdfFile(file)) {
      setRegistryError('등기부는 PDF 파일만 올릴 수 있어요.')
      return
    }
    if (file.size > MAX_FILE_BYTES) {
      setRegistryError(`${TOO_BIG} 인터넷등기소에서 '현재 유효사항'으로 다시 열람해 보세요.`)
      return
    }
    if (!(await hasPdfHeader(file))) {
      setRegistryError('PDF 파일이 아닌 것 같아요. 인터넷등기소에서 저장한 PDF를 올려주세요.')
      return
    }
    setDraft((d) => ({ ...d, registry: file }))
  }

  async function pickContract(file: File) {
    const pick = ++contractPick.current
    const isCurrent = () => pick === contractPick.current
    setContractError(null)

    // PDF는 그대로 보낸다: 크기와 PDF 머리글만 확인한다.
    if (isPdfFile(file)) {
      if (file.size > MAX_FILE_BYTES) {
        setContractError(TOO_BIG)
        return
      }
      if (!(await hasPdfHeader(file))) {
        if (isCurrent()) setContractError('PDF 파일이 아닌 것 같아요. 다른 파일을 골라 주세요.')
        return
      }
      if (isCurrent()) setDraft((d) => ({ ...d, contract: file }))
      return
    }
    if (!isImageFile(file)) {
      setContractError('계약서는 사진(JPG·PNG·WEBP)이나 PDF만 올릴 수 있어요.')
      return
    }

    // 사진은 먼저 줄여서 다시 저장하고, 줄인 파일로 10MB를 확인한다.
    setContractBusy(true)
    try {
      const resized = await resizeContractPhoto(file)
      if (!isCurrent()) return
      if (resized.size > MAX_FILE_BYTES) {
        setContractError(TOO_BIG)
        return
      }
      setDraft((d) => ({ ...d, contract: resized }))
    } catch {
      if (isCurrent()) setContractError('사진을 열지 못했어요. 다른 사진을 골라 주세요.')
    } finally {
      if (isCurrent()) setContractBusy(false)
    }
  }

  function setManual(key: keyof ManualDraft) {
    return (value: string) => setDraft((d) => ({ ...d, manual: { ...d.manual, [key]: value } }))
  }

  const canSubmit = draft.registry !== null && !contractBusy

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
        <FilePicker
          label="등기부등본"
          required
          accept="application/pdf,.pdf"
          file={draft.registry}
          error={registryError}
          describedBy="file-note"
          onPick={pickRegistry}
          onClear={() => {
            setRegistryError(null)
            setDraft((d) => ({ ...d, registry: null }))
          }}
        />
        <FilePicker
          label="계약서"
          required={false}
          accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf"
          file={draft.contract}
          busy={contractBusy}
          error={contractError}
          describedBy="file-note"
          hint="계약서를 함께 올리면 임대인·호수·특약을 등기부와 대조해요."
          onPick={pickContract}
          onClear={() => {
            contractPick.current += 1
            setContractError(null)
            setContractBusy(false)
            setDraft((d) => ({ ...d, contract: null }))
          }}
        />
      </div>
      <p id="file-note" className="muted mt-1">
        등기부는 PDF(10MB·30쪽 이하), 계약서는 사진이나 PDF(10MB 이하)
      </p>

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
            <MoneyField
              label="시세"
              gloss="매매 가격"
              value={draft.manual.market_price}
              onChange={setManual('market_price')}
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
      </section>

      <p className="mt-4">문서는 AI 분석을 위해 외부로 전송되고, 저장되지 않아요.</p>

      <div className="actions mt-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!canSubmit}
          aria-describedby={draft.registry ? undefined : 'submit-reason'}
          onClick={onSubmit}
        >
          분석하기
        </button>
        <button type="button" className="link" onClick={onHome}>
          처음으로
        </button>
      </div>
      {!draft.registry && (
        <p id="submit-reason" className="visually-hidden">
          등기부등본을 고르면 분석할 수 있어요.
        </p>
      )}
    </>
  )
}
