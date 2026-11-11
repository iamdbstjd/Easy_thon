// 고른 계약서 파일 하나 (S2·S6·수정된 계약서 올리기).
// 사진이면 가리기 전 사진을 메모리에만 들고 있다가, 서버로 보내는 순간 버린다. 어디에도 저장하지 않는다.

import { ApiError } from '../api/errors'
import { maskedPhotoFile } from '../lib/photoMask'
import type { MaskMark } from '../lib/photoMask'

export interface ContractPick {
  /** 서버로 보낼 파일. 사진이면 줄이고 가린 JPEG, PDF면 고른 파일 그대로 */
  file: File
  kind: 'photo' | 'pdf'
  /** 가리기 전 사진(줄인 JPEG). 다시 가리기·되돌리기에 쓴다. 보낸 뒤에는 null */
  source: File | null
  /** 가린 곳 (사진 픽셀 좌표) */
  marks: MaskMark[]
}

/** 보낸 뒤: 가리기 전 사진을 버린다 (보낸 파일과 가린 곳 수는 화면 안내용으로 남긴다) */
export function dropSource(pick: ContractPick | null): ContractPick | null {
  return pick && pick.source ? { ...pick, source: null } : pick
}

/**
 * 서버로 보낼 계약서 파일. 가린 곳이 있으면 가리기 전 사진에 칠해서 새로 만든다.
 * 가리지 못하면 가리기 전 사진을 대신 보내지 않고 오류를 낸다.
 */
export async function contractFileToSend(pick: ContractPick | null): Promise<File | null> {
  if (!pick) return null
  if (pick.kind !== 'photo' || !pick.source || pick.marks.length === 0) return pick.file
  try {
    return await maskedPhotoFile(pick.source, pick.marks)
  } catch {
    throw new ApiError('사진을 가리는 중 문제가 생겼어요. 계약서 사진을 다시 골라 주세요.', 'MASK_FAILED', null, 'contract')
  }
}

/** 보낸 뒤의 상태: 보낸 파일만 남기고 가리기 전 사진은 버린다 */
export function sentPick(pick: ContractPick, sent: File): ContractPick {
  return { ...pick, file: sent, source: null }
}
