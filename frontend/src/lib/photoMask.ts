// 계약서 사진 가리기: 검은 붓질과 검은 네모. 좌표는 사진 픽셀 기준이다.

import { decodeImage, JPEG_QUALITY } from './files'

export type MaskMark =
  /** 붓질: [x0, y0, x1, y1, …] */
  | { kind: 'stroke'; width: number; points: number[] }
  | { kind: 'rect'; x: number; y: number; w: number; h: number }

const MASK_COLOR = '#000000'

/** 가린 곳을 불투명한 검정으로 칠한다 */
export function drawMarks(ctx: CanvasRenderingContext2D, marks: readonly MaskMark[]) {
  ctx.save()
  ctx.fillStyle = MASK_COLOR
  ctx.strokeStyle = MASK_COLOR
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const mark of marks) {
    if (mark.kind === 'rect') {
      ctx.fillRect(mark.x, mark.y, mark.w, mark.h)
      continue
    }
    const p = mark.points
    if (p.length < 2) continue
    if (p.length === 2) {
      // 한 번 누르기만 했으면 점 하나
      ctx.beginPath()
      ctx.arc(p[0], p[1], mark.width / 2, 0, Math.PI * 2)
      ctx.fill()
      continue
    }
    ctx.lineWidth = mark.width
    ctx.beginPath()
    ctx.moveTo(p[0], p[1])
    for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i], p[i + 1])
    ctx.stroke()
  }
  ctx.restore()
}

/** 두 꼭짓점으로 네모를 만든다 (어느 방향으로 끌어도) */
export function rectMark(x0: number, y0: number, x1: number, y1: number): MaskMark {
  return { kind: 'rect', x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) }
}

/** 캔버스(사진 + 가린 곳)를 보낼 JPEG 파일로 만든다 */
export async function canvasToJpeg(canvas: HTMLCanvasElement, name: string): Promise<File> {
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY))
  if (!blob) throw new Error('jpeg encoding failed')
  return new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() })
}

/** 가리기 전 사진에 가린 곳을 칠해서 보낼 JPEG를 새로 만든다 */
export async function maskedPhotoFile(source: File, marks: readonly MaskMark[]): Promise<File> {
  const image = await decodeImage(source)
  try {
    const canvas = document.createElement('canvas')
    canvas.width = image.width
    canvas.height = image.height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('canvas 2d context unavailable')
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(image.source, 0, 0, canvas.width, canvas.height)
    drawMarks(ctx, marks)
    return await canvasToJpeg(canvas, source.name)
  } finally {
    image.release()
  }
}
