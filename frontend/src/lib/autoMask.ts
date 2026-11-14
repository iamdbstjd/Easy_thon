// 계약서 사진 자동 가리기: 사진에서 주민등록번호·전화번호·계좌번호 모양을 찾아 가릴 네모를 만든다.
// - 글자 읽기(OCR, tesseract.js)는 브라우저 안에서 돈다. 사진은 기기 밖으로 나가지 않고, OCR 파일도 CDN이 아니라
//   우리 주소(/ocr/, scripts/copy-ocr.mjs가 복사)에서 받는다. 모델 파일과 읽은 글자는 어디에도 저장하지 않는다.
// - 영어·숫자 모델로 읽는다. 한글은 못 읽으므로 이름·서명·도장·주소는 사용자가 직접 가린다.
// - 숫자 규칙은 화면 가림(lib/mask.ts, 서버 app/privacy.py)과 같다. 계좌번호는 하이픈으로 나뉜 10–16자리 숫자로 본다.
//   날짜(2026-11-14)·지번(789-1)·금액(180,000,000)은 가리지 않는다.
// - 못 읽거나 실패하면 빈 목록을 돌려준다. 예외를 내지 않는다.

import { decodeImage } from './files'
import { PHONE_NUMBER, RESIDENT_ID } from './mask'
import type { MaskMark } from './photoMask'

type OcrWorker = import('tesseract.js').Worker
type Bbox = { x0: number; y0: number; x1: number; y1: number }

/** OCR에 넣을 사진의 긴 변 (px). 줄인 사진(1,600px)은 1.5배로 키워 작은 숫자도 읽게 한다 */
const OCR_LONG_EDGE = 2400
const MAX_UPSCALE = 2
/** 한 장을 읽는 시간 상한. 넘으면 포기하고 빈 목록 (느린 휴대폰) */
const TIMEOUT_MS = 60_000
/** 다 쓴 OCR 일꾼은 이만큼 쉬면 닫아 메모리를 돌려준다 (사진 여러 장을 이어서 읽을 때는 다시 쓴다) */
const IDLE_MS = 60_000

// 계좌번호 모양: 하이픈으로 나뉜 숫자 묶음 2–4개. 숫자 개수는 아래에서 10–16자리만 남긴다
// (OCR이 하이픈 하나를 놓쳐 "110-123456789"가 돼도 잡게 뒤 묶음은 10자리까지)
const ACCOUNT = /(?<![0-9])(?<![0-9]\s?[-‐‑‒–—−－])[0-9]{2,7}(?:\s?[-‐‑‒–—−－]\s?[0-9]{2,10}){1,3}(?![0-9])/gu
const ACCOUNT_DIGITS = [10, 16]
// 뒷자리를 가린 주민등록번호("850505-2******"): OCR이 별표를 "%*****"·'"'·"+"처럼 읽거나 빼먹어도
// 생년월일 6자리 + (하이픈 + 아무 글자) 또는 (성별 숫자 1–8 + 아무 글자)면 잡는다
const YYMMDD = '[0-9]{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])'
const PARTIAL_ID = new RegExp(`(?<![0-9])${YYMMDD}(?:\\s?[-‐‑‒–—−－]\\s?\\S{1,7}|\\s?[1-8]\\S{0,6})`, 'gu')

// OCR이 숫자 옆에서 자주 헷갈리는 글자 → 숫자 (숫자와 붙어 있을 때만 바꾼다)
const LOOKALIKE: Record<string, string> = {
  O: '0', o: '0', D: '0', Q: '0',
  l: '1', I: '1', i: '1', '|': '1', '!': '1', ']': '1', '[': '1',
  Z: '2', z: '2',
  S: '5', s: '5', $: '5',
  G: '6', b: '6',
  B: '8',
  g: '9', q: '9',
}

