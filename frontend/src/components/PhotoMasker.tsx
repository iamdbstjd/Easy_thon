import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { decodeImage } from '../lib/files'
import type { Decoded } from '../lib/files'
import { drawMarks, rectMark } from '../lib/photoMask'
import type { MaskMark } from '../lib/photoMask'

/** 이보다 작은 네모는 실수로 누른 것으로 본다 (사진 픽셀) */
const MIN_RECT_PX = 4
/** 확대 단계. 1은 사진이 칸(폭, 화면 높이의 70%)에 꼭 맞는 크기 */
const ZOOMS = [1, 1.5, 2, 3, 4]

interface Drawing {
  pointerId: number
  mark: MaskMark
  start: [number, number]
}

/**
 * 계약서 사진 가리기. 사진 위에 네모를 끌어 검게 가린다.
 * - 자동으로 찾은 번호(주민등록번호·전화번호·계좌번호)가 먼저 가려져 있고, 사용자는 그 위에 더 가린다.
 * - −/+로 사진을 키워 작은 글자도 정확히 가린다. 키운 사진은 두 손가락으로 끌어(컴퓨터는 스크롤) 옮긴다.
 * 가린 곳(marks)만 바꾸고, 보낼 파일은 보내기 직전에 이 가린 곳으로 새로 만든다.
 */
