// 개발용 가짜 데이터. 주소에 ?mock=1이 있을 때만 쓴다 (src/api/client.ts).
// 예시 A·B·C와 규칙 문구를 따른다. 실제 예시 데이터는 백엔드 demo/*.json이 기준이다.

import type {
  Amendment,
  AmendmentFix,
  CheckRequest,
  ComparisonRow,
  RecheckRequest,
  Report,
  RuleResult,
} from '../api/types'
import { RULE_NAMES } from '../api/types'

export const DISCLAIMER =
  '이 결과는 올려주신 서류와 공개 데이터를 정해진 기준으로 확인한 참고 정보예요. 법률 자문이 아니며 보증금의 안전을 보장하지 않아요. 중요한 결정 전에는 대한법률구조공단(국번 없이 132) 등 전문가와 상의하세요.'

const GENERATED_AT = '2026-11-14T19:02:00+09:00'
const TODAY = '2026-11-14'

function green(id: string, summary = ''): RuleResult {
  return {
    id,
    name: RULE_NAMES[id],
    level: 'green',
    title: '',
    summary,
    action: '',
    evidence: [],
    unknown_reason: null,
  }
}

function requestMessage(address: string, items: string[]): string {
  return [
    `안녕하세요. ${address} 임대차 계약 건으로 연락드립니다.`,
    '계약 전에 아래 내용을 확인하고 싶습니다.',
    '',
    ...items.map((item, i) => `${i + 1}. ${item}`),
    '',
    '확정일자 부여현황과 납세증명서는 계약할 때 임대인이 보여주도록 주택임대차보호법에 정해져 있다고 알고 있습니다.',
    '계약일 전에 받아볼 수 있을까요? 감사합니다.',
  ].join('\n')
}

const TERM_NO_LIEN =
  '임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다. 위반 시 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다.'
const TERM_JEONSE =
  '임차인이 전세보증금 반환보증에 가입할 수 없는 경우 계약은 무효로 하며, 임대인은 계약금을 즉시 반환한다.'
const TERM_ALWAYS =
  '임대인은 계약 체결 시 국세·지방세 납세증명서와 확정일자 부여현황을 제시한다.'
const TERM_TRUST =
  '임대인은 잔금일 전까지 수탁자(신탁회사)의 임대 동의서를 제출한다. 제출하지 못하면 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다.'

function checklist(jeonse: boolean): Report['checklist'] {
  return [
    { when: '계약 전', date: null, title: '등기부 다시 떼기' },
    { when: '계약 전', date: null, title: '확정일자 부여현황·납세증명서 받기' },
    { when: '계약 전', date: null, title: '임대인 신분증과 등기부 소유자 대조' },
    { when: '계약일', date: '2026-11-14', title: '특약 넣기' },
    { when: '계약일', date: '2026-11-14', title: '계약금은 소유자 명의 계좌로 보내기' },
    { when: '잔금일', date: '2026-12-01', title: '잔금 보내기 전 등기부 다시 떼기 (새 근저당이 없는지)' },
    { when: '입주일', date: '2026-12-01', title: '전입신고 + 확정일자 받기 (당일)' },
    ...(jeonse ? [{ when: '입주 후', date: null, title: '전세보증금 반환보증 가입' }] : []),
    { when: '입주 후', date: null, title: '계약서 원본 보관' },
  ]
}


/** 계약서 수정 요청서 문안. 비어 있는 부분은 빼고 번호를 다시 매긴다. */
export function amendmentText(a: Omit<Amendment, 'text'>, address: string, todayText: string): string {
  const parts: string[] = []
  let n = 0
  if (a.fixes.length) {
    n += 1
    parts.push(`${n}. 계약서에서 고칠 곳`, ...a.fixes.map((f) => `- ${f.item}: ${f.current ?? '없음'} → ${f.proposed} (${f.reason})`), '')
  }
  if (a.terms.length) {
    n += 1
    parts.push(`${n}. 넣어 주실 특약`, ...a.terms.map((t, i) => `${i + 1}) ${t}`), '')
  }
  if (a.documents.length) {
    n += 1
    parts.push(`${n}. 계약 전에 받아야 할 서류`, ...a.documents.map((d, i) => `${i + 1}) ${d}`), '')
  }
  return [
    a.title,
    '',
    `대상: ${address}`,
    `작성일: ${todayText}`,
    '',
    ...parts,
    '위 내용을 반영해 주시면 계약을 진행하고 싶습니다. 감사합니다.',
    '',
    '이 요청서는 서류를 기준으로 만든 참고 자료이며 법률 자문이 아닙니다.',
  ].join('\n')
}

