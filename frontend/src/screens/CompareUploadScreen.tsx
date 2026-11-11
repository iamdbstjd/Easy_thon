import { useRef, useState } from 'react'
import { FilePicker } from '../components/FilePicker'
import { prepareContractFile } from '../lib/files'
import { useScreenFocus } from '../lib/useScreenFocus'

/**
 * 요청서대로 고친 계약서 하나만 올린다. 등기부·직접 입력·공공 데이터·기준일은
 * 방금 검사에 쓴 값(메모리의 CheckRequest)을 그대로 쓴다. 아무것도 저장하지 않는다.
 */
export function CompareUploadScreen({
  file,
  setFile,
  onSubmit,
  onBack,
  onHome,
}: {
  file: File | null
  setFile: (file: File | null) => void
  onSubmit: () => void
  /** 검토서(S5)로 돌아가기 */
  onBack: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const pickId = useRef(0)

  async function pick(picked: File) {
    const id = ++pickId.current
    setError(null)
    setBusy(true)
    const result = await prepareContractFile(picked)
    if (id !== pickId.current) return
    setBusy(false)
    if ('error' in result) setError(result.error)
    else setFile(result.file)
  }

  const ready = file !== null && !busy

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          수정된 계약서 올리기
        </h1>
        <p>고친 계약서를 올리면 수정 전 계약서와 비교해요. 등기부와 직접 입력한 값은 방금 검사에 쓴 것을 그대로 써요.</p>
      </div>

      <div className="rows mt-3">
        <FilePicker
          label="수정된 계약서"
          required
          accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf"
          file={file}
          busy={busy}
          error={error}
          describedBy="compare-file-note"
          onPick={pick}
          onClear={() => {
            pickId.current += 1
            setError(null)
            setBusy(false)
            setFile(null)
          }}
        />
      </div>
      <p id="compare-file-note" className="muted mt-1">
        사진이나 PDF(10MB 이하)
      </p>

      <p className="mt-4">문서는 AI 분석을 위해 외부로 전송되고, 저장되지 않아요.</p>

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
          수정된 계약서를 고르면 비교할 수 있어요.
        </p>
      )}
    </>
  )
}
