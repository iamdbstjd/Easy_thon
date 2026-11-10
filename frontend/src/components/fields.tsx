import { useCallback, useEffect, useId, useLayoutEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { digitsToNumber, formatWon, groupDigits } from '../lib/format'

// 입력 칸은 모두 "라벨 | 입력" 한 줄로 그린다. 휴대폰에서는 입력이 라벨 아래로 내려간다.

interface FieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  /** 꼭 필요할 때만 쓰는 한 줄 안내 */
  hint?: ReactNode
  optional?: boolean
  disabled?: boolean
  /** 입력 칸의 data-field 값. S4에서 비어 있는 칸으로 바로 이동할 때 쓴다 */
  fieldKey?: string
  /** 라벨 아래 괄호 풀이 (예: "먼저 들어온 세입자 보증금") */
  gloss?: string
}

function Row({
  id,
  label,
  optional,
  gloss,
  children,
}: {
  id: string
  label: string
  optional?: boolean
  gloss?: string
  children: ReactNode
}) {
  return (
    <div className="form-row">
      <label className="form-label" htmlFor={id}>
        {label}
        {optional && ' (선택)'}
        {gloss && <span className="label-gloss">({gloss})</span>}
      </label>
      <div className="form-value">{children}</div>
    </div>
  )
}

function Hint({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="form-hint">
      {children}
    </p>
  )
}

/** 읽기 전용 줄 (라벨 | 값) */
export function ReadRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="form-row read-row">
      <span className="form-label">{label}</span>
      <div className="form-value form-text">{children}</div>
    </div>
  )
}

export function TextField({
  label,
  value,
  onChange,
  hint,
  optional,
  disabled,
  fieldKey,
  narrow,
}: FieldProps & { narrow?: boolean }) {
  const id = useId()
  const hintId = `${id}-hint`
  return (
    <Row id={id} label={label} optional={optional}>
      <input
        id={id}
        className={narrow ? 'input input-narrow' : 'input'}
        type="text"
        data-field={fieldKey}
        value={value}
        autoComplete="off"
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <Hint id={hintId}>{hint}</Hint>}
    </Row>
  )
}

/**
 * 길어질 수 있는 한 줄 글 (주소, 여러 명의 임대인 이름). 내용 길이에 맞춰 늘어나는 여러 줄 칸이라
 * 좁은 화면에서도 "302호"나 뒤쪽 이름이 잘리지 않는다. 값에 줄바꿈은 넣지 않는다.
 */
export function GrowingTextField({
  label,
  value,
  onChange,
  hint,
  optional,
  disabled,
  fieldKey,
}: FieldProps) {
  const id = useId()
  const hintId = `${id}-hint`
  const ref = useRef<HTMLTextAreaElement>(null)

  const fit = useCallback(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    const borders = el.offsetHeight - el.clientHeight
    el.style.height = `${el.scrollHeight + borders}px`
  }, [])

  // 값이 바뀌면 높이를 다시 잰다
  useLayoutEffect(() => {
    fit()
  }, [value, fit])

  // 화면 폭이 바뀌면 줄바꿈 위치가 달라지므로 다시 잰다
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let width = el.offsetWidth
    const observer = new ResizeObserver(() => {
      if (el.offsetWidth !== width) {
        width = el.offsetWidth
        fit()
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [fit])

  return (
    <Row id={id} label={label} optional={optional}>
      <textarea
        ref={ref}
        id={id}
        className="input"
        data-field={fieldKey}
        rows={1}
        value={value}
        autoComplete="off"
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.preventDefault()
        }}
        onChange={(e) => onChange(e.target.value.replace(/[\r\n]+/g, ' '))}
      />
      {hint && <Hint id={hintId}>{hint}</Hint>}
    </Row>
  )
}

