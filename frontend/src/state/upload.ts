// S2 업로드 화면의 입력값. 오류 화면에서 "서류 다시 고르기"로 돌아와도 남아 있도록 App이 들고 있는다.

import type { ManualInput } from '../api/types'
import { digitsToNumber } from '../lib/format'

/** 직접 입력. 금액은 숫자만 담은 문자열, 날짜는 "YYYY-MM-DD" 또는 "" */
export interface ManualDraft {
  deposit: string
  monthly_rent: string
  contract_date: string
  landlord_name: string
  prior_deposits: string
  market_price: string
}

export interface UploadDraft {
  registry: File | null
  /** 보낼 계약서 파일 (사진이면 이미 줄인 JPEG) */
  contract: File | null
  manual: ManualDraft
}

export const EMPTY_MANUAL_DRAFT: ManualDraft = {
  deposit: '',
  monthly_rent: '',
  contract_date: '',
  landlord_name: '',
  prior_deposits: '',
  market_price: '',
}

export function emptyUploadDraft(): UploadDraft {
  return { registry: null, contract: null, manual: { ...EMPTY_MANUAL_DRAFT } }
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
    market_price: digitsToNumber(d.market_price),
  }
}
