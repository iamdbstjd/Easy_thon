// 화면에 문서 원문을 보여줄 때 주민등록번호와 전화번호 모양을 가린다 (서버 app/privacy.py와 같은 규칙).
// 화면 표시에만 쓴다. /api/check로 돌려보내는 값은 바꾸지 않는다.
//
// - 숫자는 전각(０-９)도 같은 숫자로 본다.
// - 하이픈(비슷한 글자 포함)이 있으면: 앞 6자리 - 뒤 7자리 (숫자나 가림 글자). 뒤 첫 글자 다음 띄어쓰기도 허용.
// - 하이픈이 없거나, 띄어쓰기(3칸까지)·줄바꿈 하나·점·빗금·물결·밑줄 같은 다른 구분 글자면:
//   앞 6자리가 생년월일(YYMMDD)이고 뒤 첫 글자가 1~8(또는 가림 글자)일 때만.
// - 전화번호(+82 국제 표기 포함)는 앞 번호(010, 02, +82-10 …)만 남기고 나머지 숫자를 "*"로. 구분 글자와 길이는 그대로.

// 숫자 (전각 포함)
const D = '[0-9０-９]'
// 공백은 서버(파이썬 re)의 \s와 같게 쓴다 (\x1c-\x1f·\x85 포함, U+FEFF 제외). 자바스크립트 \s와 다르다
const SPACE_CHARS = '\\t\\v\\f\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000'
const SPACE = `[\\n\\r${SPACE_CHARS}]`
// 줄바꿈이 아닌 공백
const HSPACE = `[${SPACE_CHARS}]`
// 가림 글자
const MASK_CHAR = '[*＊∗xX○◯〇●#＃■□◆◇･∙·]'
// 숫자와 가림 글자
const ID_CHAR = '[0-9０-９*＊∗xX○◯〇●#＃■□◆◇･∙·]'
// 하이픈과 비슷하게 생긴 글자 (사진 OCR·전각 입력·한글 'ㅡ'·반각 'ｰ')
const DASH = '[-‐‑‒–—―−－﹣⁃ㅡ─━ーｰ]'
// 생년월일 규칙과 함께일 때만 받는 구분 글자 (점·빗금·물결·밑줄·가운뎃점·'ㅣ')
const WEAK_SEP = '[./~_‧ㅣ．／～＿]'
const YYMMDD = '[0-9０-９]{2}(?:[0０][1-9１-９]|[1１][0-2０-２])(?:[0０][1-9１-９]|[12１２][0-9０-９]|[3３][01０１])'
const GAP = `(?:${HSPACE}{0,3}|${HSPACE}{0,3}(?:${WEAK_SEP}|\\r?\\n)${HSPACE}{0,3})`
const BACK7 = `${ID_CHAR}${HSPACE}?${ID_CHAR}{6}`
const WITH_DASH = `${ID_CHAR}{6}${SPACE}*${DASH}${SPACE}*${BACK7}`
const BIRTH_DATE = `${YYMMDD}${GAP}(?:[1-8１-８]|${MASK_CHAR})${HSPACE}?${ID_CHAR}{6}`
// 앞뒤가 숫자로 이어지면 주민등록번호가 아니다. 이름의 ○ 바로 뒤에 붙어 있어도 잡는다.
const RESIDENT_ID = new RegExp(`(?<!${D})(?:${WITH_DASH}|${BIRTH_DATE})(?!${D})`, 'gu')

const PHONE_DASH = '[-‐‑‒–—−－.ㅡ]'
const PHONE_SEP = `(?:${HSPACE}?${PHONE_DASH}${HSPACE}?|${HSPACE})`
const MOBILE = '[0０][1１][016789０１６７８９]'
const AREA = '[0０][2２]|[0０][3-6３-６][1-5１-５]|[0０][7７][0０]|[0０][5５][0０][2-8２-８]?|[0０][8８][0０]'
// 국가번호 다음에는 앞자리 0을 뺀다 (+82-10-…, +82-2-…)
const INTL = '[+＋][8８][2２]'
const INTL_CODE = '[1１][016789０１６７８９]|[2２]|[3-6３-６][1-5１-５]|[7７][0０]'
// 휴대전화·국제 표기는 구분 글자가 없어도 잡는다. 지역번호·인터넷전화는 구분 글자가 있을 때만 (다른 번호와 헷갈리지 않게).
const PHONE_NUMBER = new RegExp(
  `(?<!${D})(?<!${D}${PHONE_DASH})` +
    `(?:(?<intl>${INTL}${PHONE_SEP}?(?:${INTL_CODE}))${PHONE_SEP}?${D}{3,4}${PHONE_SEP}?${D}{4}` +
    `|(?<mobile>${MOBILE})${PHONE_SEP}?${D}{3,4}${PHONE_SEP}?${D}{4}` +
    `|\\(?(?<area>${AREA})(?:\\)${PHONE_SEP}?|${PHONE_SEP})${D}{3,4}${PHONE_SEP}${D}{4})` +
    `(?!${D})(?!${PHONE_DASH}${D})`,
  'gu',
)
const ANY_DIGIT = new RegExp(D, 'gu')

// 화면에서 줄이 바뀌지 않도록 하이픈은 줄바꿈 없는 하이픈(U+2011)으로 쓴다.
export const MASKED_ID = '******‑*******'

/** 주민등록번호 모양만 가린다 */
export function maskResidentIds(text: string): string {
  return text.replace(RESIDENT_ID, MASKED_ID)
}

/** 전화번호 모양만 가린다. 앞 번호까지(여는 괄호·국가번호 포함)는 남긴다 */
export function maskPhones(text: string): string {
  return text.replace(PHONE_NUMBER, (match: string, ...rest: unknown[]) => {
    const groups = rest[rest.length - 1] as { intl?: string; mobile?: string; area?: string }
    const prefix = groups.intl ?? groups.mobile ?? groups.area ?? ''
    // 앞 번호는 맨 앞(지역번호는 여는 괄호 다음)에 있다
    const keep = match.indexOf(prefix) + prefix.length
    return match.slice(0, keep) + match.slice(keep).replace(ANY_DIGIT, '*')
  })
}

/**
 * 문서에서 온 글자를 화면에 보여주기 전에 쓴다.
 * "소유자 정○○ 620830-1234567, 010-1234-5678" → "소유자 정○○ ******‑*******, 010-****-****"
 */
export function maskPersonal(text: string): string {
  return maskPhones(maskResidentIds(text))
}