function amendment(
  title: string,
  fixes: AmendmentFix[],
  terms: string[],
  documents: string[],
  address: string,
): Amendment {
  const base = { title, fixes, terms, documents }
  return { ...base, text: amendmentText(base, address, '2026년 11월 14일') }
}

function row(
  item: string,
  rule_id: string,
  contract: string | null,
  registry: string | null,
  level: ComparisonRow['level'],
  note: string,
): ComparisonRow {
  return { item, rule_id, contract, registry, level, note }
}

const USE_LINES_3F = [
  '철근콘크리트구조 (철근)콘크리트지붕 4층 다세대주택',
  '1층 다세대주택 98.12㎡',
  '2층 다세대주택 98.12㎡',
  '3층 다세대주택 98.12㎡',
  '4층 다세대주택 98.12㎡',
]

// ---------------------------------------------------------------------------
// 시나리오 C: 위험 신호가 있는 집 (신탁등기 + 임대인과 소유자가 다름)
// ---------------------------------------------------------------------------

const C_TRUST_TEXT =
  '3 소유권이전 2026년8월26일 제98232호 2026년8월26일 신탁 수탁자 ○○부동산신탁주식회사 110111-******* 서울특별시 강남구 테헤란로 ○○ 신탁 신탁원부 제2026-1234호'
const C_ADDRESS = '경기도 용인시 수지구 죽전동 123-4 ○○빌라 302호'

export const REQUEST_C: CheckRequest = {
  registry: {
    is_registry: true,
    registry_type: '집합건물',
    viewed_at: '2026-11-14T09:12:00+09:00',
    address_jibun: '경기도 용인시 수지구 죽전동 123-4',
    address_road: '경기도 용인시 수지구 죽전로 12',
    building_name: '○○빌라',
    unit: { dong: null, ho: '302', floor: '3층', area_m2: 29.75 },
    building_use_lines: USE_LINES_3F,
    gapgu: [
      {
        rank: '1',
        purpose: '소유권보존',
        received_at: '2019-03-11',
        cause: null,
        holders: ['박○○'],
        amount: null,
        is_cancelled: false,
        page: 2,
        source_text: '1 소유권보존 2019년3월11일 제31207호 소유자 박○○ 650101-******* 경기도 용인시 수지구 ○○로 ○○',
      },
      {
        rank: '2',
        purpose: '소유권이전',
        received_at: '2026-08-26',
        cause: '매매',
        holders: ['이○○'],
        amount: null,
        is_cancelled: false,
        page: 2,
        source_text:
          '2 소유권이전 2026년8월26일 제98231호 2026년7월30일 매매 소유자 이○○ 850505-******* 경기도 성남시 분당구 ○○로 ○○ 거래가액 금185,000,000원',
      },
      {
        rank: '3',
        purpose: '소유권이전',
        received_at: '2026-08-26',
        cause: '신탁',
        holders: ['○○부동산신탁(주)'],
        amount: null,
        is_cancelled: false,
        page: 2,
        source_text: C_TRUST_TEXT,
      },
    ],
    eulgu: [],
    unreadable: [],
  },
  contract: {
    is_contract: true,
    landlord_names: ['이○○'],
    agent_name: null,
    address: C_ADDRESS,
    unit: { dong: null, ho: '302' },
    lease_type: '전세',
    deposit: 180000000,
    monthly_rent: null,
    contract_date: '2026-11-14',
    balance_date: '2026-12-01',
    move_in_date: '2026-12-01',
    lease_end: '2028-11-30',
    special_terms: [],
    sources: {
      landlord: '임대인 성명 이○○',
      address: `소재지 ${C_ADDRESS}`,
      deposit: '보증금 금 일억팔천만원정 (₩180,000,000)',
      special_terms: null,
    },
  },
  manual: {
    deposit: null,
    monthly_rent: null,
    contract_date: null,
    landlord_name: null,
    prior_deposits: null,
    market_price: null,
  },
  building: {
    main_use: '공동주택(다세대주택)',
    unit_use: '다세대주택',
    is_violating: false,
    source: 'api',
    source_text: null,
  },
  market: { price: 200000000, method: 'same_building', deals: 3, period: '2025-12 ~ 2026-11' },
  today: TODAY,
  mode: 'demo',
}