export function PhotoMasker({
  id,
  source,
  marks,
  auto,
  autoFound,
  onChange,
}: {
  id: string
  /** 가리기 전 사진 (줄인 JPEG) */
  source: File
  marks: MaskMark[]
  /** 자동 가리기 상태 ('pending'이면 아직 찾는 중) */
  auto: 'off' | 'pending' | 'done'
  /** 자동으로 찾아 가린 곳의 수 (사용자가 지워도 그대로) */
  autoFound: number
  onChange: (marks: MaskMark[]) => void
}) {
  const baseId = useId()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const imageRef = useRef<Decoded | null>(null)
  const marksRef = useRef<MaskMark[]>(marks)
  const drawing = useRef<Drawing | null>(null)
  const frame = useRef(0)
  // 두 손가락으로 사진 옮기기: 화면에 닿아 있는 손가락들과, 옮기는 중인지
  const touches = useRef(new Map<number, [number, number]>())
  const panning = useRef(false)
  // 확대 단계를 바꿀 때 화면 가운데에 보이던 곳 (확대 1 기준 px). 바꾼 뒤에도 가운데에 둔다
  const keepCenter = useRef<[number, number] | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [size, setSize] = useState<[number, number] | null>(null)
  const [zoom, setZoom] = useState(1)

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
        setSize([image.width, image.height])
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

  useLayoutEffect(() => {
    const view = viewportRef.current
    const center = keepCenter.current
    if (!view || !center) return
    keepCenter.current = null
    view.scrollLeft = center[0] * zoom - view.clientWidth / 2
    view.scrollTop = center[1] * zoom - view.clientHeight / 2
  }, [zoom])

  function zoomTo(next: number) {
    const view = viewportRef.current
    if (view) {
      keepCenter.current = [
        (view.scrollLeft + view.clientWidth / 2) / zoom,
        (view.scrollTop + view.clientHeight / 2) / zoom,
      ]
    }
    setZoom(next)
  }

  /** 화면 좌표 → 사진 픽셀 좌표 */
  function toImage(e: ReactPointerEvent<HTMLCanvasElement>): [number, number] {
    const canvas = e.currentTarget
    const rect = canvas.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * canvas.width
    const y = ((e.clientY - rect.top) / rect.height) * canvas.height
    return [Math.min(Math.max(x, 0), canvas.width), Math.min(Math.max(y, 0), canvas.height)]
  }

  function onPointerDown(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (status !== 'ready') return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.preventDefault()
    if (e.pointerType === 'touch') {
      touches.current.set(e.pointerId, [e.clientX, e.clientY])
      if (touches.current.size >= 2) {
        // 두 번째 손가락이 닿으면 그리던 네모는 버리고 사진을 옮긴다
        if (drawing.current) {
          drawing.current = null
          scheduleRedraw()
        }
        panning.current = true
        return
      }
    }
    if (panning.current || drawing.current) return
    e.currentTarget.setPointerCapture(e.pointerId)
    const [x, y] = toImage(e)
    drawing.current = { pointerId: e.pointerId, start: [x, y], mark: rectMark(x, y, x, y) }
    scheduleRedraw()
  }

  function onPointerMove(e: ReactPointerEvent<HTMLCanvasElement>) {
    const last = touches.current.get(e.pointerId)
    if (last) {
      touches.current.set(e.pointerId, [e.clientX, e.clientY])
      if (panning.current) {
        // 손가락들의 가운데가 움직인 만큼 옮긴다 (손가락 하나가 움직이면 그 1/n)
        const view = viewportRef.current
        const n = touches.current.size
        if (view) {
          view.scrollLeft -= (e.clientX - last[0]) / n
          view.scrollTop -= (e.clientY - last[1]) / n
        }
        return
      }
    }
    const current = drawing.current
    if (!current || current.pointerId !== e.pointerId) return
    e.preventDefault()
    const [x, y] = toImage(e)
    current.mark = rectMark(current.start[0], current.start[1], x, y)
    scheduleRedraw()
  }

  /** 손을 떼면(또는 브라우저가 끊으면) 끈 네모를 그대로 남긴다. 보이는 대로 가려야 하므로 버리지 않는다 */
  function finish(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (touches.current.delete(e.pointerId) && touches.current.size === 0) panning.current = false
    const current = drawing.current
    if (!current || current.pointerId !== e.pointerId) return
    drawing.current = null
    const { mark } = current
    if (mark.w < MIN_RECT_PX || mark.h < MIN_RECT_PX) {
      scheduleRedraw()
      return
    }
    marksRef.current = [...marksRef.current, mark]
    onChange(marksRef.current)
  }

  const helpId = `${baseId}-help`
  const count = marks.length
  const autoCount = marks.filter((m) => m.auto).length
  const step = ZOOMS.indexOf(zoom)
  const [w, h] = size ?? [1, 1]

  return (
    <div id={id} className="mask-tool" role="group" aria-label="보내기 전에 가리기">
      <p id={helpId}>
        {auto === 'pending'
          ? '주민등록번호·전화번호·계좌번호를 찾아 자동으로 가리고 있어요…'
          : auto === 'done' && autoCount > 0
            ? `주민등록번호·전화번호·계좌번호로 보이는 곳 ${autoCount}군데를 자동으로 가렸어요. 빠진 곳이 없는지 확인하고, 이름·서명·도장처럼 더 가릴 곳은 네모로 끌어 가리세요.`
            : auto === 'done' && autoFound === 0
              ? '자동으로 가릴 번호를 찾지 못했어요. 주민등록번호·전화번호·서명·계좌번호처럼 보내고 싶지 않은 곳을 네모로 끌어 가리세요.'
              : '주민등록번호·전화번호·서명·계좌번호처럼 보내고 싶지 않은 곳을 네모로 끌어 가리세요.'}{' '}
        가린 사진만 보내요.
      </p>
      {status === 'loading' && <p className="muted">사진 불러오는 중</p>}
      {status === 'failed' && (
        <p className="form-error" role="alert">
          사진을 열지 못했어요. 다른 사진을 골라 주세요.
        </p>
      )}
      {status === 'ready' && (
        <div className="mask-zoom">
          <button
            type="button"
            className="zoom-button"
            aria-label="사진 작게"
            disabled={step <= 0}
            onClick={() => zoomTo(ZOOMS[step - 1])}
          >
            −
          </button>
          <span className="zoom-level" aria-live="polite">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            className="zoom-button"
            aria-label="사진 크게"
            disabled={step >= ZOOMS.length - 1}
            onClick={() => zoomTo(ZOOMS[step + 1])}
          >
            +
          </button>
          {zoom > 1 && (
            <span className="muted">
              {window.matchMedia?.('(pointer: coarse)').matches
                ? '두 손가락으로 끌면 사진이 움직여요'
                : '스크롤하면 사진이 움직여요'}
            </span>
          )}
        </div>
      )}
      <div
        ref={viewportRef}
        className="mask-viewport"
        data-zoomed={zoom > 1 ? '' : undefined}
        hidden={status !== 'ready'}
        style={{ aspectRatio: `${w} / ${h}`, width: `min(100%, calc(70vh * ${w} / ${h}))` }}
      >
        <canvas
          ref={canvasRef}
          className="mask-canvas"
          style={{ width: `${zoom * 100}%` }}
          role="img"
          aria-label="계약서 사진. 네모로 끈 곳이 검게 가려져요."
          aria-describedby={helpId}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={finish}
          onPointerCancel={finish}
          onLostPointerCapture={finish}
        />
      </div>
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
          {count > 0
            ? `가린 곳 ${count}군데${autoCount > 0 ? ` (자동 ${autoCount}군데 포함)` : ''}`
            : '아직 가린 곳이 없어요'}
        </span>
      </div>
    </div>
  )
}