/**
 * 한 줄 글자에서 가릴 번호의 [시작, 끝) 위치들. 주민등록번호(외국인·법인등록번호 포함)·전화번호·계좌번호 모양.
 * OCR이 숫자 옆의 O·l·S 같은 글자를 숫자로 잘못 읽은 것도 숫자로 고쳐서 본다.
 */
export function personalNumberRanges(line: string): [number, number][] {
  const text = fixLookalikes(line)
  const ranges: [number, number][] = []
  for (const pattern of [RESIDENT_ID, PARTIAL_ID, PHONE_NUMBER]) {
    for (const m of text.matchAll(pattern)) ranges.push([m.index, m.index + m[0].length])
  }
  for (const m of text.matchAll(ACCOUNT)) {
    const digits = m[0].replace(/[^0-9]/g, '').length
    const groups = m[0].split(/[^0-9]+/).filter(Boolean).length
    // 묶음이 둘뿐이면 12자리 이상만 (계좌는 보통 셋 이상으로 나뉜다. "제2026-5678호"를 "42026-56788"로 잘못 읽은 것 같은 경우를 거른다)
    if (digits >= ACCOUNT_DIGITS[0] && digits <= ACCOUNT_DIGITS[1] && (groups >= 3 || digits >= 12)) {
      ranges.push([m.index, m.index + m[0].length])
    }
  }
  return ranges
}

function fixLookalikes(line: string): string {
  // 한 글자(UTF-16 단위) → 한 글자로만 바꾸므로 위치가 그대로다
  const chars = line.split('')
  const isDigit = (c: string | undefined) => c !== undefined && c >= '0' && c <= '9'
  // 두 번 돌려 "OO1"처럼 이어진 것도 고친다
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < chars.length; i++) {
      const digit = LOOKALIKE[chars[i]]
      if (digit && (isDigit(chars[i - 1]) || isDigit(chars[i + 1]))) chars[i] = digit
    }
  }
  return chars.join('')
}

/**
 * 계약서 사진에서 가릴 곳을 찾아 네모(사진 픽셀 좌표, decodeImage와 같은 크기)로 돌려준다.
 * onProgress는 0–1 (처음에는 OCR 파일 받기, 그다음 글자 읽기).
 */
export async function findPersonalMarks(photo: File, onProgress?: (ratio: number) => void): Promise<MaskMark[]> {
  let done = 0
  const report = (ratio: number) => {
    done = Math.max(done, Math.min(1, ratio))
    onProgress?.(done)
  }
  try {
    return await withTimeout(run(photo, report), TIMEOUT_MS)
  } catch {
    resetWorker()
    return []
  } finally {
    report(1)
  }
}

