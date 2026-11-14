// 어려운 말 풀이: 검토서에 나오는 등기·계약 용어를 한두 문장의 쉬운 말로 푼다.
// 글 속에서는 처음 나온 곳에 점선 밑줄을 치고 누르면 풀이가 나온다 (components/Glossed.tsx).
// PDF·인쇄에서는 누를 수 없어서, 검토서 끝의 '어려운 말 풀이' 절에 그 검토서에 나온 말만 모은다.
// 계약서 수정 요청서는 공인중개사·임대인에게 보여 주는 문서라 밑줄 없이 공식 용어 그대로 둔다.

export interface GlossaryTerm {
  /** 풀이 제목 */
  term: string
  /** 글에서 찾을 표기 */
  match: string[]
  text: string
}

export const GLOSSARY: GlossaryTerm[] = [
  {
    term: '근저당',
    match: ['근저당권', '근저당'],
    text: '집주인이 이 집을 담보로 돈을 빌렸다는 표시예요. 집이 경매로 넘어가면 이 빚을 내 보증금보다 먼저 갚을 수 있어요.',
  },
  {
    term: '채권최고액',
    match: ['채권최고액'],
    text: '근저당으로 은행 등이 이 집에서 최대한 받아 갈 수 있는 금액이에요. 보통 빌린 돈의 120~130%로 잡아요.',
  },
  {
    term: '신탁등기',
    match: ['신탁등기'],
    text: '집주인이 집의 소유권을 신탁회사에 넘겨 둔 상태예요. 등기부상 집주인은 신탁회사라서, 신탁회사 동의 없이 맺은 계약은 보호받기 어려워요.',
  },
  {
    term: '신탁원부',
    match: ['신탁원부'],
    text: '신탁 계약의 조건(누가 집을 빌려줄 수 있는지 등)이 적힌 서류예요. 등기소에서 뗄 수 있어요.',
  },
  { term: '수탁자', match: ['수탁자'], text: '신탁에서 집의 소유권을 넘겨받은 쪽이에요. 보통 신탁회사예요.' },
  { term: '가압류', match: ['가압류'], text: '돈을 받을 사람이 재판 전에 집을 팔지 못하게 미리 묶어 둔 거예요.' },
  {
    term: '압류',
    match: ['압류'],
    text: '세금이나 빚 때문에 나라나 돈 받을 사람이 집을 묶어 둔 거예요. 경매로 이어질 수 있어요.',
  },
  {
    term: '경매',
    match: ['경매'],
    text: '빚을 갚지 못한 집을 법원이 팔아 빚을 갚는 절차예요. 세입자는 순서가 늦으면 보증금을 다 못 받을 수 있어요.',
  },
  {
    term: '임차권등기',
    match: ['임차권등기명령', '임차권등기'],
    text: '전 세입자가 보증금을 돌려받지 못한 채 이사 나가면서 등기부에 남긴 기록이에요. 이 집에서 보증금이 제때 돌아오지 않은 적이 있다는 뜻이에요.',
  },
  {
    term: '전세권',
    match: ['전세권'],
    text: '전세 보증금을 지키려고 등기부에 올린 권리예요. 나보다 먼저 있으면 경매 때 그 돈을 먼저 줘요.',
  },
  {
    term: '선순위',
    match: ['선순위'],
    text: '나보다 먼저 권리를 잡은 사람(은행, 먼저 들어온 세입자 등)이에요. 경매 때 이 사람들이 먼저 돈을 받아 가요.',
  },
  {
    term: '대항력',
    match: ['대항력'],
    text: '집주인이 바뀌어도 계속 살면서 보증금을 돌려 달라고 할 수 있는 힘이에요. 입주하고 전입신고를 마친 다음 날 0시부터 생겨요.',
  },
  {
    term: '우선변제권',
    match: ['우선변제권'],
    text: '집이 경매로 팔릴 때 내 순서에 맞춰 보증금을 돌려받을 수 있는 권리예요. 대항력에 확정일자까지 받아야 생겨요.',
  },
  {
    term: '확정일자 부여현황',
    match: ['확정일자 부여현황'],
    text: '이 집에서 확정일자를 받은 다른 세입자들의 날짜와 보증금이 적힌 서류예요. 나보다 먼저 받아 갈 보증금이 얼마인지 알 수 있어요.',
  },
  {
    term: '확정일자',
    match: ['확정일자'],
    text: '주민센터나 온라인에서 계약서에 받는 날짜 도장이에요. 경매 때 보증금을 순서대로 돌려받는 데 필요해요.',
  },
  {
    term: '전입신고',
    match: ['전입신고'],
    text: '이사한 뒤 주민센터에 새 주소를 알리는 신고예요. 대항력을 얻으려면 꼭 해야 해요.',
  },
  { term: '소유권 이전', match: ['소유권이전', '소유권 이전'], text: '집주인이 바뀌었다는 등기부 기록이에요.' },
  { term: '갑구', match: ['갑구'], text: '등기부에서 집주인과 압류·가압류처럼 소유권에 관한 일이 적힌 부분이에요.' },
  { term: '을구', match: ['을구'], text: '등기부에서 근저당·전세권처럼 소유권이 아닌 권리가 적힌 부분이에요.' },
  {
    term: '말소',
    match: ['말소'],
    text: '등기부의 그 기록이 지워져 효력이 끝났다는 뜻이에요. 예를 들어 빚을 다 갚으면 근저당이 말소돼요.',
  },
  {
    term: '다가구',
    match: ['다가구주택', '다가구'],
    text: '건물 전체가 집주인 한 사람 것이고 여러 세입자가 방을 나눠 빌려 사는 집이에요. 다른 세입자의 보증금이 나보다 먼저일 수 있어요.',
  },
  { term: '집합건물', match: ['집합건물'], text: '아파트·빌라처럼 호실마다 등기가 따로 있는 건물이에요.' },
  {
    term: '위반건축물',
    match: ['위반건축물'],
    text: '허가 없이 늘리거나 고쳐서 건축물대장에 위반으로 표시된 건물이에요. 전세대출이나 보증보험이 거절될 수 있어요.',
  },
  {
    term: '근린생활시설',
    match: ['근린생활시설'],
    text: '가게·사무실 같은 용도로 허가된 공간이에요. 방처럼 꾸며도 주택이 아니라서 전세대출이나 보증보험이 거절될 수 있어요.',
  },
  { term: '전유부', match: ['전유부'], text: '건축물대장에서 호실 하나하나의 용도와 면적이 적힌 부분이에요.' },
  {
    term: '건축물대장',
    match: ['건축물대장'],
    text: '건물의 용도·면적·위반 여부가 적힌 나라 장부예요. 정부24나 세움터에서 뗄 수 있어요.',
  },
  {
    term: '반환보증',
    match: ['전세보증금 반환보증', '반환보증', '보증보험'],
    text: '집주인이 보증금을 돌려주지 못하면 HUG 같은 보증기관이 대신 돌려주는 보험이에요.',
  },
  {
    term: '위임장',
    match: ['위임장'],
    text: '집주인이 다른 사람에게 계약을 맡긴다고 적은 서류예요. 인감도장이 찍혀 있고 인감증명서가 함께 있어야 해요.',
  },
  { term: '인감증명서', match: ['인감증명서'], text: '도장이 본인 것이 맞다고 주민센터가 확인해 주는 서류예요.' },
  {
    term: '납세증명서',
    match: ['납세증명서'],
    text: '집주인에게 밀린 세금이 없다는 걸 보여 주는 서류예요. 밀린 세금은 보증금보다 먼저 가져갈 수 있어요.',
  },
  { term: '특약', match: ['특약'], text: '계약서에 따로 덧붙이는 약속이에요. 보증금을 지키는 조건을 여기에 넣어요.' },
  { term: '잔금', match: ['잔금'], text: '계약금을 낸 뒤 남은 보증금이에요. 보통 이사 들어가는 날 내요.' },
]

