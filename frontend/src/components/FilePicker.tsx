import { useId } from 'react'

/**
 * 파일 고르기 한 줄 (라벨 | 파일 이름 · 파일 고르기 · 빼기).
 * 기본 파일 입력은 숨기고, "파일 고르기" 글자 링크(label)로 연다. 크기·변환 같은 개발 정보는 보여주지 않는다.
 * 형식 안내는 파일 줄들 아래에 한 줄로 따로 두고, describedBy로 연결한다.
 */
export function FilePicker({
  label,
  required,
  accept,
  file,
  busy,
  error,
  describedBy,
  onPick,
  onClear,
}: {
  label: string
  required: boolean
  accept: string
  file: File | null
  busy?: boolean
  error?: string | null
  /** 형식 안내 문장의 id */
  describedBy?: string
  onPick: (file: File) => void
  onClear: () => void
}) {
  const id = useId()
  const labelId = `${id}-label`
  const pickId = `${id}-pick`
  const errorId = `${id}-error`

  return (
    <div className="form-row">
      <span className="form-label" id={labelId}>
        {label}
        {required ? ' (필수)' : ' (선택)'}
      </span>
      <div className="form-value">
        <input
          id={id}
          className="file-input visually-hidden"
          type="file"
          accept={accept}
          aria-labelledby={`${labelId} ${pickId}`}
          aria-describedby={[describedBy, error ? errorId : null].filter(Boolean).join(' ') || undefined}
          onChange={(e) => {
            const picked = e.target.files?.[0]
            // 같은 파일을 다시 골라도 onChange가 오도록 비운다.
            e.target.value = ''
            if (picked) onPick(picked)
          }}
        />
        <div className="file-line" aria-live="polite">
          {busy ? (
            <span className="muted">사진 처리 중</span>
          ) : (
            file && <span className="file-name">{file.name}</span>
          )}
          <label htmlFor={id} id={pickId} className="link file-pick">
            {file ? '다른 파일' : '파일 고르기'}
          </label>
          {file && !busy && (
            <button type="button" className="link" onClick={onClear}>
              빼기
            </button>
          )}
        </div>
        {error && (
          <p id={errorId} className="form-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