async function run(photo: File, report: (ratio: number) => void): Promise<MaskMark[]> {
  const image = await decodeImage(photo)
  let canvas: HTMLCanvasElement | null = document.createElement('canvas')
  const { width, height } = image
  const scale = Math.min(MAX_UPSCALE, Math.max(1, OCR_LONG_EDGE / Math.max(width, height)))
  try {
    canvas.width = Math.round(width * scale)
    canvas.height = Math.round(height * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return []
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(image.source, 0, 0, canvas.width, canvas.height)
  } finally {
    image.release()
  }

  // 두 번 읽어 합친다. 한 가지 방법으로만 읽으면 표 칸에 따라 놓치는 번호가 생긴다 (시험한 사진마다 달랐다)
  // 1차: 사진 그대로, 흩어진 글자 모드(PSM 11)
  // 2차: 그림자를 없애고 표 선을 지운 흑백 사진, 자동 배치 모드(PSM 3). 기울거나 그늘진 사진에서 더 잘 읽는다
  const first = await recognize(canvas, 'sparse', report, 0.3, 0.65)
  const cleaned = withoutLines(canvas)
  if (cleaned !== canvas) canvas.width = canvas.height = 0
  canvas = null
  const second = await recognize(cleaned, 'auto', report, 0.65, 1)
  cleaned.width = cleaned.height = 0

  const marks: MaskMark[] = []
  for (const block of [...first, ...second]) {
    for (const paragraph of block.paragraphs ?? []) {
      for (const line of paragraph.lines ?? []) {
        for (const box of lineMatches(line)) marks.push(toMark(box, scale, width, height))
      }
    }
  }
  return mergeMarks(marks)
}

type OcrLine = { bbox: Bbox; words: { text: string; bbox: Bbox; symbols?: { text: string; bbox: Bbox }[] | null }[] }

/** 줄 하나: 글자마다 상자를 붙여 한 줄 글자로 잇고, 찾은 번호마다 덮을 상자(여유 포함)를 만든다 */
function lineMatches(line: OcrLine): Bbox[] {
  let text = ''
  const boxes: (Bbox | null)[] = []
  for (const word of line.words ?? []) {
    if (text) {
      text += ' '
      boxes.push(null)
    }
    // 위치는 정규식과 같은 UTF-16 단위로 센다
    const symbols = word.symbols?.length ? word.symbols : null
    if (symbols) {
      for (const sym of symbols) {
        text += sym.text
        for (let k = 0; k < sym.text.length; k++) boxes.push(sym.bbox)
      }
    } else {
      // 글자별 상자가 없으면 낱말 상자를 글자 수로 나눈다
      const n = Math.max(1, word.text.length)
      const w = (word.bbox.x1 - word.bbox.x0) / n
      text += word.text
      for (let k = 0; k < word.text.length; k++) {
        boxes.push({ ...word.bbox, x0: word.bbox.x0 + w * k, x1: word.bbox.x0 + w * (k + 1) })
      }
    }
  }
  const lineHeight = Math.max(1, line.bbox.y1 - line.bbox.y0)
  const out: Bbox[] = []
  for (const [start, end] of personalNumberRanges(text)) {
    let box: Bbox | null = null
    for (let i = start; i < end; i++) {
      const b = boxes[i]
      if (!b) continue
      box = box ? { x0: Math.min(box.x0, b.x0), y0: Math.min(box.y0, b.y0), x1: Math.max(box.x1, b.x1), y1: Math.max(box.y1, b.y1) } : { ...b }
    }
    if (!box) continue
    // 숫자를 남김없이 덮도록 넉넉히 넓힌다 (사진이 기울었거나 상자가 글자보다 작게 잡혀도)
    const h = Math.max(lineHeight, box.y1 - box.y0)
    const padX = Math.max(8, h * 0.6)
    const padY = Math.max(5, h * 0.35)
    out.push({ x0: box.x0 - padX, y0: box.y0 - padY, x1: box.x1 + padX, y1: box.y1 + padY })
  }
  return out
}

/** OCR 좌표(키운 사진) → 원래 사진 좌표의 네모 */
function toMark(box: Bbox, scale: number, width: number, height: number): MaskMark {
  const x0 = Math.max(0, Math.floor(box.x0 / scale))
  const y0 = Math.max(0, Math.floor(box.y0 / scale))
  const x1 = Math.min(width, Math.ceil(box.x1 / scale))
  const y1 = Math.min(height, Math.ceil(box.y1 / scale))
  return { kind: 'rect', x: x0, y: y0, w: Math.max(0, x1 - x0), h: Math.max(0, y1 - y0) }
}

/** 겹치는 네모는 하나로 합친다 (전화번호가 계좌번호 모양으로도 잡히는 경우 등) */
function mergeMarks(marks: MaskMark[]): MaskMark[] {
  const rects = marks.filter((m): m is Extract<MaskMark, { kind: 'rect' }> => m.kind === 'rect' && m.w > 0 && m.h > 0)
  let merged = true
  while (merged) {
    merged = false
    outer: for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i]
        const b = rects[j]
        if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) {
          const x = Math.min(a.x, b.x)
          const y = Math.min(a.y, b.y)
          rects[i] = { kind: 'rect', x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y }
          rects.splice(j, 1)
          merged = true
          break outer
        }
      }
    }
  }
  return rects
}

