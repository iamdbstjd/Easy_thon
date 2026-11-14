// 검토서 PDF 파일의 순수한 부분: 쪽 나누기와, JPEG 그림만 담는 작은 PDF 작성기.
// 화면을 그림으로 뜨는 부분은 reportPdf.ts에 있다.

/** 세로 구간 [위, 아래] (px) */
export type Span = [number, number]

/** 다음 쪽 첫 줄 위에 남기는 빈칸 (px) */
const GAP = 6

/** 겹치는 구간을 합친다. 맞닿기만 한 구간은 그 사이에서 자를 수 있게 둔다 */
export function mergeSpans(spans: Span[]): Span[] {
  const sorted = spans.filter(([a, b]) => b > a).sort((x, y) => x[0] - y[0])
  const out: Span[] = []
  for (const [a, b] of sorted) {
    const last = out.at(-1)
    if (last && a < last[1]) last[1] = Math.max(last[1], b)
    else out.push([a, b])
  }
  return out
}

/** limit보다 위에서 자를 수 있는 가장 아래 자리 (구간 사이 빈칸). min보다 위로 올라가야 하면 null */
function cutAbove(spans: Span[], limit: number, min: number): number | null {
  let free = 0 // 앞 구간이 끝난 곳. 여기부터 다음 구간 전까지는 빈칸
  for (const [a, b] of spans) {
    if (a >= limit) return Math.min(limit, Math.max(free, a - GAP))
    if (b > limit) {
      const y = Math.max(free, a - GAP)
      return y >= min ? y : null
    }
    free = b
  }
  return limit
}

/**
 * 쪽을 나눌 자리(px)를 고른다. 글줄(lines)은 자르지 않고, 덩어리(blocks: 표의 한 줄, 위험 신호 하나 등)는
 * 되도록 자르지 않는다. 쪽마다 적어도 60%는 채운다. 돌려주는 값에 0과 맨 끝(total)은 없다.
 */
export function pageCuts(total: number, pageHeight: number, lines: Span[], blocks: Span[]): number[] {
  const hard = mergeSpans(lines)
  const soft = mergeSpans([...lines, ...blocks])
  const cuts: number[] = []
  let top = 0
  while (total - top > pageHeight) {
    const limit = top + pageHeight
    const min = top + pageHeight * 0.6
    const y = cutAbove(soft, limit, min) ?? cutAbove(hard, limit, min) ?? limit
    top = Math.floor(y)
    cuts.push(top)
  }
  return cuts
}

/** PDF에 넣을 JPEG 한 장 */
export interface JpegPage {
  data: Uint8Array
  /** 픽셀 크기 */
  width: number
  height: number
  /** 쪽 크기 (pt). 없으면 A4 */
  size?: [number, number]
}

/** A4 (pt) */
const A4: [number, number] = [595.28, 841.89]

/** 쪽마다 JPEG 한 장을 한 면(기본 A4)에 꽉 채운 PDF 파일 내용. 제목은 문서 정보(/Title)에 넣는다 */
export function jpegPdf(pages: JpegPage[], title: string): Uint8Array<ArrayBuffer> {
  const enc = new TextEncoder()
  const parts: Uint8Array[] = []
  const offsets: number[] = []
  let size = 0
  const put = (chunk: string | Uint8Array) => {
    const bytes = typeof chunk === 'string' ? enc.encode(chunk) : chunk
    parts.push(bytes)
    size += bytes.length
  }
  const obj = (id: number, dict: string, stream?: Uint8Array) => {
    offsets[id] = size
    put(`${id} 0 obj\n${dict}\n`)
    if (stream) {
      put('stream\n')
      put(stream)
      put('\nendstream\n')
    }
    put('endobj\n')
  }

  // 1 문서, 2 쪽 목록, 3 문서 정보, 그 뒤로 쪽마다 [쪽, 그림, 그리기] 세 개씩
  put('%PDF-1.4\n%âãÏÓ\n')
  obj(1, '<< /Type /Catalog /Pages 2 0 R >>')
  obj(2, `<< /Type /Pages /Kids [${pages.map((_, i) => `${4 + i * 3} 0 R`).join(' ')}] /Count ${pages.length} >>`)
  obj(3, `<< /Title ${pdfString(title)} /Producer (jipkimi) >>`)
  pages.forEach((page, i) => {
    const id = 4 + i * 3
    const [w, h] = page.size ?? A4
    obj(
      id,
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${w} ${h}] ` +
        `/Resources << /XObject << /Im ${id + 1} 0 R >> >> /Contents ${id + 2} 0 R >>`,
    )
    obj(
      id + 1,
      `<< /Type /XObject /Subtype /Image /Width ${page.width} /Height ${page.height} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.data.length} >>`,
      page.data,
    )
    const draw = enc.encode(`q ${w} 0 0 ${h} 0 0 cm /Im Do Q`)
    obj(id + 2, `<< /Length ${draw.length} >>`, draw)
  })

  const count = 4 + pages.length * 3
  const xref = size
  put(`xref\n0 ${count}\n0000000000 65535 f \n`)
  for (let id = 1; id < count; id++) put(`${String(offsets[id]).padStart(10, '0')} 00000 n \n`)
  put(`trailer\n<< /Size ${count} /Root 1 0 R /Info 3 0 R >>\nstartxref\n${xref}\n%%EOF\n`)

  const out = new Uint8Array(new ArrayBuffer(size))
  let at = 0
  for (const part of parts) {
    out.set(part, at)
    at += part.length
  }
  return out
}

/** PDF 글자열. 한글이 있어서 UTF-16BE(앞에 FEFF)를 16진수로 쓴다 */
function pdfString(text: string): string {
  let hex = 'FEFF'
  for (let i = 0; i < text.length; i++) hex += text.charCodeAt(i).toString(16).padStart(4, '0').toUpperCase()
  return `<${hex}>`
}
