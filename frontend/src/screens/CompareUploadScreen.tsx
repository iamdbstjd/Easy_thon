import { useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { ConsentNotice } from '../components/ConsentNotice'
import { DocFilesField } from '../components/DocFilesField'
import { MAX_TOTAL_BYTES, totalBytes } from '../lib/files'
import { useScreenFocus } from '../lib/useScreenFocus'
import type { FilePick } from '../state/contract'

/**
 * 요청서대로 고친 계약서만 올린다 (여러 파일이면 올린 순서대로 한 계약서). 등기부·직접 입력·공공 데이터·기준일은
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
  /** 수정된 계약서 파일들 (올린 순서) */
  contract: FilePick[]
  setContract: Dispatch<SetStateAction<FilePick[]>>
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

  const tooBig = totalBytes(contract.map((p) => p.file)) > MAX_TOTAL_BYTES
  const fileReady = contract.length > 0 && !busy && !tooBig
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
        <DocFilesField
          label="수정된 계약서"
          doc="contract"
          required
          maskable
          picks={contract}
          describedBy="compare-file-note"
          onChange={(update) => setContract((current) => update(current))}
          onBusyChange={setBusy}
        />
      </div>
      <p id="compare-file-note" className="muted mt-1">
        사진이나 PDF. 여러 장이면 한 번에 골라도 돼요. 파일 하나 10MB까지
      </p>
      {tooBig && (
        <p className="form-error" role="alert">
          올린 파일이 모두 합쳐 20MB를 넘어요. 파일 수를 줄여 주세요.
        </p>
      )}

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
          {fileReady
            ? '위 내용을 확인하면 비교할 수 있어요.'
            : tooBig
              ? '올린 파일이 모두 합쳐 20MB를 넘어요.'
              : '수정된 계약서를 고르면 비교할 수 있어요.'}
        </p>
      )}
    </>
  )
}