// ---- OCR 일꾼: 처음 쓸 때 만들고, 사진 여러 장이면 다시 쓰고, 한동안 안 쓰면 닫는다 (메모리에만 있다)

let workerPromise: Promise<OcrWorker> | null = null
let idleTimer: number | undefined
let queue: Promise<unknown> = Promise.resolve()
/** 지금 읽고 있는 사진의 진행률 받는 곳 (일꾼은 한 번에 한 장만 읽는다) */
let progressTarget: ((status: string, progress: number) => void) | null = null

function ocrUrl(path: string): string {
  return new URL(`${import.meta.env.BASE_URL}ocr/${path}`, window.location.href).href
}

type Tesseract = typeof import('tesseract.js')

async function loadTesseract(): Promise<Tesseract> {
  const mod = await import('tesseract.js')
  // CommonJS 묶음이라 번들러에 따라 default 안에 들어 있을 수 있다
  return typeof mod.createWorker === 'function' ? mod : (mod as unknown as { default: Tesseract }).default
}

async function createOcrWorker(): Promise<OcrWorker> {
  const { createWorker, OEM } = await loadTesseract()
  const worker = await createWorker('eng', OEM.LSTM_ONLY, {
    workerPath: ocrUrl('worker.min.js'),
    corePath: ocrUrl(''),
    langPath: ocrUrl('').replace(/\/$/, ''),
    workerBlobURL: false,
    cacheMethod: 'none',
    logger: (m: { status: string; progress: number }) => progressTarget?.(m.status, m.progress),
  })
  return worker
}

/** 한 번 읽기. layout은 글자 찾는 방법(흩어진 글자 / 자동 배치), [from, to]는 이 읽기가 차지하는 진행률 구간 */
async function recognize(
  canvas: HTMLCanvasElement,
  layout: 'sparse' | 'auto',
  report: (ratio: number) => void,
  from: number,
  to: number,
) {
  const job = queue.then(async () => {
    window.clearTimeout(idleTimer)
    progressTarget = (status, progress) => {
      if (status === 'recognizing text') report(from + (to - from) * progress)
      else if (status.startsWith('loading')) report(0.27 * progress)
    }
    try {
      workerPromise ??= createOcrWorker()
      const [worker, { PSM }] = await Promise.all([workerPromise, loadTesseract()])
      report(from)
      // 해상도를 정해 두면 "Estimating resolution" 경고를 내지 않는다. 그 밖의 진단 글("Detected N diacritics")은 버린다
      await worker.setParameters({
        tessedit_pageseg_mode: layout === 'sparse' ? PSM.SPARSE_TEXT : PSM.AUTO,
        user_defined_dpi: '300',
        debug_file: '/dev/null',
        // 흰 글자·검은 바탕 줄은 찾지 않는다 (계약서에는 없고, 이걸 빼면 더 빨리 읽는다)
        tessedit_do_invert: '0',
      })
      const result = await worker.recognize(canvas, {}, { text: false, blocks: true })
      return (result.data.blocks ?? []) as unknown as { paragraphs: { lines: OcrLine[] }[] }[]
    } finally {
      progressTarget = null
      idleTimer = window.setTimeout(resetWorker, IDLE_MS)
    }
  })
  queue = job.catch(() => undefined)
  return job
}

/**
 * 2차 읽기용 사진: 그림자·조명 차이를 없앤 흑백(검은 글자, 흰 바탕)에서 표의 가로·세로 선을 지운다.
 * 선이 글자에 붙어 있으면 OCR이 그 칸을 통째로 놓치곤 한다. 밝기는 둘레 평균과 비교해 가른다(Bradley 방식).
 */
