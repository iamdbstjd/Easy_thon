// 화면에 고정으로 들어가는 문구

/**
 * 등기부만으로는 알 수 없는 것.
 * 화면 말투(해요체)에 맞춘 문구다.
 */
export const OFF_REGISTRY_ROWS: { info: string; why: string; how: string }[] = [
  {
    info: '선순위 임차인 보증금 (특히 다가구)',
    why: '경매 때 먼저 들어온 세입자가 먼저 돈을 받아 가요.',
    how: '임대인은 계약할 때 확정일자 부여현황을 보여줄 의무가 있어요 (주택임대차보호법 제3조의7). 임대인 동의를 받아 주민센터에서 열람할 수도 있어요.',
  },
  {
    info: '임대인 세금 체납',
    why: '체납 세금이 보증금보다 먼저 가져갈 수 있어요.',
    how: '계약할 때 납세증명서를 보여줄 의무가 있어요 (같은 조). 계약 후에는 보증금 1천만 원 초과 계약이면 임대차 시작일 전까지 임대인 동의 없이 세무서에서 미납국세를 열람할 수 있다고 안내돼요.',
  },
  {
    info: '임대인의 보증사고 이력',
    why: '다른 집에서 보증금을 돌려주지 않은 임대인일 수 있어요.',
    how: 'HUG 안심전세앱 등에서 확인하세요.',
  },
  {
    info: '계약 후 잔금 전 변동',
    why: '잔금 날 근저당이 새로 설정될 수 있어요.',
    how: '잔금 당일 등기부를 다시 떼어 보세요.',
  },
  {
    info: '대항력·우선변제권',
    why: '대항력(집주인이 바뀌어도 계속 살면서 보증금을 주장할 수 있는 힘)은 입주 + 전입신고 다음 날 0시부터 생겨요. 같은 날 설정된 근저당이 앞서요.',
    how: '입주 당일 전입신고 + 확정일자를 받고, 보증보험에 가입하세요.',
  },
]

/** S1 하단 고지 한 줄 */
export const START_NOTICE =
  '법률 자문이 아니에요. 결과는 참고 정보이며 보증금의 안전을 보장하지 않아요.'

/** 추천 특약 아래 안내 */
export const SPECIAL_TERMS_NOTE = '실제로 쓰기 전에 공인중개사나 대한법률구조공단에 확인하세요.'

/** S5 하단 외부 연결. 전화번호는 휴대폰에서 바로 걸 수 있게 tel: 링크로 둔다. */
export const HELP_LINKS: {
  name: string
  detail: string
  tel: string | null
  href: string
  label: string
}[] = [
  {
    name: '대한법률구조공단',
    detail: '법률 상담',
    tel: '132',
    href: 'https://www.klac.or.kr',
    label: 'www.klac.or.kr',
  },
  {
    name: '주택도시보증공사 HUG',
    detail: '전세보증금 반환보증',
    tel: null,
    href: 'https://www.khug.or.kr',
    label: 'www.khug.or.kr',
  },
]

export const IROS_URL = 'https://www.iros.go.kr'
/** 국토교통부 실거래가 공개시스템 */
export const RT_URL = 'https://rt.molit.go.kr'
/** 세움터 (건축물대장 열람·발급) */
export const EAIS_URL = 'https://www.eais.go.kr'

/** 검토서 위쪽 '바로가기'. 지도는 주소로 검색한다 (누르면 그 지도 서비스로 주소가 넘어간다) */
export function quickLinks(address: string | null): { label: string; href: string }[] {
  const links: { label: string; href: string }[] = []
  if (address) {
    const q = encodeURIComponent(address)
    links.push({ label: '네이버 지도', href: `https://map.naver.com/p/search/${q}` })
    links.push({ label: '카카오맵', href: `https://map.kakao.com/?q=${q}` })
  }
  links.push({ label: '실거래가 공개시스템', href: RT_URL })
  links.push({ label: '세움터(건축물대장)', href: EAIS_URL })
  links.push({ label: '인터넷등기소', href: IROS_URL })
  return links
}
