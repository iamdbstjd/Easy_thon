// 고른 서류 파일 (등기부·계약서 공통, S2·S6·수정된 계약서 올리기).
// 한 서류를 여러 파일로 올릴 수 있다 (쪽마다 찍은 사진, 나눠 저장한 PDF). 올린 순서대로 보낸다.
// 계약서 사진이면 가리기 전 사진을 메모리에만 들고 있다가, 서버로 보내는 순간 버린다. 어디에도 저장하지 않는다.

import { ApiError } from '../api/errors'
import { maskedPhotoFile } from '../lib/photoMask'
import type { MaskMark } from '../lib/photoMask'

export interface FilePick {
  /** 화면 안에서만 쓰는 구분 값 (목록의 key, 가리기 창 열기) */
  id: string
  /** 서버로 보낼 파일. 사진이면 줄인(계약서는 가린) JPEG, PDF면 고른 파일 그대로 */
  file: File
  kind: 'photo' | 'pdf'
  /** 가리기 전 사진(줄인 JPEG). 다시 가리기·되돌리기에 쓴다. 가릴 수 없는 파일이거나 보낸 뒤에는 null */
  source: File | null
  /** 가린 곳 (사진 픽셀 좌표) */
  marks: MaskMark[]
}

let nextPickId = 0

export function newPick(file: File, kind: FilePick['kind'], maskable: boolean): FilePick {
  nextPickId += 1
  return { id: `pick-${nextPickId}`, file, kind, source: maskable && kind === 'photo' ? file : null, marks: [] }
}

/**
 * 서버로 보낼 파일 하나. 가린 곳이 있으면 가리기 전 사진에 칠해서 새로 만든다.
 * 가리지 못하면 가리기 전 사진을 대신 보내지 않고 오류를 낸다.
 */
export async function contractFileToSend(pick: FilePick | null): Promise<File | null> {
  if (!pick) return null
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

/** 보낸 뒤의 상태: 보낸 파일만 남기고 가리기 전 사진은 버린다 */
export function sentPick(pick: FilePick, sent: File): FilePick {
  return { ...pick, file: sent, source: null }
}

export function sentPicks(picks: FilePick[], sent: File[]): FilePick[] {
  return picks.map((pick, i) => sentPick(pick, sent[i] ?? pick.file))
}
