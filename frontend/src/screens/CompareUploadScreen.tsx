import { useState } from 'react'
import { ConsentNotice } from '../components/ConsentNotice'
import { ContractField } from '../components/ContractField'
import { useScreenFocus } from '../lib/useScreenFocus'
import type { ContractPick } from '../state/contract'

/**
 * 요청서대로 고친 계약서 하나만 올린다. 등기부·직접 입력·공공 데이터·기준일은
 * 방금 검사에 쓴 값(메모리의 CheckRequest)을 그대로 쓴다. 아무것도 저장하지 않는다.
 */
export function CompareUploadScreen({
  contract,
  setContract,
  consent,
  setConsent,
  onSubmit,
  onBack,
  onPrivacy,
  onHome,
}: {
  contract: ContractPick | null
  setContract: (contract: ContractPick | null) => void
  consent: boolean
  setConsent: (consent: boolean) => void
  onSubmit: () => void
  /** 검토서(S5)로 돌아가기 */
  onBack: () => void
  onPrivacy: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [busy, setBusy] = useState(false)

  const fileReady = contract !== null && !busy
  const ready = fileReady && consent

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          수정된 계약서 올리기
        </h1>
        <p>고친 계약서를 올리면 수정 전 계약서와 비교해요. 등기부와 직접 입력한 값은 방금 검사에 쓴 것을 그대로 써요.</p>
      </div>

      <div className="rows mt-3">
        <ContractField
          label="수정된 계약서"
          required
          value={contract}
          describedBy="compare-file-note"
          onChange={setContract}
          onBusyChange={setBusy}
        />
      </div>
      <p id="compare-file-note" className="muted mt-1">
        사진이나 PDF(10MB 이하)
      </p>

      <ConsentNotice checked={consent} onChange={setConsent} onPrivacy={onPrivacy} />

      <div className="actions mt-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!ready}
          aria-describedby={ready ? undefined : 'compare-reason'}
          onClick={onSubmit}
        >
          비교하기
        </button>
        <button type="button" className="link" onClick={onBack}>
          검토서로 돌아가기
        </button>
        <button type="button" className="link" onClick={onHome}>
          처음으로
        </button>
      </div>
      {!ready && (
        <p id="compare-reason" className="visually-hidden">
          {fileReady ? '위 내용을 확인하면 비교할 수 있어요.' : '수정된 계약서를 고르면 비교할 수 있어요.'}
        </p>
      )}
    </>
  )
}
