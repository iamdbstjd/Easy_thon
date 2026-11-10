// 화면에 문서 원문을 보여줄 때 주민등록번호 모양을 가린다.
// 화면 표시에만 쓴다. /api/check로 돌려보내는 값은 바꾸지 않는다.

// 앞 6자리와 뒤 7자리: 숫자 또는 가림 문자(* ＊ x X ○ ●)
const ID_CHARS = '0-9*＊xX○●'
// 하이픈 앞뒤 공백 허용. 하이픈 비슷한 문자도 같이 본다.
const ID_PATTERN = new RegExp(
  `(?<![${ID_CHARS}])[${ID_CHARS}]{6}\\s*[-‐‑–—－−]\\s*[${ID_CHARS}]{7}(?![${ID_CHARS}])`,
  'g',
)

// 화면에서 줄이 바뀌지 않도록 하이픈은 줄바꿈 없는 하이픈(U+2011)으로 쓴다.
export const MASKED_ID = '******\u2011*******'

/** "소유자 정○○ 620830-1234567" → "소유자 정○○ ******‑*******" */
export function maskIds(text: string): string {
  return text.replace(ID_PATTERN, MASKED_ID)
}
