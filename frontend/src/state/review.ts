// S4 내용 확인·수정 화면의 입력값과 CheckRequest 사이의 변환.
// 사용자가 손대지 않은 칸은 서버에서 받은 값을 그대로 돌려보낸다 (형식이 바뀌지 않도록).

import type { CheckRequest, ContractExtract, ManualInput, RegistryExtract } from '../api/types'
import {
  digitsToNumber,
  isoToLocalInput,
  localInputToIso,
  numberToDigits,
} from '../lib/format'
import { maskPersonal } from '../lib/mask'

/** 화면의 입력 칸. 금액은 숫자만 담은 문자열, 날짜는 "YYYY-MM-DD", 열람 일시는 "YYYY-MM-DDTHH:mm" */
export interface ReviewForm {
  regAddressJibun: string
  regAddressRoad: string
  regDong: string
  regHo: string
  regViewedAt: string

  conLandlords: string
  conAddress: string
  conDong: string
  conHo: string
  conDeposit: string
  conMonthlyRent: string
  conContractDate: string
  conBalanceDate: string

  manDeposit: string
  manMonthlyRent: string
  manContractDate: string
  manLandlordName: string
  manPriorDeposits: string
  manMarketPrice: string
}

function dateInput(value: string | null | undefined): string {
  const head = (value ?? '').slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(head) ? head : ''
}

/**
 * 화면에 처음 보여줄 값. 이름·주소에 주민등록번호 모양이 섞여 있으면 가려서 보여준다.
 * 손대지 않은 칸은 requestFromForm이 원래 값을 그대로 돌려보내므로, 가린 글자가 서버로 가지 않는다.
 */
export function formFromRequest(req: CheckRequest): ReviewForm {
  const r = req.registry
  const c = req.contract
  const m = req.manual
  const shown = (v: string | null | undefined) => maskPersonal(v ?? '')
  return {
    regAddressJibun: shown(r.address_jibun),
    regAddressRoad: shown(r.address_road),
    regDong: r.unit.dong ?? '',
    regHo: r.unit.ho ?? '',
    regViewedAt: isoToLocalInput(r.viewed_at),

    conLandlords: c ? c.landlord_names.map(shown).join(', ') : '',
    conAddress: shown(c?.address),
    conDong: c?.unit.dong ?? '',
    conHo: c?.unit.ho ?? '',
    conDeposit: numberToDigits(c?.deposit ?? null),
    conMonthlyRent: numberToDigits(c?.monthly_rent ?? null),
    conContractDate: dateInput(c?.contract_date),
    conBalanceDate: dateInput(c?.balance_date),

    manDeposit: numberToDigits(m.deposit),
    manMonthlyRent: numberToDigits(m.monthly_rent),
    manContractDate: dateInput(m.contract_date),
    manLandlordName: shown(m.landlord_name),
    manPriorDeposits: numberToDigits(m.prior_deposits),
    manMarketPrice: numberToDigits(m.market_price),
  }
}

function text(value: string): string | null {
  const t = value.trim()
  return t === '' ? null : t
}

/** "이○○, 김○○" → ["이○○", "김○○"] */
function splitNames(value: string): string[] {
  return value
    .split(/[,，]/)
    .map((name) => name.trim())
    .filter((name) => name !== '')
}

export function requestFromForm(
  req: CheckRequest,
  form: ReviewForm,
  initial: ReviewForm,
): CheckRequest {
  function edited<T>(key: keyof ReviewForm, original: T, parse: (value: string) => T): T {
    return form[key] === initial[key] ? original : parse(form[key])
  }
  const date = (v: string) => (v === '' ? null : v)

  const r = req.registry
  const registry: RegistryExtract = {
    ...r,
    address_jibun: edited('regAddressJibun', r.address_jibun, text),
    address_road: edited('regAddressRoad', r.address_road, text),
    unit: {
      ...r.unit,
      dong: edited('regDong', r.unit.dong, text),
      ho: edited('regHo', r.unit.ho, text),
    },
    viewed_at: edited('regViewedAt', r.viewed_at, (v) => (v === '' ? null : localInputToIso(v))),
  }

  const c = req.contract
  const contract: ContractExtract | null = c && {
    ...c,
    landlord_names: edited('conLandlords', c.landlord_names, splitNames),
    address: edited('conAddress', c.address, text),
    unit: {
      ...c.unit,
      dong: edited('conDong', c.unit.dong, text),
      ho: edited('conHo', c.unit.ho, text),
    },
    deposit: edited('conDeposit', c.deposit, digitsToNumber),
    monthly_rent: edited('conMonthlyRent', c.monthly_rent, digitsToNumber),
    contract_date: edited('conContractDate', c.contract_date, date),
    balance_date: edited('conBalanceDate', c.balance_date, date),
  }

  const m = req.manual
  const manual: ManualInput = {
    deposit: edited('manDeposit', m.deposit, digitsToNumber),
    monthly_rent: edited('manMonthlyRent', m.monthly_rent, digitsToNumber),
    contract_date: edited('manContractDate', m.contract_date, date),
    landlord_name: edited('manLandlordName', m.landlord_name, text),
    prior_deposits: edited('manPriorDeposits', m.prior_deposits, digitsToNumber),
    market_price: edited('manMarketPrice', m.market_price, digitsToNumber),
  }

  return { ...req, registry, contract, manual }
}

/**
 * [빠진 내용 채우기]로 S4에 왔을 때 먼저 보여줄 칸.
 * 확인하지 못한 규칙(⚪) 가운데 S4에서 고칠 수 있는 칸이 비어 있으면, 화면 순서대로 첫 칸을 고른다.
 * (R1 임대인 이름, R5 보증금·시세, R11 계약서 주소, R13 열람 일시)
 */
export function missingField(
  unknownRules: string[],
  form: ReviewForm,
  hasContract: boolean,
): keyof ReviewForm | null {
  const unknown = new Set(unknownRules)
  const candidates: [string, keyof ReviewForm][] = [
    ['R13', 'regViewedAt'],
    ...(hasContract
      ? ([
          ['R1', 'conLandlords'],
          ['R11', 'conAddress'],
          ['R5', 'conDeposit'],
        ] as [string, keyof ReviewForm][])
      : ([
          ['R5', 'manDeposit'],
          ['R1', 'manLandlordName'],
        ] as [string, keyof ReviewForm][])),
    ['R5', 'manMarketPrice'],
  ]
  for (const [rule, key] of candidates) {
    if (unknown.has(rule) && form[key].trim() === '') return key
  }
  return null
}