export const REPORT_C: Report = {
  mode: 'demo',
  generated_at: GENERATED_AT,
  today: TODAY,
  overall: {
    level: 'red',
    title: '계약 보류 권장',
    message:
      '보증금을 잃을 수 있는 위험 신호가 3개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요.',
    unknown_note: null,
  },
  counts: { red: 3, yellow: 2, unknown: 0, green: 8 },
  results: [
    {
      id: 'R1',
      name: RULE_NAMES.R1,
      level: 'red',
      title: '계약하는 사람과 집주인이 달라요',
      summary: '등기부상 소유자는 ○○부동산신탁(주)인데, 계약서의 임대인은 이○○이에요.',
      action:
        '대리 계약이라면 위임장과 인감증명서를 확인하고 소유자와 직접 통화하세요. 보증금은 소유자 명의 계좌로만 보내세요.',
      evidence: [
        { doc: 'registry', page: 2, text: C_TRUST_TEXT },
        { doc: 'contract', page: 1, text: '임대인 성명 이○○' },
      ],
      unknown_reason: null,
    },
    {
      id: 'R2',
      name: RULE_NAMES.R2,
      level: 'red',
      title: '집이 신탁회사 소유예요',
      summary:
        '등기부상 소유권이 ○○부동산신탁(주)에게 넘어가 있어요. 신탁회사 동의 없이 맺은 계약은 보호받기 어려워요.',
      action: '신탁원부와 신탁회사의 임대 동의서를 요구하세요. 받기 전에는 계약을 미루세요.',
      evidence: [{ doc: 'registry', page: 2, text: C_TRUST_TEXT }],
      unknown_reason: null,
    },
    green('R3'),
    green('R4'),
    {
      id: 'R5',
      name: RULE_NAMES.R5,
      level: 'red',
      title: '보증금이 집값에 비해 위험한 수준이에요',
      summary:
        '선순위 0원 + 내 보증금 1억 8,000만 원 = 시세(2억 원, 같은 건물 매매 거래)의 90%예요. 경매로 넘어가면 보증금을 다 돌려받지 못할 수 있어요.',
      action: '보증금을 낮추거나, 전세보증금 반환보증에 가입할 수 있는지 먼저 확인하세요.',
      evidence: [
        { doc: 'contract', page: 1, text: '보증금 금 일억팔천만원정 (₩180,000,000)' },
        {
          doc: 'market',
          page: null,
          text: '같은 건물 매매 거래 3건의 중앙값 2억 원 (2025-12 ~ 2026-11)',
        },
      ],
      unknown_reason: null,
    },
    green('R6'),
    green('R7'),
    {
      id: 'R8',
      name: RULE_NAMES.R8,
      level: 'yellow',
      title: '최근에 집주인이 바뀌었어요',
      summary:
        '2026년 8월 26일에 소유권이 신탁으로 바뀌었어요 (기준일 80일 전). 매매와 전세 계약을 동시에 진행하는 수법에서 자주 보이는 패턴이에요.',
      action:
        '새 집주인이 이 집을 산 경위와 가격을 확인하세요. 내 보증금으로 집값을 치르는 구조라면 피하세요.',
      evidence: [{ doc: 'registry', page: 2, text: C_TRUST_TEXT }],
      unknown_reason: null,
    },
    green('R9'),
    green('R10'),
    green('R11'),
    {
      id: 'R12',
      name: RULE_NAMES.R12,
      level: 'yellow',
      title: '보증금을 지키는 특약이 없어요',
      summary: '잔금 전후에 집주인이 새로 대출을 받지 못하게 막는 조항이 계약서에 없어요.',
      action: '아래 추천 특약을 계약서에 넣어 달라고 요청하세요.',
      evidence: [{ doc: 'contract', page: null, text: '특약 없음' }],
      unknown_reason: null,
    },
    green('R13'),
  ],
  comparison: [
    row('임대인', 'R1', '이○○', '○○부동산신탁(주)', 'red', '불일치'),
    row('소재지·호수', 'R11', C_ADDRESS, '경기도 용인시 수지구 죽전동 123-4 ○○빌라 302호', 'green', '일치'),
    row('보증금', 'R5', '1억 8,000만 원', '시세 2억 원', 'red', '90%'),
    row('계약일', 'R8', '2026년 11월 14일', '소유권 이전 2026년 8월 26일', 'yellow', '80일 전 소유자 변경'),
    row('특약', 'R12', '보호 특약 없음', null, 'yellow', '특약 없음'),
  ],
  amendment: amendment(
    '계약서 수정 요청서',
    [
      {
        item: '임대인',
        current: '이○○',
        proposed: '소유자 ○○부동산신탁(주) 명의 (대리 계약이면 신탁회사의 임대 동의서·위임장·인감증명서 첨부)',
        reason: '등기부상 소유자와 계약서의 임대인이 달라요',
      },
    ],
    [TERM_NO_LIEN, TERM_JEONSE, TERM_ALWAYS, TERM_TRUST],
    ['확정일자 부여현황', '국세·지방세 납세증명서', '신탁원부', '신탁회사(수탁자)의 임대 동의서', '위임장', '인감증명서'],
    C_ADDRESS,
  ),
  request_message: requestMessage(C_ADDRESS, [
    '확정일자 부여현황',
    '국세·지방세 납세증명서',
    '신탁원부',
    '신탁회사(수탁자)의 임대 동의서',
    '위임장',
    '인감증명서',
  ]),
  special_terms: [TERM_NO_LIEN, TERM_JEONSE, TERM_ALWAYS, TERM_TRUST],
  checklist: checklist(true),
  disclaimer: DISCLAIMER,
}