function withoutLines(source: HTMLCanvasElement): HTMLCanvasElement {
  const W = source.width
  const H = source.height
  const out = document.createElement('canvas')
  out.width = W
  out.height = H
  const ctx = out.getContext('2d', { willReadFrequently: true })
  if (!ctx) return source
  ctx.drawImage(source, 0, 0)
  const img = ctx.getImageData(0, 0, W, H)
  const d = img.data
  const n = W * H
  const gray = new Uint8Array(n)
  for (let i = 0, p = 0; i < n; i++, p += 4) gray[i] = (d[p] * 299 + d[p + 1] * 587 + d[p + 2] * 114) / 1000
  const dark = adaptiveDark(gray, W, H)
  // 글자 획보다 훨씬 긴 검은 줄만 선으로 본다 (가로는 폭의 5%, 세로는 높이의 3% 이상)
  const minH = Math.max(50, Math.round(W * 0.05))
  const minV = Math.max(50, Math.round(H * 0.03))
  const line = new Uint8Array(n)
  for (let y = 0; y < H; y++) {
    const row = y * W
    for (let x = 0; x < W; ) {
      if (!dark[row + x]) {
        x++
        continue
      }
      let e = x
      while (e < W && dark[row + e]) e++
      if (e - x >= minH) line.fill(1, row + x, row + e)
      x = e
    }
  }
  for (let x = 0; x < W; x++) {
    for (let y = 0; y < H; ) {
      if (!dark[y * W + x]) {
        y++
        continue
      }
      let e = y
      while (e < H && dark[e * W + x]) e++
      if (e - y >= minV) for (let k = y; k < e; k++) line[k * W + x] = 1
      y = e
    }
  }
  for (let i = 0, p = 0; i < n; i++, p += 4) {
    // 선과 그 둘레 한 픽셀은 흰색으로
    const onLine = line[i] || line[i - 1] || line[i + 1] || line[i - W] || line[i + W]
    const v = dark[i] && !onLine ? 0 : 255
    d[p] = d[p + 1] = d[p + 2] = v
  }
  ctx.putImageData(img, 0, 0)
  return out
}

/** 둘레(사진 폭의 1/12 네모) 평균보다 15% 이상 어두우면 글자·선으로 본다. 그림자가 져도 글자만 남는다 */
function adaptiveDark(gray: Uint8Array, W: number, H: number): Uint8Array {
  const half = Math.max(8, Math.round(W / 24))
  const stride = W + 1
  // 합계 표(integral image). 255 × 픽셀 수는 Uint32 범위 안이다 (사진은 긴 변 2,400px 이하)
  const sum = new Uint32Array(stride * (H + 1))
  for (let y = 0; y < H; y++) {
    let rowSum = 0
    for (let x = 0; x < W; x++) {
      rowSum += gray[y * W + x]
      sum[(y + 1) * stride + x + 1] = sum[y * stride + x + 1] + rowSum
    }
  }
  const dark = new Uint8Array(W * H)
  for (let y = 0; y < H; y++) {
    const y0 = Math.max(0, y - half)
    const y1 = Math.min(H - 1, y + half)
    for (let x = 0; x < W; x++) {
      const x0 = Math.max(0, x - half)
      const x1 = Math.min(W - 1, x + half)
      const count = (x1 - x0 + 1) * (y1 - y0 + 1)
      const total = sum[(y1 + 1) * stride + x1 + 1] - sum[y0 * stride + x1 + 1] - sum[(y1 + 1) * stride + x0] + sum[y0 * stride + x0]
      if (gray[y * W + x] * count < total * 0.85) dark[y * W + x] = 1
    }
  }
  return dark
}

function resetWorker() {
  window.clearTimeout(idleTimer)
  const current = workerPromise
  workerPromise = null
  current?.then((w) => w.terminate()).catch(() => undefined)
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('ocr timeout')), ms)
    promise.then(
      (value) => {
        window.clearTimeout(timer)
        resolve(value)
      },
      (err) => {
        window.clearTimeout(timer)
        reject(err)
      },
    )
  })
}
