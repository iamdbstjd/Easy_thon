// 계약서 PDF 가리기: PDF를 쪽마다 그림(JPEG)으로 그리고, 글자 층에서 주민등록번호·전화번호·계좌번호 자리를 찾는다.
// - pdf.js(pdfjs-dist, 옛 휴대폰 브라우저도 되는 legacy 판)는 PDF를 고를 때만 불러온다. 일꾼·글꼴 지도(cmaps)·표준 글꼴·
//   wasm·색 프로필은 CDN이 아니라 우리 주소(/pdfjs/, scripts/copy-ocr.mjs가 복사)에서 받고, 어디에도 저장하지 않는다.
// - 글자 층이 있는 쪽(전자 계약서 대부분)은 글자 위치로 바로 찾는다. 스캔해서 글자 층이 거의 없는 쪽은 textMarks가 null이라
//   부르는 쪽이 쪽 그림을 OCR(autoMask.findPersonalMarks)로 읽는다.
// - 가린 PDF(maskedPdf)에는 가린 쪽 그림만 담는다. 원래 PDF의 글자 층은 넣지 않으므로 가린 번호가 파일에 남지 않는다.

import { personalNumberRanges } from './autoMask'
import { decodeImage, JPEG_QUALITY } from './files'
import { jpegPdf } from './pdf'
import type { JpegPage } from './pdf'
import { drawMarks } from './photoMask'
import type { MaskMark } from './photoMask'

type PdfJs = typeof import('pdfjs-dist/legacy/build/pdf.mjs')
type PdfPageProxy = import('pdfjs-dist').PDFPageProxy
type PageViewport = import('pdfjs-dist').PageViewport

/** 쪽 그림의 가로 (px). 아주 긴 쪽은 세로 상한에 맞춘다 */
const PAGE_WIDTH = 1600
const PAGE_MAX_HEIGHT = 2600
/** 한 서류의 쪽 수 상한 (서버와 같다) */
export const MAX_PDF_PAGES = 30
/** 글자 층의 글자(공백 빼고)가 이보다 적으면 스캔한 쪽으로 보고 OCR에 맡긴다 */
const MIN_TEXT_CHARS = 20
/** pdf.js 파일을 받는 곳 (우리 주소) */
const PDFJS_BASE = '/pdfjs/'

export interface PdfPage {
  /** 쪽 그림 (JPEG File, 가리기 화면·OCR에 쓴다). 가로 약 1600px */
  image: File
  /** 그림 픽셀 크기 */
  width: number
  height: number
  /** 원래 쪽 크기 (pt) */
  size: [number, number]
  /** 글자 층에서 찾은 번호 자리 (그림 픽셀 좌표, kind:'rect'). 글자 층이 거의 없으면 null → 부르는 쪽이 OCR(findPersonalMarks)을 쓴다 */
  textMarks: MaskMark[] | null
}

let pdfjsLoading: Promise<PdfJs> | null = null

/** pdf.js를 한 번만 불러온다 (실패하면 다음에 다시 시도) */
function loadPdfJs(): Promise<PdfJs> {
  pdfjsLoading ??= import('pdfjs-dist/legacy/build/pdf.mjs').then(
    (pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = `${PDFJS_BASE}pdf.worker.min.mjs`
      return pdfjs
    },
    (err: unknown) => {
      pdfjsLoading = null
      throw err
    },
  )
  return pdfjsLoading
}

/**
 * PDF를 쪽마다 그림으로 그리고 글자 층에서 번호 자리를 찾는다.
 * 암호가 걸렸거나 깨진 PDF면 예외, 쪽이 MAX_PDF_PAGES보다 많으면 Error('too_many_pages').
 */
export async function pdfPages(file: File): Promise<PdfPage[]> {
  const pdfjs = await loadPdfJs()
  const task = pdfjs.getDocument({
    data: new Uint8Array(await file.arrayBuffer()),
    cMapUrl: `${PDFJS_BASE}cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${PDFJS_BASE}standard_fonts/`,
    wasmUrl: `${PDFJS_BASE}wasm/`,
    iccUrl: `${PDFJS_BASE}iccs/`,
    enableXfa: false,
    verbosity: 0,
  })
  try {
    const doc = await task.promise
    if (doc.numPages > MAX_PDF_PAGES) throw new Error('too_many_pages')
    const base = file.name.replace(/\.[^.]+$/, '') || 'contract'
    const pages: PdfPage[] = []
    // 휴대폰 메모리를 아끼려고 한 쪽씩 그리고 바로 정리한다
    for (let n = 1; n <= doc.numPages; n++) {
      const page = await doc.getPage(n)
      try {
        pages.push(await renderPage(page, `${base}-${n}.jpg`))
      } finally {
        page.cleanup()
      }
    }
    return pages
  } finally {
    await task.destroy()
  }
}