const BY_MATCH = new Map<string, GlossaryTerm>()
for (const item of GLOSSARY) for (const m of item.match) BY_MATCH.set(m, item)
// 긴 표기부터 맞춘다 ("가압류"가 "압류"보다, "확정일자 부여현황"이 "확정일자"보다 먼저)
const PATTERN = new RegExp(
  [...BY_MATCH.keys()]
    .sort((a, b) => b.length - a.length)
    .map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|'),
  'g',
)

export interface TextPart {
  text: string
  /** 풀이가 있는 말이면 그 풀이 */
  term?: GlossaryTerm
}

/** 글을 쪼개 어려운 말을 표시한다. 같은 말은 처음 나온 곳만 표시한다 */
export function splitTerms(text: string): TextPart[] {
  const parts: TextPart[] = []
  const seen = new Set<GlossaryTerm>()
  let last = 0
  for (const m of text.matchAll(PATTERN)) {
    const term = BY_MATCH.get(m[0])
    if (!term || seen.has(term)) continue
    seen.add(term)
    if (m.index > last) parts.push({ text: text.slice(last, m.index) })
    parts.push({ text: m[0], term })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last) })
  return parts
}

/** 여러 글에 나온 어려운 말 (풀이 목록 순서대로) */
export function termsIn(texts: (string | null | undefined)[]): GlossaryTerm[] {
  const found = new Set<GlossaryTerm>()
  for (const text of texts) {
    if (!text) continue
    for (const m of text.matchAll(PATTERN)) {
      const term = BY_MATCH.get(m[0])
      if (term) found.add(term)
    }
  }
  return GLOSSARY.filter((t) => found.has(t))
}
