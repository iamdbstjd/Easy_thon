// 업로드 파일 확인과 계약서 사진 줄이기 (PRD F1·F2)

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