// ---------------------------------------------------------------------------
// 시나리오 B: 확인할 게 있는 집 (다가구 + 근저당 + 최근 소유권 이전 + 5일 전 등기부)
// ---------------------------------------------------------------------------

const B_MORTGAGE_TEXT =
  '1 근저당권설정 2026년9월15일 제87654호 2026년9월15일 설정계약 채권최고액 금120,000,000원 채무자 정○○ 근저당권자 주식회사○○은행 110111-******* 서울특별시 중구 ○○로 ○○'
const B_TRANSFER_TEXT =
  '2 소유권이전 2026년9월15일 제87653호 2026년8월20일 매매 소유자 정○○ 900303-******* 경기도 용인시 수지구 ○○로 ○○ 거래가액 금650,000,000원'
const B_ADDRESS = '경기도 용인시 수지구 죽전동 78-9 3층 301호'

export const REQUEST_B: CheckRequest = {
  registry: {
    is_registry: true,
    registry_type: '건물',
    viewed_at: '2026-11-09T14:05:00+09:00',
    address_jibun: '경기도 용인시 수지구 죽전동 78-9',
    address_road: '경기도 용인시 수지구 죽전로56번길 7',
    building_name: null,
    unit: { dong: null, ho: null, floor: null, area_m2: null },
    building_use_lines: [
      '철근콘크리트구조 철근콘크리트지붕 4층 다가구주택',
      '1층 다가구주택 120.50㎡',
      '2층 다가구주택 120.50㎡',
      '3층 다가구주택 120.50㎡',
      '4층 다가구주택 98.30㎡',
    ],
    gapgu: [
      {
        rank: '1',
        purpose: '소유권보존',
        received_at: '2015-06-02',
        cause: null,
        holders: ['한○○'],
        amount: null,
        is_cancelled: false,
        page: 2,
        source_text: '1 소유권보존 2015년6월2일 제45120호 소유자 한○○ 600707-******* 경기도 용인시 수지구 ○○로 ○○',
      },
      {
        rank: '2',
        purpose: '소유권이전',
        received_at: '2026-09-15',
        cause: '매매',
        holders: ['정○○'],
        amount: null,
        is_cancelled: false,
        page: 2,
        source_text: B_TRANSFER_TEXT,
      },
    ],
    eulgu: [
      {
        rank: '1',
        purpose: '근저당권설정',
        received_at: '2026-09-15',
        cause: '설정계약',
        holders: ['주식회사○○은행'],
        amount: 120000000,
        is_cancelled: false,
        page: 3,
        source_text: B_MORTGAGE_TEXT,
      },
    ],
    unreadable: [],
  },
  contract: {
    is_contract: true,
    landlord_names: ['정○○'],
    agent_name: null,
    address: B_ADDRESS,
    unit: { dong: null, ho: '301' },
    lease_type: '월세',
    deposit: 30000000,
    monthly_rent: 400000,
    contract_date: '2026-11-14',
    balance_date: '2026-12-01',
    move_in_date: '2026-12-01',
    lease_end: '2027-11-30',
    special_terms: [],
    sources: {
      landlord: '임대인 성명 정○○',
      address: `소재지 ${B_ADDRESS}`,
      deposit: '보증금 금 삼천만원정 (₩30,000,000) 차임 금 사십만원정 (₩400,000)',
      special_terms: null,
    },
  },
  manual: {
    deposit: null,
    monthly_rent: null,
    contract_date: null,
    landlord_name: null,
    prior_deposits: null,
    market_price: null,
  },
  building: {
    main_use: '단독주택(다가구주택)',
    unit_use: null,
    is_violating: false,
    source: 'api',
    source_text: null,
  },
  market: null,
  today: TODAY,
  mode: 'demo',
}

