"""응답에서 주민등록번호를 가린다.

등기부 원문(source_text)에는 소유자·권리자의 주민등록번호 앞자리(생년월일)가 그대로 있다
(예: "소유자 정○○ 620830-*******"). 화면 [원문 보기]에 나가지 않도록 API 응답의 모든 문자열에서
주민등록번호 모양(앞 6자리 - 뒤 7자리, 숫자나 가림 글자)을 "******-*******"로 바꾼다.
법인등록번호(예: 110111-*******)도 같은 모양이라 함께 가려진다. 그 밖의 글자는 그대로 둔다.
"""

from __future__ import annotations

import re
from typing import Any, TypeVar

from pydantic import BaseModel

MASKED_ID = "******-*******"

# 숫자와 가림 글자 (*, ＊, ∗, x, X, ○, ◯, 〇, ●)
_ID_CHAR = r"[\d*＊∗xX○◯〇●]"
# 하이픈과 비슷하게 생긴 글자 (사진 OCR·전각 입력)
_DASH = r"[-‐‑‒–—−－]"
# 앞뒤가 숫자로 이어지면 주민등록번호가 아니다 (날짜 범위, 긴 번호). 이름의 ○ 바로 뒤에 붙어 있어도 잡는다.
RESIDENT_ID = re.compile(rf"(?<!\d){_ID_CHAR}{{6}}\s*{_DASH}\s*{_ID_CHAR}{{7}}(?!\d)")

M = TypeVar("M", bound=BaseModel)


def mask_text(text: str) -> str:
    return RESIDENT_ID.sub(MASKED_ID, text)


def _mask(value: Any) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, list):
        return [_mask(item) for item in value]
    if isinstance(value, dict):
        return {key: _mask(item) for key, item in value.items()}  # 키는 필드 이름이라 그대로
    return value


def mask_resident_ids(model: M) -> M:
    """모델 안의 모든 문자열(원문, 근거, 이름 목록 등)에서 주민등록번호 모양을 가린 사본."""
    return type(model).model_validate(_mask(model.model_dump(mode="python")))
