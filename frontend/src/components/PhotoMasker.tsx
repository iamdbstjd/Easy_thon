import { useEffect, useId, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { decodeImage } from '../lib/files'
import type { Decoded } from '../lib/files'
import { drawMarks, rectMark } from '../lib/photoMask'
import type { MaskMark } from '../lib/photoMask'

/** 붓 굵기 (화면 픽셀). 사진 픽셀로는 미리보기 배율만큼 굵어진다 */
const BRUSH_SCREEN_PX = 22
/** 이보다 작은 네모는 실수로 누른 것으로 본다 (사진 픽셀) */
const MIN_RECT_PX = 4

type Tool = 'brush' | 'rect'

interface Drawing {
  pointerId: number
  mark: MaskMark
  start: [number, number]
}

/**
 * 계약서 사진 가리기. 손가락이나 마우스로 검게 칠하거나 네모를 끌어 가린다.
 * 가린 곳(marks)만 바꾸고, 보낼 파일은 보내기 직전에 이 가린 곳으로 새로 만든다.
 */
export function PhotoMasker({
  id,
  source,
  marks,
  onChange,
}: {
  id: string
  /** 가리기 전 사진 (줄인 JPEG) */
  source: File
  marks: MaskMark[]
  onChange: (marks: MaskMark[]) => void
}) {
  const baseId = useId()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<Decoded | null>(null)
  const marksRef = useRef<MaskMark[]>(marks)
  const drawing = useRef<Drawing | null>(null)
  const frame = useRef(0)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [tool, setTool] = useState<Tool>('brush')

  function redraw() {
    const canvas = canvasRef.current
    const image = imageRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !image || !ctx) return
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(image.source, 0, 0, canvas.width, canvas.height)
    const current = drawing.current ? [drawing.current.mark] : []
    drawMarks(ctx, [...marksRef.current, ...current])
  }

  function scheduleRedraw() {
    if (frame.current) return
    frame.current = requestAnimationFrame(() => {
      frame.current = 0
      redraw()
    })
  }

  // 사진을 읽어 캔버스 크기를 사진 크기에 맞춘다
  useEffect(() => {
    let cancelled = false
    decodeImage(source).then(
      (image) => {
        if (cancelled) {
          image.release()
          return
        }
        imageRef.current = image
        const canvas = canvasRef.current
        if (canvas) {
          canvas.width = image.width
          canvas.height = image.height
        }
        redraw()
        setStatus('ready')
      },
      () => {
        if (!cancelled) setStatus('failed')
      },
    )
    return () => {
      cancelled = true
      cancelAnimationFrame(frame.current)
      frame.current = 0
      imageRef.current?.release()
      imageRef.current = null
    }
  }, [source])

  useEffect(() => {
    marksRef.current = marks
    redraw()
  }, [marks])

  /** 화면 좌표 → 사진 픽셀 좌표 (테두리 안쪽 기준) */
  function toImage(e: ReactPointerEvent<HTMLCanvasElement>): [number, number] {
    const canvas = e.currentTarget
    const rect = canvas.getBoundingClientRect()
    const left = rect.left + canvas.clientLeft
    const top = rect.top + canvas.clientTop
    const x = ((e.clientX - left) / canvas.clientWidth) * canvas.width
    const y = ((e.clientY - top) / canvas.clientHeight) * canvas.height
    return [Math.min(Math.max(x, 0), canvas.width), Math.min(Math.max(y, 0), canvas.height)]
  }

  function onPointerDown(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (status !== 'ready' || drawing.current) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.preventDefault()
    const canvas = e.currentTarget
    canvas.setPointerCapture(e.pointerId)
    const [x, y] = toImage(e)
    const width = Math.max(6, Math.round((BRUSH_SCREEN_PX * canvas.width) / Math.max(1, canvas.clientWidth)))
    drawing.current = {
      pointerId: e.pointerId,
      start: [x, y],
      mark: tool === 'brush' ? { kind: 'stroke', width, points: [x, y] } : rectMark(x, y, x, y),
    }
    scheduleRedraw()
  }

  function onPointerMove(e: ReactPointerEvent<HTMLCanvasElement>) {
    const current = drawing.current
    if (!current || current.pointerId !== e.pointerId) return
    e.preventDefault()
    const [x, y] = toImage(e)
    if (current.mark.kind === 'stroke') current.mark.points.push(x, y)
    else current.mark = rectMark(current.start[0], current.start[1], x, y)
    scheduleRedraw()
  }

  /** 손을 떼면(또는 브라우저가 끊으면) 칠한 곳을 그대로 남긴다. 보이는 대로 가려야 하므로 버리지 않는다 */
  function finish(e: ReactPointerEvent<HTMLCanvasElement>) {
    const current = drawing.current
    if (!current || current.pointerId !== e.pointerId) return
    drawing.current = null
    const { mark } = current
    if (mark.kind === 'rect' && (mark.w < MIN_RECT_PX || mark.h < MIN_RECT_PX)) {
      scheduleRedraw()
      return
    }
    marksRef.current = [...marksRef.current, mark]
    onChange(marksRef.current)
  }

  const toolName = `${baseId}-tool`
  const helpId = `${baseId}-help`
  const count = marks.length

  return (
    <div id={id} className="mask-tool" role="group" aria-label="보내기 전에 가리기">
      <p id={helpId}>
        주민등록번호·전화번호·서명·계좌번호처럼 보내고 싶지 않은 곳을 칠하세요. 가린 사진만 보내요.
      </p>
      <fieldset className="mask-choices">
        <legend className="visually-hidden">가리는 방법</legend>
        <label className="choice">
          <input
            type="radio"
            name={toolName}
            checked={tool === 'brush'}
            onChange={() => setTool('brush')}
          />
          손으로 칠하기
        </label>
        <label className="choice">
          <input
            type="radio"
            name={toolName}
            checked={tool === 'rect'}
            onChange={() => setTool('rect')}
          />
          네모로 가리기
        </label>
      </fieldset>
      {status === 'loading' && <p className="muted">사진 불러오는 중</p>}
      {status === 'failed' && (
        <p className="form-error" role="alert">
          사진을 열지 못했어요. 다른 사진을 골라 주세요.
        </p>
      )}
      <canvas
        ref={canvasRef}
        className="mask-canvas"
        hidden={status !== 'ready'}
        role="img"
        aria-label={`계약서 사진. ${tool === 'brush' ? '칠한 곳' : '네모로 끈 곳'}이 검게 가려져요.`}
        aria-describedby={helpId}
        data-tool={tool}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finish}
        onPointerCancel={finish}
        onLostPointerCapture={finish}
      />
      <div className="mask-actions">
        <button
          type="button"
          className="link"
          disabled={count === 0}
          onClick={() => onChange(marks.slice(0, -1))}
        >
          되돌리기
        </button>
        <button type="button" className="link" disabled={count === 0} onClick={() => onChange([])}>
          다 지우기
        </button>
        <span className="muted" aria-live="polite">
          {count > 0 ? `가린 곳 ${count}군데` : '아직 가린 곳이 없어요'}
        </span>
      </div>
    </div>
  )
}