async function renderPage(page: PdfPageProxy, name: string): Promise<PdfPage> {
  const unit = page.getViewport({ scale: 1 }) // 쪽 회전을 반영한 크기 (pt)
  const viewport = page.getViewport({ scale: Math.min(PAGE_WIDTH / unit.width, PAGE_MAX_HEIGHT / unit.height) })
  const canvas = document.createElement('canvas')
  canvas.width = Math.floor(viewport.width)
  canvas.height = Math.floor(viewport.height)
  try {
    await page.render({ canvas, viewport, background: '#ffffff' }).promise
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY))
    if (!blob) throw new Error('jpeg encoding failed')
    const textMarks = await findTextMarks(page, viewport, canvas.width, canvas.height)
    return {
      image: new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() }),
      width: canvas.width,
      height: canvas.height,
      size: [unit.width, unit.height],
      textMarks,
    }
  } finally {
    canvas.width = canvas.height = 0
  }
}

/** 글자 조각 하나: 기준선 시작점(pt)과 글자 진행 방향·위쪽 방향(단위 벡터), 글자 크기, 폭(pt) */
interface Piece {
  str: string
  x: number
  y: number
  dir: [number, number]
  up: [number, number]
  size: number
  width: number
  /** 줄 글자에서 이 조각이 시작하는 위치 */
  start: number
}

/** 글자 층에서 번호 자리를 찾는다. 글자 층이 거의 없으면 null */
async function findTextMarks(
  page: PdfPageProxy,
  viewport: PageViewport,
  width: number,
  height: number,
): Promise<MaskMark[] | null> {
  const content = await page.getTextContent()
  const pieces: Piece[] = []
  let chars = 0
  for (const item of content.items) {
    if (!('str' in item) || !item.str) continue
    chars += item.str.replace(/\s/g, '').length
    const [a, b, c, d, e, f] = item.transform as number[]
    const along = Math.hypot(a, b) || 1
    const size = Math.hypot(c, d) || along
    pieces.push({
      str: item.str,
      x: e,
      y: f,
      dir: [a / along, b / along],
      up: [c / size, d / size],
      size,
      width: item.width,
      start: 0,
    })
  }
  if (chars < MIN_TEXT_CHARS) return null

  // 기준선 높이가 글자 크기의 40% 안이면 같은 줄로 본다 (위 줄부터, 줄 안에서는 왼쪽부터)
  pieces.sort((p, q) => q.y - p.y || p.x - q.x)
  const lines: Piece[][] = []
  for (const piece of pieces) {
    const line = lines.at(-1)
    if (line && Math.abs(line[0].y - piece.y) <= 0.4 * Math.max(line[0].size, piece.size)) line.push(piece)
    else lines.push([piece])
  }

  const rects: MaskMark[] = []
  for (const line of lines) {
    line.sort((p, q) => p.x - q.x)
    // 조각 사이가 글자 크기의 15%보다 벌어져 있으면 띄어쓰기를 넣는다
    let text = ''
    let prev: Piece | null = null
    for (const piece of line) {
      if (prev && piece.x - (prev.x + prev.width) > 0.15 * piece.size && !/\s$/.test(text) && !/^\s/.test(piece.str)) {
        text += ' '
      }
      piece.start = text.length
      text += piece.str
      prev = piece
    }
    for (const [from, to] of personalNumberRanges(text)) {
      const rect = rangeRect(line, from, to, viewport)
      if (rect) rects.push(padRect(rect, width, height))
    }
  }
  return mergeRects(rects)
}

/** 글자 폭 어림 (글자 크기 기준): 한글·한자·전각은 1, 띄어쓰기 0.3, 숫자·영문 등은 0.55 */
function charWeight(ch: string): number {
  const code = ch.charCodeAt(0)
  if (
    (code >= 0x1100 && code <= 0x11ff) ||
    (code >= 0x2e80 && code <= 0x9fff) ||
    (code >= 0xac00 && code <= 0xd7af) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xff00 && code <= 0xffef)
  ) {
    return 1
  }
  return /\s/.test(ch) ? 0.3 : 0.55
}

