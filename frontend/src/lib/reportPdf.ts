// 검토서를 PDF 파일로 만든다 (휴대폰 공유창이나 내려받기로 보낸다). 모두 브라우저 안에서 하고 서버로는 보내지 않는다.
// 1) 화면 밖 iframe(폭 760px, 컴퓨터 화면 배치)에 지금 검토서를 복사하고 접힌 곳을 모두 펼친다
// 2) 글줄 위치를 재서 줄 가운데가 잘리지 않게 쪽을 나눈다
// 3) html2canvas로 그림을 떠서 A4 쪽마다 JPEG 한 장씩 PDF에 담는다
// 주민등록번호·전화번호 가림은 화면에 이미 되어 있어서 그대로 따라온다.

import logo from '../assets/logo.png'
import { jpegPdf, pageCuts } from './pdf'
import type { JpegPage, Span } from './pdf'

const WIDTH = 760 // 본문 폭(px). A4 본문 182mm에 맞춘다 → 16px 글자가 약 11pt
const SCALE = 2 // 그림 배율 (약 210dpi)
const MM = WIDTH / 182 // 1mm가 몇 px인지
const PAGE_W = 210 * MM
const PAGE_H = 297 * MM
const MARGIN_X = 14 * MM
const MARGIN_TOP = 14 * MM
const MARGIN_BOTTOM = 16 * MM
const BODY_H = Math.floor(PAGE_H - MARGIN_TOP - MARGIN_BOTTOM) // 한 쪽에 들어가는 본문 높이(px)
const FOOTER_Y = 8 * MM // 쪽 아래 끝에서 쪽 번호 줄까지
// 한 번에 뜨는 그림 크기 상한. 아이폰 사파리의 캔버스 한도(약 1,670만 화소)보다 작게
const MAX_CHUNK_PIXELS = 10_000_000
const JPEG_QUALITY = 0.85
const FONTS = ['400 16px "Pretendard Variable"', '700 16px "Noto Serif KR"']
// 쪽을 나눌 때 되도록 통째로 두는 덩어리 (한 쪽의 절반보다 작을 때만)
const BLOCKS = '.finding, tr, .row, figure, li'

export interface ReportPdfOptions {
  fileName: string
  /** PDF 문서 정보의 제목 */
  title: string
  /** 쪽마다 아래에 쓰는 문서 이름 (오른쪽에는 쪽 번호) */
  footer: string
}

/** source(검토서가 그려진 main)를 A4 PDF 파일로 만든다 */
export async function reportPdf(source: HTMLElement, options: ReportPdfOptions): Promise<File> {
  const [{ default: html2canvas }, frame] = await Promise.all([import('html2canvas'), openFrame(source)])
  try {
    const doc = frame.contentDocument
    const root = doc?.getElementById('pdf-root')
    if (!doc || !root) throw new Error('pdf frame not ready')
    const text = `${root.innerText}${options.footer}0123456789/`
    // 줄 위치는 iframe에서 재고, 그림은 이 문서의 캔버스에 그리므로 양쪽 모두 글꼴을 받아 둔다
    await Promise.all([loadFonts(doc, text), loadFonts(document, text)])

    const total = Math.ceil(root.getBoundingClientRect().height)
    const { lines, blocks } = measure(root)
    const edges = [0, ...pageCuts(total, BODY_H, lines, blocks), total]
    const slices: Span[] = edges.slice(1).map((bottom, i) => [edges[i], bottom])

    // 여러 쪽을 한 번에 뜨되 캔버스가 너무 커지지 않게 묶는다
    const chunks: Span[][] = []
    for (const slice of slices) {
      const chunk = chunks.at(-1)
      if (chunk && (slice[1] - chunk[0][0]) * WIDTH * SCALE * SCALE <= MAX_CHUNK_PIXELS) chunk.push(slice)
      else chunks.push([slice])
    }

    const pages: JpegPage[] = []
    for (const chunk of chunks) {
      const top = chunk[0][0]
      const canvas = await html2canvas(root, {
        scale: SCALE,
        backgroundColor: '#ffffff',
        logging: false,
        x: 0,
        y: top,
        width: WIDTH,
        height: chunk[chunk.length - 1][1] - top,
        windowWidth: WIDTH,
        windowHeight: Math.ceil(PAGE_H),
        scrollX: 0,
        scrollY: 0,
        onclone: (cloned: Document) => loadFonts(cloned, text),
      })
      for (const [a, b] of chunk) {
        pages.push(await pageJpeg(canvas, a - top, b - a, pages.length + 1, slices.length, options.footer))
      }
      canvas.width = canvas.height = 0 // 메모리를 바로 돌려준다
    }
    return new File([jpegPdf(pages, options.title)], options.fileName, { type: 'application/pdf' })
  } finally {
    frame.remove()
  }
}

