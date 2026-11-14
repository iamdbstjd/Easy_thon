// S2 업로드 화면의 입력값. 오류 화면에서 "서류 다시 고르기"로 돌아와도 남아 있도록 App이 들고 있는다.

import type { ManualInput } from '../api/types'
import { digitsToNumber } from '../lib/format'
import type { FilePick } from './contract'

/** 직접 입력. 금액은 숫자만 담은 문자열, 날짜는 "YYYY-MM-DD" 또는 "" */
export interface ManualDraft {
  deposit: string
  monthly_rent: string
  contract_date: string
  landlord_name: string
  prior_deposits: string
}

export interface UploadDraft {
  /** 등기부 파일들 (한 등기부를 나눈 PDF·사진, 올린 순서) */
  registry: FilePick[]
  /** 계약서 파일들 (사진이면 줄이고 가린 JPEG, 올린 순서). 없으면 빈 목록 */
  contract: FilePick[]
  manual: ManualDraft
  /** 서류를 AI로 보내는 것에 대한 확인 (메모리에만) */
  consent: boolean
}

export const EMPTY_MANUAL_DRAFT: ManualDraft = {
  deposit: '',
  monthly_rent: '',
  contract_date: '',
  landlord_name: '',
  prior_deposits: '',
}

export function emptyUploadDraft(): UploadDraft {
  return { registry: [], contract: [], manual: { ...EMPTY_MANUAL_DRAFT }, consent: false }
}

export function hasManualValues(manual: ManualDraft): boolean {
  return Object.values(manual).some((v) => v.trim() !== '')
}

export function manualFromDraft(d: ManualDraft): ManualInput {
  return {
    deposit: digitsToNumber(d.deposit),
    monthly_rent: digitsToNumber(d.monthly_rent),
    contract_date: d.contract_date || null,
    landlord_name: d.landlord_name.trim() || null,
    prior_deposits: digitsToNumber(d.prior_deposits),
    market_price: null, // 시세는 실거래로 찾아 넣고, 읽은 내용 확인 화면에서 고친다
  }
}
