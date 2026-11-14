// 계약서 사진 가리기: 검은 네모. 좌표는 사진 픽셀 기준이다.
// 흐리게 하지 않고 불투명한 검정으로 칠해서, 보내는 사진에서는 가린 곳이 완전히 지워진다.

import { decodeImage, JPEG_QUALITY } from './files'

export interface MaskMark {
  kind: 'rect'
  x: number
  y: number
  w: number
  h: number
  /** 자동으로 찾아 가린 곳 (주민등록번호·전화번호·계좌번호). 사용자가 끈 네모는 없음 */
  auto?: boolean
}

const MASK_COLOR = '#000000'

/** 가린 곳을 불투명한 검정으로 칠한다 */
export function drawMarks(ctx: CanvasRenderingContext2D, marks: readonly MaskMark[]) {
  ctx.save()
  ctx.fillStyle = MASK_COLOR
  for (const mark of marks) ctx.fillRect(mark.x, mark.y, mark.w, mark.h)
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