export const REPORT_B: Report = {
  mode: 'demo',
  generated_at: GENERATED_AT,
  today: TODAY,
  overall: {
    level: 'yellow',
    title: '추가 확인 필요',
    message: '계약 전에 확인할 것이 5개 있어요.',
    unknown_note: '확인하지 못한 항목 1개',
  },
  counts: { red: 0, yellow: 5, unknown: 1, green: 7 },
  results: [
    green('R1'),
    green('R2'),
    green('R3'),
    green('R4'),
    {
      id: 'R5',
      name: RULE_NAMES.R5,
      level: 'unknown',
      title: '',
      summary: '',
      action: '',
      evidence: [],
      unknown_reason: '다가구는 시세를 추정하기 어려워요.',
    },
    {
      id: 'R6',
      name: RULE_NAMES.R6,
      level: 'yellow',
      title: '집에 먼저 잡힌 빚(근저당 등)이 있어요',
      summary: '채권최고액 등 1억 2,000만 원이 내 보증금보다 먼저 돌려받아요.',
      action:
        '잔금일에 대출을 갚고 근저당을 말소하는 조건을 특약에 넣거나, 집값에서 이 금액을 빼고도 보증금이 충분히 남는지 확인하세요.',
      evidence: [{ doc: 'registry', page: 3, text: B_MORTGAGE_TEXT }],
      unknown_reason: null,
    },
    {
      id: 'R7',
      name: RULE_NAMES.R7,
      level: 'yellow',
      title: '다른 세입자 보증금을 등기부로는 알 수 없어요',
      summary:
        '이 건물은 한 사람이 통째로 소유해서, 먼저 들어온 세입자들의 보증금이 등기부에 나오지 않아요.',
      action: '집주인에게 확정일자 부여현황을 요구해 먼저 들어온 보증금 합계를 확인하세요.',
      evidence: [
        { doc: 'registry', page: 1, text: '철근콘크리트구조 철근콘크리트지붕 4층 다가구주택' },
      ],
      unknown_reason: null,
    },
    {
      id: 'R8',
      name: RULE_NAMES.R8,
      level: 'yellow',
      title: '최근에 집주인이 바뀌었어요',
      summary:
        '2026년 9월 15일에 소유권이 매매로 바뀌었어요 (기준일 60일 전). 매매와 전세 계약을 동시에 진행하는 수법에서 자주 보이는 패턴이에요.',
      action:
        '새 집주인이 이 집을 산 경위와 가격을 확인하세요. 내 보증금으로 집값을 치르는 구조라면 피하세요.',
      evidence: [{ doc: 'registry', page: 2, text: B_TRANSFER_TEXT }],
      unknown_reason: null,
    },
    green('R9'),
    green('R10'),
    green('R11'),
    {
      id: 'R12',
      name: RULE_NAMES.R12,
      level: 'yellow',
      title: '보증금을 지키는 특약이 없어요',
      summary: '잔금 전후에 집주인이 새로 대출을 받지 못하게 막는 조항이 계약서에 없어요.',
      action: '아래 추천 특약을 계약서에 넣어 달라고 요청하세요.',
      evidence: [{ doc: 'contract', page: null, text: '특약 없음' }],
      unknown_reason: null,
    },
    {
      id: 'R13',
      name: RULE_NAMES.R13,
      level: 'yellow',
      title: '5일 전에 뗀 등기부예요',
      summary: '그 사이에 근저당 등이 새로 생겼을 수 있어요.',
      action: '계약 당일과 잔금 당일에 등기부를 다시 떼어 보세요.',
      evidence: [{ doc: 'registry', page: 1, text: '열람일시 : 2026년11월09일 14시05분' }],
      unknown_reason: null,
    },
  ],
  comparison: [
    row('임대인', 'R1', '정○○', '정○○', 'green', '일치'),
    row('소재지·호수', 'R11', B_ADDRESS, '경기도 용인시 수지구 죽전동 78-9', 'green', '일치'),
    row('보증금', 'R5', '3,000만 원', '시세 없음', 'unknown', '확인 못 함'),
    row('계약일', 'R8', '2026년 11월 14일', '소유권 이전 2026년 9월 15일', 'yellow', '60일 전 소유자 변경'),
    row('특약', 'R12', '보호 특약 없음', null, 'yellow', '특약 없음'),
  ],
  amendment: amendment(
    '계약서 수정 요청서',
    [],
    [
      TERM_NO_LIEN,
      '임대인은 잔금일까지 등기부상 근저당권(채권최고액 1억 2,000만 원)을 말소한다.',
      TERM_ALWAYS,
    ],
    ['확정일자 부여현황', '국세·지방세 납세증명서', '근저당 대출을 잔금일에 갚고 말소할 계획인지'],
    B_ADDRESS,
  ),
  request_message: requestMessage(B_ADDRESS, [
    '확정일자 부여현황',
    '국세·지방세 납세증명서',
    '근저당 대출을 잔금일에 갚고 말소할 계획인지',
  ]),
  special_terms: [
    TERM_NO_LIEN,
    '임대인은 잔금일까지 등기부상 근저당권(채권최고액 1억 2,000만 원)을 말소한다.',
    TERM_ALWAYS,
  ],
  checklist: checklist(false),
  disclaimer: DISCLAIMER,
}

