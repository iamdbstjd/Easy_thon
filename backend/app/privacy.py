"""응답에서 주민등록번호와 전화번호를 가린다.

등기부 원문(source_text)에는 소유자·권리자의 주민등록번호 앞자리(생년월일)가 그대로 있다
(예: "소유자 정○○ 620830-*******"). 화면 [원문 보기]에 나가지 않도록 API 응답의 모든 문자열에서
주민등록번호 모양을 "******-*******"로 바꾼다. 법인등록번호(예: 110111-*******)도 같은 모양이라 함께 가려진다.
숫자는 전각(０-９)도 같은 숫자로 본다.

- 하이픈(비슷한 글자 포함)이 있으면: 앞 6자리 - 뒤 7자리 (숫자나 가림 글자). 뒤 7자리 첫 글자 다음 띄어쓰기도 허용.
- 하이픈이 없거나, 띄어쓰기(3칸까지)·줄바꿈 하나·점·빗금·물결·밑줄 같은 다른 구분 글자면: 앞 6자리가 올바른
  생년월일(YYMMDD)이고 뒤 7자리 첫 글자가 1~8(또는 가림 글자)일 때만 가린다.
  13자리 계좌번호나 날짜(2026.11.14) 같은 다른 번호를 가리지 않기 위해서다.

전화번호(010-1234-5678, 01012345678, 02-123-4567, (031)123-4567, +82-10-1234-5678 …)는 앞 번호
(010, 02, 031, +82-10 …)만 남기고 나머지 숫자를 모두 "*"로 바꾼다 (예: "010-****-****", "010********").
구분 글자와 길이는 그대로다. 그 밖의 글자(날짜, 지번, 금액, 접수번호, 사업자번호)는 그대로 둔다.
"""

from __future__ import annotations

import re
from typing import Any, TypeVar

from pydantic import BaseModel

MASKED_ID = "******-*******"

_D = "[0-9０-９]"  # 숫자 (전각 포함)
# 가림 글자 (*, ＊, ∗, x, X, ○, ◯, 〇, ●, #, ＃, ■, □, ◆, ◇, ･, ∙, ·)
_MASK_CHAR = "[*＊∗xX○◯〇●#＃■□◆◇･∙·]"
# 숫자와 가림 글자
_ID_CHAR = "[0-9０-９*＊∗xX○◯〇●#＃■□◆◇･∙·]"
# 하이픈과 비슷하게 생긴 글자 (사진 OCR·전각 입력·한글 'ㅡ'·반각 'ｰ')
_DASH = "[-‐‑‒–—―−－﹣⁃ㅡ─━ーｰ]"
# 생년월일 규칙과 함께일 때만 받는 구분 글자 (점·빗금·물결·밑줄·가운뎃점·'ㅣ')
_WEAK_SEP = "[./~_‧ㅣ．／～＿]"
_HSPACE = r"[^\S\r\n]"  # 줄바꿈이 아닌 공백
_YYMMDD = "[0-9０-９]{2}(?:[0０][1-9１-９]|[1１][0-2０-２])(?:[0０][1-9１-９]|[12１２][0-9０-９]|[3３][01０１])"
_GAP = rf"(?:{_HSPACE}{{0,3}}|{_HSPACE}{{0,3}}(?:{_WEAK_SEP}|\r?\n){_HSPACE}{{0,3}})"
_BACK7 = rf"{_ID_CHAR}{_HSPACE}?{_ID_CHAR}{{6}}"
_WITH_DASH = rf"{_ID_CHAR}{{6}}\s*{_DASH}\s*{_BACK7}"
_BIRTH_DATE = rf"{_YYMMDD}{_GAP}(?:[1-8１-８]|{_MASK_CHAR}){_HSPACE}?{_ID_CHAR}{{6}}"
# 앞뒤가 숫자로 이어지면 주민등록번호가 아니다 (날짜 범위, 긴 번호). 이름의 ○ 바로 뒤에 붙어 있어도 잡는다.
RESIDENT_ID = re.compile(rf"(?<!{_D})(?:{_WITH_DASH}|{_BIRTH_DATE})(?!{_D})")

_PHONE_DASH = "[-‐‑‒–—−－.ㅡ]"
_PHONE_SEP = rf"(?:{_HSPACE}?{_PHONE_DASH}{_HSPACE}?|{_HSPACE})"
_MOBILE = "[0０][1１][016789０１６７８９]"
_AREA = "[0０][2２]|[0０][3-6３-６][1-5１-５]|[0０][7７][0０]|[0０][5５][0０][2-8２-８]?|[0０][8８][0０]"
_INTL = "[+＋][8８][2２]"  # 국가번호 다음에는 앞자리 0을 뺀다 (+82-10-…, +82-2-…)
_INTL_CODE = "[1１][016789０１６７８９]|[2２]|[3-6３-６][1-5１-５]|[7７][0０]"
# 휴대전화·국제 표기는 구분 글자가 없어도 잡는다. 지역번호·인터넷전화는 구분 글자가 있을 때만 (다른 번호와 헷갈리지 않게).
PHONE_NUMBER = re.compile(
    rf"(?<!{_D})(?<!{_D}{_PHONE_DASH})"
    rf"(?:(?P<intl>{_INTL}{_PHONE_SEP}?(?:{_INTL_CODE})){_PHONE_SEP}?{_D}{{3,4}}{_PHONE_SEP}?{_D}{{4}}"
    rf"|(?P<mobile>{_MOBILE}){_PHONE_SEP}?{_D}{{3,4}}{_PHONE_SEP}?{_D}{{4}}"
    rf"|\(?(?P<area>{_AREA})(?:\){_PHONE_SEP}?|{_PHONE_SEP}){_D}{{3,4}}{_PHONE_SEP}{_D}{{4}})"
    rf"(?!{_D})(?!{_PHONE_DASH}{_D})"
)
_DIGIT = re.compile(_D)

M = TypeVar("M", bound=BaseModel)


def _mask_phone(match: re.Match[str]) -> str:
    prefix = next(name for name in ("intl", "mobile", "area") if match.group(name))
    keep = match.end(prefix) - match.start()
    text = match.group()
    return text[:keep] + _DIGIT.sub("*", text[keep:])


def mask_text(text: str) -> str:
    """주민등록번호 모양은 "******-*******"로, 전화번호는 앞 번호만 남기고 가린다."""
    return PHONE_NUMBER.sub(_mask_phone, RESIDENT_ID.sub(MASKED_ID, text))


def mask_value(value: Any) -> Any:
    """JSON 같은 값(dict·list·str) 안의 모든 문자열을 가린 사본. 키는 필드 이름이라 그대로 둔다."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, list):
        return [mask_value(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_value(item) for key, item in value.items()}
    return value


def mask_resident_ids(model: M) -> M:
    """모델 안의 모든 문자열(원문, 근거, 이름 목록 등)에서 주민등록번호·전화번호 모양을 가린 사본."""
    return type(model).model_validate(mask_value(model.model_dump(mode="python")))
