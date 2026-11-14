// 고른 서류 파일 (등기부·계약서 공통, S2·S6·수정된 계약서 올리기).
// 한 서류를 여러 파일로 올릴 수 있다 (쪽마다 찍은 사진, 나눠 저장한 PDF). 올린 순서대로 보낸다.
// 계약서 사진이면 가리기 전 사진을 메모리에만 들고 있다가, 서버로 보내는 순간 버린다. 어디에도 저장하지 않는다.
// 계약서 PDF는 쪽마다 그림으로 바꿔(lib/pdfPages.ts) 사진처럼 가린다. 가린 곳이 있으면 글자 층 없이 가린 그림만 담은
// PDF로 다시 만들어 보내고, 가린 곳이 없으면 원래 PDF를 그대로 보낸다.

import { ApiError } from '../api/errors'
import { maskedPdf } from '../lib/pdfPages'
import { maskedPhotoFile } from '../lib/photoMask'
import type { MaskMark } from '../lib/photoMask'

/** 계약서 PDF의 한 쪽 (가리기용 그림) */
export interface PagePick {
  id: string
  /** 쪽 그림 (JPEG). 보낸 뒤에는 null */
  source: File | null
  /** 그림 픽셀 크기 */
  width: number
  height: number
  /** 원래 쪽 크기 (pt) */
  size: [number, number]
  /** 가린 곳 (그림 픽셀 좌표). 자동으로 찾은 곳이 앞에 온다 */
  marks: MaskMark[]
  auto: 'pending' | 'done'
  autoFound: number
  /** 자동 가리기를 하지 못했다 (글자 읽기 파일을 못 받는 등) */
  autoFailed: boolean
  /** PDF 글자 층에서 찾은 번호. 있으면 글자 읽기(OCR) 대신 쓴다. 글자 층이 없는 쪽은 null */
  textMarks: MaskMark[] | null
}

export interface FilePick {
  /** 화면 안에서만 쓰는 구분 값 (목록의 key, 가리기 창 열기) */
  id: string
  /** 서버로 보낼 파일. 사진이면 줄인(계약서는 가린) JPEG, PDF면 고른 파일 그대로 */
  file: File
  kind: 'photo' | 'pdf'
  /** 가리기 전 사진(줄인 JPEG). 다시 가리기·되돌리기에 쓴다. 가릴 수 없는 파일이거나 보낸 뒤에는 null */
  source: File | null
  /** 가린 곳 (사진 픽셀 좌표). 자동으로 찾은 곳(auto)이 앞에, 사용자가 끈 네모가 뒤에 온다 */
  marks: MaskMark[]
  /** 자동 가리기 (lib/autoMask.ts): 가릴 수 있는 사진이면 고르자마자 'pending', 다 찾으면 'done' */
  auto: 'off' | 'pending' | 'done'
  /** 자동으로 찾아 가린 곳의 수 (사용자가 지워도 그대로) */
  autoFound: number
  /** 자동 가리기를 하지 못했다 (사진이면 그 사진, PDF면 한 쪽이라도) */
  autoFailed: boolean
  /**
   * 계약서 PDF를 쪽마다 그림으로 바꾼 것. 바꾸는 중이거나(auto 'pending') 바꾸지 못했거나 PDF가 아니면 null.
   * PDF는 쪽을 다 바꾸고 쪽마다 자동 가리기까지 끝나야 auto가 'done'이 된다.
   */
  pages: PagePick[] | null
}

let nextPickId = 0

export function newPick(file: File, kind: FilePick['kind'], maskable: boolean): FilePick {
  nextPickId += 1
  const photo = maskable && kind === 'photo'
  return {
    id: `pick-${nextPickId}`,
    file,
    kind,
    source: photo ? file : null,
    marks: [],
    auto: maskable ? 'pending' : 'off',
    autoFound: 0,
    autoFailed: false,
    pages: null,
  }
}

/**
 * 서버로 보낼 파일 하나. 가린 곳이 있으면 가리기 전 사진에 칠해서 새로 만든다.
 * 가리지 못하면 가리기 전 사진을 대신 보내지 않고 오류를 낸다.
 */
export async function contractFileToSend(pick: FilePick | null): Promise<File | null> {
  if (!pick) return null
  if (pick.kind === 'pdf') {
    const pages = pick.pages
    if (!pages || !pages.some((page) => page.marks.length > 0)) return pick.file
    try {
      return await maskedPdf(
        pages.map((page) => {
          if (!page.source) throw new Error('page image released')
          return { image: page.source, width: page.width, height: page.height, size: page.size, marks: page.marks }
        }),
        pick.file.name,
      )
    } catch {
      throw new ApiError('PDF를 가리는 중 문제가 생겼어요. 계약서 PDF를 다시 골라 주세요.', 'MASK_FAILED', null, 'contract')
    }
  }
  if (pick.kind !== 'photo' || !pick.source || pick.marks.length === 0) return pick.file
  try {
    return await maskedPhotoFile(pick.source, pick.marks)
  } catch {
    throw new ApiError('사진을 가리는 중 문제가 생겼어요. 계약서 사진을 다시 골라 주세요.', 'MASK_FAILED', null, 'contract')
  }
}

/** 서버로 보낼 파일들 (올린 순서 그대로) */
export async function filesToSend(picks: FilePick[]): Promise<File[]> {
  const files: File[] = []
  for (const pick of picks) {
    const file = await contractFileToSend(pick)
    if (file) files.push(file)
  }
  return files
}

/** 보낸 뒤의 상태: 보낸 파일만 남기고 가리기 전 사진·쪽 그림은 버린다 */
export function sentPick(pick: FilePick, sent: File): FilePick {
  return { ...pick, file: sent, source: null, pages: pick.pages?.map((page) => ({ ...page, source: null })) ?? null }
}

/** 가린 곳의 수 (사진이면 그 사진, PDF면 모든 쪽) */
export function markCount(pick: FilePick): number {
  return pick.pages ? pick.pages.reduce((n, page) => n + page.marks.length, 0) : pick.marks.length
}

export function sentPicks(picks: FilePick[], sent: File[]): FilePick[] {
  return picks.map((pick, i) => sentPick(pick, sent[i] ?? pick.file))
}