// ---------------------------------------------------------------------------
// 시나리오 A: 위험 신호 없는 집
// ---------------------------------------------------------------------------

const A_ADDRESS = '경기도 용인시 수지구 죽전동 45-6 △△빌라 302호'

export const REQUEST_A: CheckRequest = {
  registry: {
    is_registry: true,
    registry_type: '집합건물',
    viewed_at: '2026-11-14T08:40:00+09:00',
    address_jibun: '경기도 용인시 수지구 죽전동 45-6',
    address_road: '경기도 용인시 수지구 포은대로 34',
    building_name: '△△빌라',
    unit: { dong: null, ho: '302', floor: '3층', area_m2: 24.3 },
    building_use_lines: USE_LINES_3F,
    gapgu: [
      {
        rank: '1',
        purpose: '소유권보존',
        received_at: '2016-05-02',
        cause: null,
        holders: ['최○○'],
        amount: null,
        is_cancelled: false,
        page: 2,
        source_text: '1 소유권보존 2016년5월2일 제52011호 소유자 최○○ 550202-******* 경기도 용인시 수지구 ○○로 ○○',
      },
      {
        rank: '2',
        purpose: '소유권이전',
        received_at: '2019-04-17',
        cause: '매매',
        holders: ['김○○'],
        amount: null,
        is_cancelled: false,
        page: 2,
        source_text:
          '2 소유권이전 2019년4월17일 제40877호 2019년3월25일 매매 소유자 김○○ 700808-******* 경기도 용인시 수지구 ○○로 ○○ 거래가액 금190,000,000원',
      },
    ],
    eulgu: [],
    unreadable: [],
  },
  contract: {
    is_contract: true,
    landlord_names: ['김○○'],
    agent_name: null,
    address: A_ADDRESS,
    unit: { dong: null, ho: '302' },
    lease_type: '월세',
    deposit: 10000000,
    monthly_rent: 450000,
    contract_date: '2026-11-14',
    balance_date: '2026-12-01',
    move_in_date: '2026-12-01',
    lease_end: '2027-11-30',
    special_terms: [TERM_NO_LIEN],
    sources: {
      landlord: '임대인 성명 김○○',
      address: `소재지 ${A_ADDRESS}`,
      deposit: '보증금 금 일천만원정 (₩10,000,000) 차임 금 사십오만원정 (₩450,000)',
      special_terms: `1. ${TERM_NO_LIEN}`,
    },
  },
  manual: {
    deposit: null,
    monthly_rent: null,
    contract_date: null,
    landlord_name: null,
    prior_deposits: null,
    market_price: null,
  },
  building: {
    main_use: '공동주택(다세대주택)',
    unit_use: '다세대주택',
    is_violating: false,
    source: 'api',
    source_text: null,
  },
  market: { price: 200000000, method: 'same_building', deals: 4, period: '2025-12 ~ 2026-11' },
  today: TODAY,
  mode: 'demo',
}

