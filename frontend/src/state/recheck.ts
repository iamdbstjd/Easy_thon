// S6 계약 후 재확인: 올릴 파일과, 읽은 뒤 확인하는 날짜 칸 ↔ RecheckRequest 변환.
// 계약 당시 등기부나 결과는 어디에도 저장하지 않는다. 같은 화면 흐름의 상태로만 이어 준다.

import type { ContractExtract, RecheckRequest } from '../api/types'
import { isoToLocalInput, localInputToIso } from '../lib/format'
import type { ContractPick } from './contract'

/** S5(또는 S7)에서 이어 받은 계약서와, 계약 때 본 등기부의 열람 일시. 예시 계약서는 이어 받지 않는다 */
export interface RecheckCarry {
  contract: ContractExtract
  baselineViewedAt: string | null
}

export interface RecheckUpload {
  registry: File | null
  contract: ContractPick | null
  /** 서류를 AI로 보내는 것에 대한 확인 (메모리에만) */
  consent: boolean
}

export function emptyRecheckUpload(): RecheckUpload {
  return { registry: null, contract: null, consent: false }
}

/** 읽은 뒤 확인하는 칸. 날짜는 "YYYY-MM-DD", 열람 일시는 "YYYY-MM-DDTHH:mm" */
export interface RecheckForm {
  contractDate: string
  balanceDate: string
  moveInDate: string
  viewedAt: string
}

function dateInput(value: string | null | undefined): string {
  const head = (value ?? '').slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(head) ? head : ''
}

export function recheckFormFrom(req: RecheckRequest): RecheckForm {
  return {
    contractDate: dateInput(req.contract.contract_date),
    balanceDate: dateInput(req.contract.balance_date),
    moveInDate: dateInput(req.contract.move_in_date),
    viewedAt: isoToLocalInput(req.registry.viewed_at),
  }
}

/** 손대지 않은 칸은 받은 값을 그대로 돌려보낸다 */
export function recheckRequestFrom(
  req: RecheckRequest,
  form: RecheckForm,
  initial: RecheckForm,
): RecheckRequest {
  function edited<T>(key: keyof RecheckForm, original: T, parse: (value: string) => T): T {
    return form[key] === initial[key] ? original : parse(form[key])
  }
  const date = (v: string) => (v === '' ? null : v)
  return {
    ...req,
    registry: {
      ...req.registry,
      viewed_at: edited('viewedAt', req.registry.viewed_at, (v) => (v === '' ? null : localInputToIso(v))),
    },
    contract: {
      ...req.contract,
      contract_date: edited('contractDate', req.contract.contract_date, date),
      balance_date: edited('balanceDate', req.contract.balance_date, date),
      move_in_date: edited('moveInDate', req.contract.move_in_date, date),
    },
  }
}
