import { useEffect, useId, useRef, useState } from 'react'
import { byFileName, MAX_FILES, prepareUploadFile, UPLOAD_ACCEPT } from '../lib/files'
import type { DocKind } from '../lib/files'
import { newPick } from '../state/contract'
import type { FilePick } from '../state/contract'
import { PhotoMasker } from './PhotoMasker'

/** 고른 파일 목록 바꾸기. 사진을 줄이는 동안 목록이 바뀔 수 있어 늘 최신 목록에서 고친다 */
export type PicksUpdate = (update: (picks: FilePick[]) => FilePick[]) => void

/**
 * 서류 파일 고르기 한 줄 (S2·S6·수정된 계약서 올리기). 등기부·계약서 공통.
 * - PDF나 사진을 여러 개 고를 수 있다 (한 서류를 쪽마다 찍었거나 나눠 저장한 경우). 고른 순서대로 붙고,
 *   한 번에 여러 개를 고르면 이름 순서로 붙인다. 서버에도 이 순서대로 보낸다.
 * - 사진은 형식과 상관없이 줄여서 JPEG로 다시 저장한다. maskable이면 사진마다 보내기 전에 가릴 수 있다.
 * - 기본 파일 입력은 숨기고, "파일 고르기" 글자 링크(label)로 연다. 형식 안내는 describedBy로 연결한다.
 */
export function DocFilesField({
  label,
  doc,
  required,
  maskable,
  picks,
  onChange,
  onBusyChange,
  describedBy,
  hint,
}: {
  label: string
  doc: DocKind
  required: boolean
  /** 사진을 보내기 전에 가릴 수 있게 한다 (계약서) */
  maskable: boolean
  picks: FilePick[]
  onChange: PicksUpdate
  /** 사진을 줄이는 동안 true (그동안은 보낼 수 없다) */
  onBusyChange: (busy: boolean) => void
  /** 형식 안내 문장의 id */
  describedBy?: string
  /** 파일을 고르기 전에만 보이는 안내 한 줄 */
  hint?: string
}) {
  const id = useId()
  const labelId = `${id}-label`
  const pickId = `${id}-pick`
  const errorId = `${id}-error`
  const hintId = `${id}-hint`
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [maskOpen, setMaskOpen] = useState<string | null>(null)
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

  async function add(selected: File[]) {
    const ordered = byFileName(selected)
    const taken = ordered.slice(0, Math.max(0, MAX_FILES - picks.length))
    const problems: string[] = ordered.length > taken.length ? [`파일은 ${MAX_FILES}개까지 올릴 수 있어요.`] : []
    if (taken.length === 0) {
      setErrors(problems)
      return
    }
    const seq = ++pickSeq.current
    setErrors([])
    updateBusy(true)
    const added: FilePick[] = []
    // 큰 사진 여러 장을 한꺼번에 열면 메모리가 모자랄 수 있어 하나씩 줄인다
    for (const file of taken) {
      const result = await prepareUploadFile(file, doc)
      if (seq !== pickSeq.current) return
      if ('error' in result) problems.push(taken.length > 1 ? `${file.name}: ${result.error}` : result.error)
      else added.push(newPick(result.file, result.kind, maskable))
    }
    updateBusy(false)
    setErrors(problems)
    if (added.length > 0) onChange((current) => [...current, ...added])
  }

  function remove(pick: FilePick) {
    if (maskOpen === pick.id) setMaskOpen(null)
    setErrors([])
    onChange((current) => current.filter((p) => p.id !== pick.id))
  }

  function setMarks(pick: FilePick, marks: FilePick['marks']) {
    onChange((current) => current.map((p) => (p.id === pick.id ? { ...p, marks } : p)))
  }

  const hasFiles = picks.length > 0
  const numbered = picks.length > 1
  const canMask = (pick: FilePick) => maskable && pick.kind === 'photo'
  const maskablePhotos = picks.some((p) => canMask(p) && p.source)
  const hasPdf = maskable && picks.some((p) => p.kind === 'pdf')

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
          multiple
          accept={UPLOAD_ACCEPT}
          disabled={busy}
          aria-labelledby={`${labelId} ${pickId}`}
          aria-describedby={
            [hint && !hasFiles ? hintId : null, describedBy, errors.length > 0 ? errorId : null]
              .filter(Boolean)
              .join(' ') || undefined
          }
          onChange={(e) => {
            const selected = Array.from(e.target.files ?? [])
            // 같은 파일을 다시 골라도 onChange가 오도록 비운다.
            e.target.value = ''
            if (selected.length > 0) void add(selected)
          }}
        />
        {hasFiles && (
          <ol className="file-list" aria-label={`고른 ${label} 파일`}>
            {picks.map((pick, i) => {
              const maskId = `${id}-mask-${pick.id}`
              const open = maskOpen === pick.id && pick.source !== null
              return (
                <li key={pick.id}>
                  <div className="file-line">
                    {numbered && <span className="file-order">{i + 1}</span>}
                    <span className="file-name">{pick.file.name}</span>
                    {canMask(pick) && pick.source && (
                      <button
                        type="button"
                        className="link"
                        aria-expanded={open}
                        aria-controls={maskId}
                        onClick={() => setMaskOpen((current) => (current === pick.id ? null : pick.id))}
                      >
                        {open ? '가리기 접기' : '보내기 전에 가리기'}
                      </button>
                    )}
                    {canMask(pick) && pick.source && !open && pick.marks.length > 0 && (
                      <span className="muted">가린 곳 {pick.marks.length}군데</span>
                    )}
                    <button
                      type="button"
                      className="link"
                      aria-label={`${pick.file.name} 빼기`}
                      onClick={() => remove(pick)}
                    >
                      빼기
                    </button>
                  </div>
                  {open && pick.source && (
                    <PhotoMasker
                      id={maskId}
                      source={pick.source}
                      marks={pick.marks}
                      onChange={(marks) => setMarks(pick, marks)}
                    />
                  )}
                  {canMask(pick) && !pick.source && (
                    <p className="form-hint">
                      {pick.marks.length > 0
                        ? `가린 곳 ${pick.marks.length}군데를 가리고 보냈어요.`
                        : '가리지 않고 보냈어요.'}{' '}
                      다시 가리려면 사진을 다시 골라 주세요.
                    </p>
                  )}
                </li>
              )
            })}
          </ol>
        )}
        <div className="file-line" aria-live="polite">
          {busy ? (
            <span className="muted">파일 확인 중</span>
          ) : picks.length < MAX_FILES ? (
            <label htmlFor={id} id={pickId} className="link file-pick">
              {hasFiles ? '파일 더 고르기' : '파일 고르기'}
            </label>
          ) : (
            <span className="muted" id={pickId}>
              파일은 {MAX_FILES}개까지예요
            </span>
          )}
        </div>
        {hint && !hasFiles && (
          <p id={hintId} className="form-hint">
            {hint}
          </p>
        )}
        {maskablePhotos && maskOpen === null && (
          <p className="form-hint">주민등록번호·전화번호·서명·계좌번호는 보내기 전에 사진마다 가릴 수 있어요.</p>
        )}
        {hasPdf && (
          <p className="form-hint">PDF는 가릴 수 없어요. 가리고 싶은 곳이 있으면 그 쪽을 사진으로 찍어 올려 주세요.</p>
        )}
        {errors.length > 0 && (
          <div id={errorId}>
            {errors.map((message) => (
              <p key={message} className="form-error" role="alert">
                {message}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