const A_COMPARISON: ComparisonRow[] = [
  row('임대인', 'R1', '김○○', '김○○', 'green', '일치'),
  row('소재지·호수', 'R11', A_ADDRESS, '경기도 용인시 수지구 죽전동 45-6 △△빌라 302호', 'green', '일치'),
  row('보증금', 'R5', '1,000만 원', '시세 2억 원', 'green', '5%'),
  row('계약일', 'R8', '2026년 11월 14일', '소유권 이전 2019년 4월 17일', 'green', '변경 없음'),
  row('특약', 'R12', '보호 특약 있음', null, 'green', '특약 있음'),
]

export const REPORT_A: Report = {
  mode: 'demo',
  generated_at: GENERATED_AT,
  today: TODAY,
  overall: {
    level: 'green',
    title: '큰 위험 신호 없음',
    message:
      '확인한 범위에서는 큰 위험 신호를 찾지 못했어요. 안전을 보장하는 것은 아니니 아래 할 일은 꼭 챙기세요.',
    unknown_note: null,
  },
  counts: { red: 0, yellow: 0, unknown: 0, green: 13 },
  results: [
    green('R1'),
    green('R2'),
    green('R3'),
    green('R4'),
    green(
      'R5',
      '선순위 0원 + 내 보증금 1,000만 원 = 시세(2억 원, 같은 건물 매매 거래)의 5%예요.',
    ),
    green('R6'),
    green('R7'),
    green('R8'),
    green('R9'),
    green('R10'),
    green('R11'),
    green('R12'),
    green('R13'),
  ],
  comparison: A_COMPARISON,
  amendment: amendment('계약서 수정 요청서', [], [TERM_ALWAYS], ['확정일자 부여현황', '국세·지방세 납세증명서'], A_ADDRESS),
  request_message: requestMessage(A_ADDRESS, ['확정일자 부여현황', '국세·지방세 납세증명서']),
  special_terms: [TERM_ALWAYS],
  checklist: checklist(false),
  disclaimer: DISCLAIMER,
}

/**
 * 시나리오 A에서 임대인 이름을 지우고 검사했을 때 (가짜 API 전용).
 * 핵심 규칙 R1을 확인하지 못해 종합 판정이 "확인이 끝나지 않았어요"가 된다.
 */
export const REPORT_A_INCOMPLETE: Report = {
  ...REPORT_A,
  overall: {
    level: 'yellow',
    title: '확인 미완료',
    message:
      '위험 신호는 찾지 못했지만, 꼭 확인해야 할 항목 1개를 확인하지 못했어요. 빠진 내용을 채운 뒤 다시 검사하세요.',
    unknown_note: '확인하지 못한 항목 1개',
  },
  counts: { red: 0, yellow: 0, unknown: 1, green: 12 },
  comparison: A_COMPARISON.map((r) =>
    r.rule_id === 'R1' ? { ...r, contract: null, level: 'unknown', note: '확인 못 함' } : r,
  ),
  results: REPORT_A.results.map(
    (r): RuleResult =>
      r.id === 'R1' ? { ...r, level: 'unknown', unknown_reason: '임대인 이름을 확인하지 못했어요.' } : r,
  ),
}

// ---------------------------------------------------------------------------
// 계약 후 재확인 예시: A 집, 잔금 이틀 전(오늘 2026-11-29) 뗀 등기부에 을구 근저당이 새로 생긴 경우
// ---------------------------------------------------------------------------

export const REQUEST_RECHECK_A: RecheckRequest = {
  registry: {
    ...REQUEST_A.registry,
    viewed_at: '2026-11-29T09:05:00+09:00',
    eulgu: [
      {
        rank: '1',
        purpose: '근저당권설정',
        received_at: '2026-11-27',
        cause: '설정계약',
        holders: ['주식회사○○은행'],
        amount: 120000000,
        is_cancelled: false,
        page: 3,
        source_text:
          '1 근저당권설정 2026년11월27일 제112233호 2026년11월27일 설정계약 채권최고액 금120,000,000원 채무자 김○○ 근저당권자 주식회사○○은행 110111-******* 서울특별시 중구 ○○로 ○○',
      },
    ],
  },
  contract: REQUEST_A.contract!,
  baseline_viewed_at: null,
  today: '2026-11-29',
  mode: 'demo',
}
