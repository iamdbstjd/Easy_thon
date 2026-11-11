// 업로드 파일 확인과 계약서 사진 줄이기

export const MAX_FILE_BYTES = 10 * 1024 * 1024
const LONG_EDGE_PX = 1600
const JPEG_QUALITY = 0.9

const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']

export function isPdfFile(file: File): boolean {
  return file.type === 'application/pdf' || /\.pdf$/i.test(file.name)
}

export function isImageFile(file: File): boolean {
  return IMAGE_TYPES.includes(file.type) || /\.(jpe?g|png|webp)$/i.test(file.name)
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

type Decoded = { source: CanvasImageSource; width: number; height: number; release: () => void }

async function decodeImage(file: File): Promise<Decoded> {
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
 * 계약서 사진을 긴 변 1,600px 이하로 줄이고 JPEG(품질 0.9)로 다시 저장한다.
 * 더 작은 사진은 키우지 않는다. 다시 저장하면서 사진의 위치 정보 같은 메타데이터도 빠진다.
 */
export async function resizeContractPhoto(file: File): Promise<File> {
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
    const base = file.name.replace(/\.[^.]+$/, '') || 'contract'
    return new File([blob], `${base}.jpg`, { type: 'image/jpeg', lastModified: Date.now() })
  } finally {
    image.release()
  }
}

const TOO_BIG = '10MB 이하 파일만 올릴 수 있어요.'

/** 등기부 PDF 확인 (S2·S6). 문제가 있으면 화면에 보여줄 문장, 없으면 null */
export async function checkRegistryFile(file: File): Promise<string | null> {
  if (!isPdfFile(file)) return '등기부는 PDF 파일만 올릴 수 있어요.'
  if (file.size > MAX_FILE_BYTES) {
    return `${TOO_BIG} 인터넷등기소에서 '현재 유효사항'으로 다시 열람해 보세요.`
  }
  if (!(await hasPdfHeader(file))) {
    return 'PDF 파일이 아닌 것 같아요. 인터넷등기소에서 저장한 PDF를 올려주세요.'
  }
  return null
}

/**
 * 계약서 파일 준비 (S2·S6). PDF는 그대로 보내고(크기·머리글만 확인),
 * 사진은 먼저 줄여서 다시 저장한 뒤 줄인 파일로 10MB를 확인한다.
 */
export async function prepareContractFile(file: File): Promise<{ file: File } | { error: string }> {
  if (isPdfFile(file)) {
    if (file.size > MAX_FILE_BYTES) return { error: TOO_BIG }
    if (!(await hasPdfHeader(file))) return { error: 'PDF 파일이 아닌 것 같아요. 다른 파일을 골라 주세요.' }
    return { file }
  }
  if (!isImageFile(file)) return { error: '계약서는 사진(JPG·PNG·WEBP)이나 PDF만 올릴 수 있어요.' }
  try {
    const resized = await resizeContractPhoto(file)
    if (resized.size > MAX_FILE_BYTES) return { error: TOO_BIG }
    return { file: resized }
  } catch {
    return { error: '사진을 열지 못했어요. 다른 사진을 골라 주세요.' }
  }
}