/** 화면 밖에 폭 760px iframe을 열고 검토서를 복사한다. 스타일은 이 문서 것을 그대로 쓴다 */
function openFrame(source: HTMLElement): Promise<HTMLIFrameElement> {
  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.tabIndex = -1
  frame.style.cssText = `position:fixed;left:-10000px;top:0;width:${WIDTH}px;height:${Math.ceil(PAGE_H)}px;border:0`
  const styles = [...document.querySelectorAll<HTMLElement>('link[rel="stylesheet"], style')]
    .map((node) =>
      node instanceof HTMLLinkElement
        ? `<link rel="stylesheet" href="${attr(node.href)}"${node.hasAttribute('crossorigin') ? ' crossorigin' : ''}>`
        : `<style>${node.textContent ?? ''}</style>`,
    )
    .join('')
  frame.srcdoc =
    `<!doctype html><html lang="ko" style="overflow:hidden"><head><meta charset="utf-8">` +
    `<base href="${attr(location.href)}">${styles}</head><body class="pdf-capture"><div id="pdf-root">` +
    `<img class="pdf-logo" src="${attr(new URL(logo, location.href).href)}" alt="집키미">` +
    `<main class="page">${source.innerHTML}</main></div></body></html>`
  return new Promise((resolve, reject) => {
    frame.onload = () => {
      const doc = frame.contentDocument
      if (!doc) {
        frame.remove()
        reject(new Error('pdf frame has no document'))
        return
      }
      // 근거 원문(<details>)과 접힌 목록(확인 못 함·해당 없음·참고)을 모두 펼친다
      doc.querySelectorAll('details').forEach((d) => (d.open = true))
      doc.querySelectorAll('.fold-body[hidden]').forEach((el) => el.removeAttribute('hidden'))
      resolve(frame)
    }
    document.body.appendChild(frame)
  })
}

/** 글자에 쓰인 글꼴 조각(한글은 글자 범위별로 나뉘어 있다)을 모두 받을 때까지 기다린다 */
async function loadFonts(doc: Document, text: string): Promise<void> {
  if (!doc.fonts) return
  await Promise.all(FONTS.map((font) => doc.fonts.load(font, text).catch(() => [])))
  await doc.fonts.ready
}

/** 글줄·그림의 세로 위치(자르면 안 됨)와 덩어리·제목 묶음의 위치(되도록 자르지 않음) */
function measure(root: HTMLElement): { lines: Span[]; blocks: Span[] } {
  const doc = root.ownerDocument
  const top = root.getBoundingClientRect().top
  const span = (r: DOMRect): Span => [r.top - top, r.bottom - top]

  const lines: Span[] = []
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const range = doc.createRange()
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.nodeValue?.trim()) continue
    range.selectNodeContents(node)
    for (const r of range.getClientRects()) if (r.width > 0 && r.height > 0) lines.push(span(r))
  }
  for (const el of root.querySelectorAll('img, svg')) lines.push(span(el.getBoundingClientRect()))

  const blocks: Span[] = []
  for (const el of root.querySelectorAll(BLOCKS)) {
    const s = span(el.getBoundingClientRect())
    if (s[1] - s[0] < BODY_H / 2) blocks.push(s)
  }
  // 제목이 쪽 맨 아래에 홀로 남지 않게 제목과 다음 줄을 묶는다. 절의 첫 제목은 절 위쪽 굵은 선부터 묶는다
  const sorted = [...lines].sort((x, y) => x[0] - y[0])
  for (const el of root.querySelectorAll('h1, h2, h3')) {
    const section = el.closest('.doc-section')
    const head = section && section.querySelector('h1, h2, h3') === el ? section : el
    const a = span(head.getBoundingClientRect())[0]
    const b = span(el.getBoundingClientRect())[1]
    const next = sorted.find(([la]) => la >= b - 1)
    if (next && next[1] - a < BODY_H / 2) blocks.push([a, next[1]])
  }
  return { lines, blocks }
}

/** 뜬 그림의 [sy, sy+height] 부분을 A4 한 쪽(여백·쪽 번호 포함)으로 만들어 JPEG로 바꾼다 */
async function pageJpeg(
  source: HTMLCanvasElement,
  sy: number,
  height: number,
  number: number,
  count: number,
  footer: string,
): Promise<JpegPage> {
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(PAGE_W * SCALE)
  canvas.height = Math.round(PAGE_H * SCALE)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('no canvas')
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  const y0 = Math.round(sy * SCALE)
  const h = Math.min(Math.round(height * SCALE), source.height - y0)
  if (h > 0) {
    ctx.drawImage(source, 0, y0, source.width, h, Math.round(MARGIN_X * SCALE), Math.round(MARGIN_TOP * SCALE), source.width, h)
  }
  ctx.fillStyle = '#4b5563'
  ctx.font = `${12 * SCALE}px "Pretendard Variable", Pretendard, sans-serif`
  const baseline = canvas.height - Math.round(FOOTER_Y * SCALE)
  ctx.textAlign = 'left'
  ctx.fillText(footer, Math.round(MARGIN_X * SCALE), baseline)
  ctx.textAlign = 'right'
  ctx.fillText(`${number} / ${count}`, canvas.width - Math.round(MARGIN_X * SCALE), baseline)

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY))
  const page = { width: canvas.width, height: canvas.height }
  canvas.width = canvas.height = 0
  if (!blob) throw new Error('jpeg encoding failed')
  return { ...page, data: new Uint8Array(await blob.arrayBuffer()) }
}

/** HTML 속성 값으로 넣을 때 따옴표와 &를 바꾼다 */
function attr(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
}