/** 조각 글자 [0, i) 까지가 조각 폭에서 차지하는 비율 (한글이 숫자보다 넓은 것을 반영) */
function widthRatio(str: string, i: number): number {
  let before = 0
  let total = 0
  for (let k = 0; k < str.length; k++) {
    const w = charWeight(str[k])
    if (k < i) before += w
    total += w
  }
  return total > 0 ? before / total : 0
}

/** 줄 글자의 [from, to) 부분을 덮는 네모 (그림 픽셀). 조각 안의 위치는 글자 폭 어림으로 정한다 */
function rangeRect(line: Piece[], from: number, to: number, viewport: PageViewport) {
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  let sizePx = 0
  for (const piece of line) {
    const end = piece.start + piece.str.length
    if (end <= from || piece.start >= to) continue
    const a = widthRatio(piece.str, Math.max(from, piece.start) - piece.start) * piece.width
    const b = widthRatio(piece.str, Math.min(to, end) - piece.start) * piece.width
    // 기준선 아래 30%부터 글자 크기만큼 위까지
    for (const along of [a, b]) {
      for (const rise of [-0.3 * piece.size, 1.0 * piece.size]) {
        const px = piece.x + piece.dir[0] * along + piece.up[0] * rise
        const py = piece.y + piece.dir[1] * along + piece.up[1] * rise
        const [vx, vy] = viewport.convertToViewportPoint(px, py) as [number, number]
        x0 = Math.min(x0, vx)
        y0 = Math.min(y0, vy)
        x1 = Math.max(x1, vx)
        y1 = Math.max(y1, vy)
      }
    }
    sizePx = Math.max(sizePx, piece.size * viewport.scale)
  }
  return Number.isFinite(x0) ? { x0, y0, x1, y1, sizePx } : null
}

/** 숫자가 다 덮이게 넉넉히 키운다 */
function padRect(r: { x0: number; y0: number; x1: number; y1: number; sizePx: number }, width: number, height: number): MaskMark {
  const padX = 0.3 * r.sizePx + 2
  const padY = 0.15 * r.sizePx + 2
  const x = Math.max(0, Math.floor(r.x0 - padX))
  const y = Math.max(0, Math.floor(r.y0 - padY))
  return {
    kind: 'rect',
    x,
    y,
    w: Math.min(width, Math.ceil(r.x1 + padX)) - x,
    h: Math.min(height, Math.ceil(r.y1 + padY)) - y,
  }
}

/** 겹치는 네모는 하나로 합친다 (같은 번호가 여러 규칙에 걸린 경우) */
function mergeRects(rects: MaskMark[]): MaskMark[] {
  const out = [...rects]
  for (let merged = true; merged; ) {
    merged = false
    outer: for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        const p = out[i]
        const q = out[j]
        if (p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h) {
          const x = Math.min(p.x, q.x)
          const y = Math.min(p.y, q.y)
          out[i] = { kind: 'rect', x, y, w: Math.max(p.x + p.w, q.x + q.w) - x, h: Math.max(p.y + p.h, q.y + q.h) - y }
          out.splice(j, 1)
          merged = true
          break outer
        }
      }
    }
  }
  return out
}

/**
 * 가린 PDF: 쪽 그림에 가린 곳을 검게 칠해 쪽마다 JPEG 한 장씩 담는다. 쪽 크기는 원래 PDF와 같다.
 * 원래 PDF의 글자 층은 넣지 않는다 (가린 번호가 파일에 남지 않게).
 */
export async function maskedPdf(
  pages: { image: File; width: number; height: number; size: [number, number]; marks: MaskMark[] }[],
  name: string,
  title?: string,
): Promise<File> {
  const out: JpegPage[] = []
  for (const page of pages) {
    const image = await decodeImage(page.image)
    const canvas = document.createElement('canvas')
    try {
      canvas.width = page.width
      canvas.height = page.height
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('canvas 2d context unavailable')
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(image.source, 0, 0, canvas.width, canvas.height)
      drawMarks(ctx, page.marks)
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY))
      if (!blob) throw new Error('jpeg encoding failed')
      out.push({ data: new Uint8Array(await blob.arrayBuffer()), width: canvas.width, height: canvas.height, size: page.size })
    } finally {
      image.release()
      canvas.width = canvas.height = 0
    }
  }
  return new File([jpegPdf(out, title ?? name.replace(/\.[^.]+$/, ''))], name, {
    type: 'application/pdf',
    lastModified: Date.now(),
  })
}