/** 날짜 입력. 값은 "YYYY-MM-DD" 또는 "" */
export function DateField({ label, value, onChange, hint, optional, disabled, fieldKey }: FieldProps) {
  const id = useId()
  const hintId = `${id}-hint`
  return (
    <Row id={id} label={label} optional={optional}>
      <input
        id={id}
        className="input input-narrow"
        type="date"
        data-field={fieldKey}
        value={value}
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <Hint id={hintId}>{hint}</Hint>}
    </Row>
  )
}

/** 일시 입력. 값은 "YYYY-MM-DDTHH:mm" 또는 "" */
export function DateTimeField({
  label,
  value,
  onChange,
  hint,
  optional,
  disabled,
  fieldKey,
}: FieldProps) {
  const id = useId()
  const hintId = `${id}-hint`
  return (
    <Row id={id} label={label} optional={optional}>
      <input
        id={id}
        className="input"
        type="datetime-local"
        step={60}
        data-field={fieldKey}
        value={value}
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <Hint id={hintId}>{hint}</Hint>}
    </Row>
  )
}

const MAX_DIGITS = 15

/**
 * 금액 입력. 숫자만 받아 천 단위 쉼표로 보여주고, 칸 안에 "원"을, 아래에 "1억 2,000만 원"처럼 한국식 단위를 쓴다.
 * 값(value)은 숫자만 담은 문자열이다. 쉼표가 들어가도 커서 위치가 튀지 않게 맞춘다.
 */
export function MoneyField({
  label,
  value,
  onChange,
  hint,
  optional,
  disabled,
  fieldKey,
  gloss,
}: FieldProps) {
  const id = useId()
  const amountId = `${id}-amount`
  const hintId = `${id}-hint`
  const inputRef = useRef<HTMLInputElement>(null)
  // 입력 직후 커서 앞에 있던 숫자 개수. 쉼표를 다시 넣은 뒤 같은 자리로 커서를 옮긴다.
  const digitsBeforeCaret = useRef<number | null>(null)

  useLayoutEffect(() => {
    const el = inputRef.current
    const target = digitsBeforeCaret.current
    digitsBeforeCaret.current = null
    if (!el || target === null || document.activeElement !== el) return
    let pos = 0
    let seen = 0
    while (pos < el.value.length && seen < target) {
      const ch = el.value[pos]
      if (ch >= '0' && ch <= '9') seen += 1
      pos += 1
    }
    el.setSelectionRange(pos, pos)
  })

  const amount = digitsToNumber(value)
  const describedBy = [amount !== null ? amountId : null, hint ? hintId : null]
    .filter(Boolean)
    .join(' ')

  return (
    <Row id={id} label={label} optional={optional} gloss={gloss}>
      <div className="money">
        <input
          ref={inputRef}
          id={id}
          className="input"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          data-field={fieldKey}
          value={groupDigits(value)}
          disabled={disabled}
          aria-describedby={describedBy || undefined}
          onKeyDown={(e) => {
            // 쉼표 바로 뒤에서 지우면 쉼표 앞 숫자를 지운다 (쉼표만 지우면 값이 그대로라 커서만 튄다).
            const el = e.currentTarget
            const at = el.selectionStart
            if (at === null || at !== el.selectionEnd) return
            if (e.key === 'Backspace' && at > 0 && el.value[at - 1] === ',') {
              el.setSelectionRange(at - 1, at - 1)
            } else if (e.key === 'Delete' && el.value[at] === ',') {
              el.setSelectionRange(at + 1, at + 1)
            }
          }}
          onChange={(e) => {
            const raw = e.target.value
            const caret = e.target.selectionStart ?? raw.length
            digitsBeforeCaret.current = raw.slice(0, caret).replace(/\D/g, '').length
            const digits = raw
              .replace(/\D/g, '')
              .replace(/^0+(?=\d)/, '')
              .slice(0, MAX_DIGITS)
            onChange(digits)
          }}
        />
        <span className="money-unit" aria-hidden="true">
          원
        </span>
      </div>
      {amount !== null && <Hint id={amountId}>{formatWon(amount)}</Hint>}
      {hint && <Hint id={hintId}>{hint}</Hint>}
    </Row>
  )
}
