import { useEffect, useId, useRef, useState } from 'react'
import { isPdfFile, prepareContractFile } from '../lib/files'
import type { ContractPick } from '../state/contract'
import { FilePicker } from './FilePicker'
import { PhotoMasker } from './PhotoMasker'

const CONTRACT_ACCEPT = 'image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf'

/**
 * 계약서 파일 고르기 한 줄 (S2·S6·수정된 계약서 올리기).
 * 사진은 줄인 뒤 보내기 전에 가릴 수 있다. PDF는 가릴 수 없다고 한 줄로 알린다.
 */
export function ContractField({
  label,
  required,
  hint,
  describedBy,
  value,
  onChange,
  onBusyChange,
}: {
  label: string
  required: boolean
  hint?: string
  describedBy?: string
  value: ContractPick | null
  onChange: (pick: ContractPick | null) => void
  /** 사진을 줄이는 동안 true (그동안은 보낼 수 없다) */
  onBusyChange: (busy: boolean) => void
}) {
  const maskId = useId()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [maskOpen, setMaskOpen] = useState(false)
  const pickSeq = useRef(0)

  // 화면을 떠나면 아직 처리 중인 사진은 버린다 (새로 시작한 화면에 끼어들지 않게)
  useEffect(() => {
    const seq = pickSeq
    return () => {
      seq.current += 1
    }
  }, [])

  function updateBusy(next: boolean) {
    setBusy(next)
    onBusyChange(next)
  }

  async function pick(file: File) {
    const seq = ++pickSeq.current
    setError(null)
    setMaskOpen(false)
    updateBusy(true)
    const result = await prepareContractFile(file)
    if (seq !== pickSeq.current) return
    updateBusy(false)
    if ('error' in result) {
      setError(result.error)
      return
    }
    const photo = !isPdfFile(file)
    onChange({ file: result.file, kind: photo ? 'photo' : 'pdf', source: photo ? result.file : null, marks: [] })
  }

  function clear() {
    pickSeq.current += 1
    setError(null)
    setMaskOpen(false)
    updateBusy(false)
    onChange(null)
  }

  const count = value?.marks.length ?? 0

  return (
    <FilePicker
      label={label}
      required={required}
      accept={CONTRACT_ACCEPT}
      file={value?.file ?? null}
      busy={busy}
      error={error}
      describedBy={describedBy}
      hint={hint}
      onPick={pick}
      onClear={clear}
    >
      {!busy && value?.kind === 'pdf' && (
        <p className="form-hint">PDF는 가릴 수 없어요. 가리고 싶은 곳이 있으면 계약서를 사진으로 찍어 올려 주세요.</p>
      )}
      {!busy && value?.kind === 'photo' && value.source && (
        <>
          {!maskOpen && (
            <p className="form-hint">주민등록번호·전화번호·서명·계좌번호는 보내기 전에 가릴 수 있어요.</p>
          )}
          <div className="file-line">
            <button
              type="button"
              className="link"
              aria-expanded={maskOpen}
              aria-controls={maskId}
              onClick={() => setMaskOpen((open) => !open)}
            >
              {maskOpen ? '가리기 접기' : '보내기 전에 가리기'}
            </button>
            {!maskOpen && count > 0 && <span className="muted">가린 곳 {count}군데</span>}
          </div>
          {maskOpen && (
            <PhotoMasker
              id={maskId}
              source={value.source}
              marks={value.marks}
              onChange={(marks) => onChange({ ...value, marks })}
            />
          )}
        </>
      )}
      {!busy && value?.kind === 'photo' && !value.source && (
        <p className="form-hint">
          {count > 0 ? `가린 곳 ${count}군데를 가리고 보냈어요.` : '가리지 않고 보냈어요.'} 다시 가리려면 사진을
          다시 골라 주세요.
        </p>
      )}
    </FilePicker>
  )
}
