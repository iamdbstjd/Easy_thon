// 업로드 파일 확인과 사진 줄이기 (등기부·계약서 공통)
// 서버 상한(backend/app/uploads.py)과 같은 값을 쓴다.

export const MAX_FILE_BYTES = 10 * 1024 * 1024
/** 서류(등기부·계약서)마다 파일 수 */
export const MAX_FILES = 10
/** 한 번에 보내는 파일 전체 (등기부 + 계약서) */
export const MAX_TOTAL_BYTES = 20 * 1024 * 1024
const LONG_EDGE_PX = 1600
export const JPEG_QUALITY = 0.9

/** 파일 고르기 창에 보여 줄 형식: PDF와 브라우저가 열 수 있는 사진 (휴대폰에서는 카메라도) */
export const UPLOAD_ACCEPT = 'application/pdf,.pdf,image/*,.heic,.heif'

export type DocKind = 'registry' | 'contract'

export function isPdfFile(file: File): boolean {
  return file.type === 'application/pdf' || /\.pdf$/i.test(file.name)
}

/** 사진으로 보이는 파일 (형식은 따지지 않는다. 열 수 있는지는 줄이면서 확인한다) */
export function isImageFile(file: File): boolean {
  return file.type.startsWith('image/') || /\.(jpe?g|png|webp|gif|bmp|heic|heif|avif|tiff?)$/i.test(file.name)
}

/** 파일 앞부분에 PDF 머리글(%PDF-)이 있는지 본다. 확장자만 바꾼 파일을 걸러낸다. */
export async function hasPdfHeader(file: File): Promise<boolean> {
  try {
    const head = await file.slice(0, 1024).text()
    return head.includes('%PDF-')
  } catch {
    return false
  }
}

export type Decoded = { source: CanvasImageSource; width: number; height: number; release: () => void }

export async function decodeImage(file: File): Promise<Decoded> {
  if (typeof createImageBitmap === 'function') {
    try {
      // 휴대폰 사진의 회전 정보(EXIF)를 반영해서 읽는다.
      const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
      return { source: bitmap, width: bitmap.width, height: bitmap.height, release: () => bitmap.close() }
    } catch {
      // 아래 <img> 방식으로 다시 시도한다
    }
  }
  const url = URL.createObjectURL(file)
  const img = new Image()
  img.src = url
  try {
    await img.decode()
  } catch (err) {
    URL.revokeObjectURL(url)
    throw err
  }
  return {
    source: img,
    width: img.naturalWidth,
    height: img.naturalHeight,
    release: () => URL.revokeObjectURL(url),
  }
}

/**
 * 사진을 긴 변 1,600px 이하로 줄이고 JPEG(품질 0.9)로 다시 저장한다. PNG·WEBP·HEIC 등도 JPEG가 된다.
 * 더 작은 사진은 키우지 않는다. 다시 저장하면서 사진의 위치 정보 같은 메타데이터도 빠진다.
 */
export async function resizePhoto(file: File): Promise<File> {
  const image = await decodeImage(file)
  try {
    const scale = Math.min(1, LONG_EDGE_PX / Math.max(image.width, image.height))
    const width = Math.max(1, Math.round(image.width * scale))
    const height = Math.max(1, Math.round(image.height * scale))

    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('canvas 2d context unavailable')
    // 투명한 PNG가 JPEG에서 검게 나오지 않도록 흰 바탕을 먼저 칠한다.
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, width, height)
    ctx.imageSmoothingEnabled = true
    ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(image.source, 0, 0, width, height)

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY),
    )
    if (!blob) throw new Error('jpeg encoding failed')
    const base = file.name.replace(/\.[^.]+$/, '') || 'photo'
    return new File([blob], `${base}.jpg`, { type: 'image/jpeg', lastModified: Date.now() })
  } finally {
    image.release()
  }
}

const TOO_BIG = '10MB 이하 파일만 올릴 수 있어요.'
const DOC_NAME: Record<DocKind, string> = { registry: '등기부', contract: '계약서' }

export type PreparedFile = { file: File; kind: 'pdf' | 'photo' }

/**
 * 올릴 파일 하나 준비 (등기부·계약서 공통). PDF는 그대로 보내고(크기·머리글만 확인),
 * 사진은 형식과 상관없이 먼저 줄여서 JPEG로 다시 저장한 뒤 줄인 파일로 10MB를 확인한다.
 * 문제가 있으면 화면에 보여 줄 문장을 돌려준다.
 */
export async function prepareUploadFile(file: File, doc: DocKind): Promise<PreparedFile | { error: string }> {
  if (isPdfFile(file)) {
    if (file.size > MAX_FILE_BYTES) {
      return {
        error: doc === 'registry' ? `${TOO_BIG} 인터넷등기소에서 '현재 유효사항'으로 다시 열람해 보세요.` : TOO_BIG,
      }
    }
    if (!(await hasPdfHeader(file))) return { error: 'PDF 파일이 아닌 것 같아요. 다른 파일을 골라 주세요.' }
    return { file, kind: 'pdf' }
  }
  if (!isImageFile(file)) return { error: `${DOC_NAME[doc]}는 PDF나 사진(JPG·PNG 등)만 올릴 수 있어요.` }
  try {
    const resized = await resizePhoto(file)
    if (resized.size > MAX_FILE_BYTES) return { error: TOO_BIG }
    return { file: resized, kind: 'photo' }
  } catch {
    return { error: '사진을 열지 못했어요. JPG나 PNG로 바꿔서 올려 주세요.' }
  }
}

/** 고른 파일들을 이름 순서로 (page2가 page10보다 앞). 쪽마다 찍은 사진을 한 번에 고르는 경우를 위해서다 */
export function byFileName(files: File[]): File[] {
  return [...files].sort((a, b) => a.name.localeCompare(b.name, 'ko', { numeric: true, sensitivity: 'base' }))
}

export function totalBytes(files: File[]): number {
  return files.reduce((sum, f) => sum + f.size, 0)
}
