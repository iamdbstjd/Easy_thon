import { useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { RecheckRequest } from '../api/types'
import { FilePicker } from '../components/FilePicker'
import { DateField, DateTimeField, ReadRow } from '../components/fields'
import { checkRegistryFile, prepareContractFile } from '../lib/files'
import { keepTogether } from '../lib/keepTogether'
import { maskIds } from '../lib/mask'
import { useScreenFocus } from '../lib/useScreenFocus'
import { recheckFormFrom, recheckRequestFrom } from '../state/recheck'
import type { RecheckCarry, RecheckForm, RecheckUpload } from '../state/recheck'

const INTRO = '잔금을 보내기 전과 입주 다음 날, 오늘 뗀 등기부를 계약서와 맞춰 봐요.'

/**
 * S6 계약 후 재확인: 오늘 뗀 등기부(필수)와 계약서(필수, 앞 화면에서 이어 왔으면 생략)를 올린다.
 * 아무것도 저장하지 않는다. 계약서는 같은 화면 흐름의 상태로만 이어 받는다.
 */
export function RecheckUploadScreen({
  carry,
  upload,
  setUpload,
  onSubmit,
  onHome,
}: {
  carry: RecheckCarry | null
  upload: RecheckUpload
  setUpload: Dispatch<SetStateAction<RecheckUpload>>
  onSubmit: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [registryError, setRegistryError] = useState<string | null>(null)
  const [contractError, setContractError] = useState<string | null>(null)
  const [contractBusy, setContractBusy] = useState(false)
  const contractPick = useRef(0)

  async function pickRegistry(file: File) {
    setRegistryError(null)
    const error = await checkRegistryFile(file)
    if (error) setRegistryError(error)
    else setUpload((u) => ({ ...u, registry: file }))
  }

  async function pickContract(file: File) {
    const pick = ++contractPick.current
    const isCurrent = () => pick === contractPick.current
    setContractError(null)
    setContractBusy(true)
    const result = await prepareContractFile(file)
    if (!isCurrent()) return
    setContractBusy(false)
    if ('error' in result) setContractError(result.error)
    else setUpload((u) => ({ ...u, contract: result.file }))
  }

  const ready = upload.registry !== null && (carry !== null || upload.contract !== null) && !contractBusy

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          계약 후 재확인
        </h1>
        <p>{INTRO}</p>
      </div>

      <div className="rows mt-3">
        <FilePicker
          label="오늘 뗀 등기부"
          required
          accept="application/pdf,.pdf"
          file={upload.registry}
          error={registryError}
          describedBy="recheck-file-note"
          onPick={pickRegistry}
          onClear={() => {
            setRegistryError(null)
            setUpload((u) => ({ ...u, registry: null }))
          }}
        />
        {carry ? (
          <ReadRow label="계약서">
            <p>앞 화면의 계약서를 그대로 써요.</p>
            {carry.contract.address && (
              <p className="muted">{keepTogether(maskIds(carry.contract.address))}</p>
            )}
          </ReadRow>
        ) : (
          <FilePicker
            label="계약서"
            required
            accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf"
            file={upload.contract}
            busy={contractBusy}
            error={contractError}
            describedBy="recheck-file-note"
            onPick={pickContract}
            onClear={() => {
              contractPick.current += 1
              setContractError(null)
              setContractBusy(false)
              setUpload((u) => ({ ...u, contract: null }))
            }}
          />
        )}
      </div>
      <p id="recheck-file-note" className="muted mt-1">
        {carry
          ? '등기부는 PDF(10MB·30쪽 이하)'
          : '등기부는 PDF(10MB·30쪽 이하), 계약서는 사진이나 PDF(10MB 이하)'}
      </p>

      <p className="mt-4">문서는 AI 분석을 위해 외부로 전송되고, 저장되지 않아요.</p>

      <div className="actions mt-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!ready}
          aria-describedby={ready ? undefined : 'recheck-reason'}
          onClick={onSubmit}
        >
          서류 읽기
        </button>
        <button type="button" className="link" onClick={onHome}>
          처음으로
        </button>
      </div>
      {!ready && (
        <p id="recheck-reason" className="visually-hidden">
          {carry ? '오늘 뗀 등기부를 고르면 읽을 수 있어요.' : '등기부와 계약서를 고르면 읽을 수 있어요.'}
        </p>
      )}
    </>
  )
}

/** S6 두 번째 단계: 읽은 날짜를 한 줄 표로 확인하고 고친다 (S4보다 짧게) */
export function RecheckConfirmScreen({
  draft,
  checking,
  onRecheck,
  onReselect,
  onHome,
}: {
  draft: RecheckRequest
  checking: boolean
  onRecheck: (req: RecheckRequest) => void
  onReselect: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [initial] = useState(() => recheckFormFrom(draft))
  const [form, setForm] = useState<RecheckForm>(initial)

  function bind(key: keyof RecheckForm) {
    return { value: form[key], onChange: (value: string) => setForm((f) => ({ ...f, [key]: value })) }
  }

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          계약 후 재확인
        </h1>
        <p>읽은 날짜를 확인하세요. 틀린 곳이 있으면 고친 뒤 재확인하세요.</p>
      </div>

      <div className="rows mt-3">
        <DateField label="계약일" {...bind('contractDate')} />
        <DateField label="잔금일" {...bind('balanceDate')} />
        <DateField label="입주일" {...bind('moveInDate')} />
        <DateTimeField label="등기부 열람 일시" {...bind('viewedAt')} />
      </div>

      <div className="actions">
        <button
          type="button"
          className="btn-primary"
          disabled={checking}
          onClick={() => onRecheck(recheckRequestFrom(draft, form, initial))}
        >
          {checking ? '확인 중' : '재확인'}
        </button>
        <button type="button" className="link" disabled={checking} onClick={onReselect}>
          서류 다시 고르기
        </button>
        <button type="button" className="link" disabled={checking} onClick={onHome}>
          처음으로
        </button>
      </div>
    </>
  )
}
