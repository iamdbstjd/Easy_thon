"""규칙 엔진 공통 도구: 날짜, 이름·주소 정리, 층 찾기, 금액·비율 표시."""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Optional, Union
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# ---------------------------------------------------------------------------
# 날짜
# ---------------------------------------------------------------------------


def now_kst() -> dt.datetime:
    """현재 한국 시각 (초 단위, 시간대 포함)."""
    return dt.datetime.now(KST).replace(microsecond=0)


def today_kst() -> dt.date:
    """현재 한국 날짜."""
    return dt.datetime.now(KST).date()


def to_kst(value: dt.datetime) -> dt.datetime:
    """한국 시각으로 바꾼다. 시간대가 없으면 한국 시각으로 본다."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def fmt_date(value: dt.date) -> str:
    """2026-08-26 → "2026년 8월 26일"."""
    return f"{value.year}년 {value.month}월 {value.day}일"


_PERIOD = re.compile(r"^\s*(\d{4})-(\d{1,2})\s*~\s*(\d{4})-(\d{1,2})\s*$")


def fmt_period(period: str) -> str:
    """조회 기간 "2025-12 ~ 2026-11" → "2025년 12월 ~ 2026년 11월". 다른 형식은 그대로 둔다."""
    m = _PERIOD.match(period or "")
    if not m or not all(1 <= int(month) <= 12 for month in (m.group(2), m.group(4))):
        return period
    return f"{m.group(1)}년 {int(m.group(2))}월 ~ {m.group(3)}년 {int(m.group(4))}월"


# ---------------------------------------------------------------------------
# 글자·이름 정리
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def compact(text: Optional[str]) -> str:
    """공백을 모두 지운다."""
    return _WS.sub("", text or "")


# 회사 표기
_COMPANY_MARKS = ("(주)", "（주）", "㈜", "주식회사", "유한회사", "(유)", "（유）")
# 이름에 잘못 붙어 올 수 있는 역할어
ROLE_WORDS = ("근저당권자", "수탁자", "소유자", "공유자", "채권자", "임대인", "임차인")
# 주민·법인등록번호 형식 (######-#######). 숫자 대신 *·x·○·● 등으로 가린 것도 포함한다.
# 이름 비교, 화면용 이름, 근거 원문 가리기에 모두 이 형식을 쓴다
_ID_CHAR = r"[0-9*＊xX○●•]"
_ID_NUMBER = re.compile(rf"(?<![0-9]){_ID_CHAR}{{6}}\s*-\s*{_ID_CHAR}{{7}}")
_ROLE_PREFIX = re.compile(r"^(?:" + "|".join(ROLE_WORDS) + r")\s*")
ID_MASK = "******-*******"


def strip_id_numbers(text: Optional[str]) -> str:
    """등록번호 형식을 지운다 ("김철수 850315-1xxxxxx" → "김철수")."""
    return _WS.sub(" ", _ID_NUMBER.sub(" ", text or "")).strip()


def mask_id_numbers(text: Optional[str]) -> str:
    """근거 원문의 등록번호 형식("900101-*******" 등)을 "******-*******"로 바꾼다. 나머지는 그대로 둔다."""
    return _ID_NUMBER.sub(ID_MASK, text or "")


def normalize_name(name: Optional[str]) -> str:
    """이름 비교용 정리: 공백, 회사 표기, 역할어, 등록번호를 지운다."""
    text = _ID_NUMBER.sub("", compact(name))
    for mark in _COMPANY_MARKS:
        text = text.replace(mark, "")
    for word in ROLE_WORDS:
        text = text.replace(word, "")
    return text


def display_name(name: Optional[str]) -> str:
    """화면용 이름: 등록번호와 앞에 붙은 역할어를 떼고 나머지 원문을 살린다."""
    return _ROLE_PREFIX.sub("", strip_id_numbers(name)).strip()


# ---------------------------------------------------------------------------
# 조사 (받침에 따라 이에요/예요, 으로/로)
# ---------------------------------------------------------------------------

# 숫자를 읽었을 때의 받침 (영·일·이·삼·사·오·육·칠·팔·구)
_DIGIT_JONG = {"0": 21, "1": 8, "2": 0, "3": 16, "4": 0, "5": 0, "6": 1, "7": 8, "8": 8, "9": 0}
_TAIL_SKIP = set(" )]}'\"’”」』")


def _final_jong(word: str) -> Optional[int]:
    """마지막 글자의 받침 번호 (0이면 받침 없음, ㄹ은 8). 한글·숫자가 아니면 None."""
    for ch in reversed(word or ""):
        if ch in _TAIL_SKIP:
            continue
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            return code % 28
        return _DIGIT_JONG.get(ch)
    return None


def josa_ieyo(word: str) -> str:
    """'이에요/예요'. 판단할 수 없으면(○ 등) '이에요'."""
    return "예요" if _final_jong(word) == 0 else "이에요"


def josa_iga(word: str) -> str:
    """'이/가'. 받침이 없으면 '가', 판단할 수 없으면 '이'."""
    return "가" if _final_jong(word) == 0 else "이"


def josa_euro(word: str) -> str:
    """'으로/로'. 받침이 없거나 ㄹ이면 '로', 판단할 수 없으면 '으로'."""
    return "로" if _final_jong(word) in (0, 8) else "으로"


# ---------------------------------------------------------------------------
# 금액·비율
# ---------------------------------------------------------------------------


def fmt_money(amount: int) -> str:
    """120000000 → "1억 2,000만 원", 12345678 → "1,234만 5,678원", 0 → "0원"."""
    if amount < 0:
        return "-" + fmt_money(-amount)
    if amount == 0:
        return "0원"
    eok, rest = divmod(amount, 100_000_000)
    man, won = divmod(rest, 10_000)
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    if won:
        parts.append(f"{won:,}원")
        return " ".join(parts)
    return " ".join(parts) + " 원"


Number = Union[int, float, Decimal, Fraction]


def _to_fraction(value: Number) -> Fraction:
    if isinstance(value, float):
        return Fraction(Decimal(repr(value)))
    return Fraction(value)


def percent_floor(value: Number) -> int:
    """비율 → 정수 퍼센트. 기준값(70%·80%)과 어긋나지 않게 버림한다 (0.7999 → 79)."""
    return math.floor(_to_fraction(value) * 100)


def fmt_percent(value: Number) -> str:
    """0.9 → "90%"."""
    return f"{percent_floor(value)}%"


# ---------------------------------------------------------------------------
# 층 (R10)
# ---------------------------------------------------------------------------

Floor = tuple[bool, int]  # (지하 여부, 층 번호)

# 호수·층 칸 맨 앞의 지하 표시 (지하·지·비·B). 칸 전체가 호실 표기라 그대로 믿는다.
_UNIT_BASEMENT = re.compile(r"^제?(?:지하|지|비|[Bb])제?(\d+)")
# 용도 줄 안의 지하 표시. "지"·"비"는 앞이 한글이 아닐 때만 ("대지", "설비"는 지하가 아니다)
_LINE_BASEMENT = r"(?:지하|(?<![가-힣])[지비]|(?<![A-Za-z])[Bb])"
_FLOOR_TOKEN = re.compile(r"\d+층|(?<![A-Za-z])[Bb]\d+")


def parse_floor(text: Optional[str]) -> Optional[Floor]:
    """"3층"·"제3층" → (False, 3), "지하1층"·"지1층"·"B1"·"비1층" → (True, 1)."""
    t = compact(text)
    if not t:
        return None
    m = _UNIT_BASEMENT.match(t)
    if m:
        return (True, int(m.group(1)))
    m = re.search(r"\d+", t)
    if m and int(m.group()) > 0:
        return (False, int(m.group()))
    return None


def is_basement_unit(text: Optional[str]) -> bool:
    """호수·층 칸이 지하 표시(지하·지·비·B)로 시작하는지 ("B102호", "비102호")."""
    return _UNIT_BASEMENT.match(compact(text)) is not None


def floor_from_ho(ho: Optional[str]) -> Optional[Floor]:
    """층 정보가 없을 때 3·4자리 호수로 층을 구한다: "302호" → 3층, "1201호" → 12층. 지하 호수는 None."""
    t = compact(ho)
    if not t or is_basement_unit(t):
        return None
    nums = re.findall(r"\d+", t)
    if not nums:
        return None
    digits = nums[-1]
    if len(digits) == 3:
        n = int(digits[0])
    elif len(digits) == 4:
        n = int(digits[:2])
    else:
        return None
    return (False, n) if n > 0 else None


def _tidy_floor_text(line: str) -> str:
    """"지하 1 층"·"제 3 층"처럼 띄어 쓴 층 표기를 붙인다."""
    t = re.sub(r"(지하|지|비|제|[Bb])\s+(?=\d)", r"\1", line)
    return re.sub(r"(\d)\s+층", r"\1층", t)


def line_has_floor(line: str, floor: Floor) -> bool:
    """용도 줄에 그 층이 있는지. 3층은 "13층"·"지하3층"·"지3층"·"비3층"과 맞지 않는다."""
    basement, n = floor
    t = _tidy_floor_text(line)
    if basement:
        return re.search(_LINE_BASEMENT + rf"제?0*{n}(?!\d)", t) is not None
    above = re.sub(_LINE_BASEMENT + r"제?\d+층?", " ", t)  # 지하층 표기를 먼저 지운다
    return re.search(rf"(?<!\d)(?:제)?0*{n}층", above) is not None


def is_header_line(line: str) -> bool:
    """건물 전체 줄: "구조"나 "지붕"이 있는 줄. 층수가 적혀 있어도 층별 줄이 아니다."""
    t = compact(line)
    return "지붕" in t or "구조" in t


def is_floor_line(line: str) -> bool:
    """층별 줄: 건물 전체 줄이 아니고 "N층"(또는 "B1")이 있는 줄."""
    return not is_header_line(line) and _FLOOR_TOKEN.search(_tidy_floor_text(line)) is not None


# ---------------------------------------------------------------------------
# 주소 (R11)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AddressCore:
    """주소의 핵심: 지번("죽전동", "123-4") 또는 도로명("포은대로", "123")."""

    kind: str  # "jibun" | "road"
    name: str
    number: str

    @property
    def text(self) -> str:
        return f"{self.name} {self.number}"


_HYPHENS = re.compile(r"[‐‑‒–—－﹣−]")
_JIBUN_RE = re.compile(r"([가-힣][가-힣0-9]*(?:동|리|가))\s*(산\s*)?(\d+)(?:\s*-\s*(\d+))?(?!\d)")
_ROAD_RE = re.compile(r"([가-힣][가-힣0-9·.]*(?:로|길))\s*(?:지하\s*)?(\d+)(?:\s*-\s*(\d+))?(?!\d)")
_LOT_RE = re.compile(r"(산)?(\d+)(?:-(\d+))?")


def tidy_address(text: Optional[str]) -> str:
    """비교 전 정리: 공백을 하나로, "번지"와 숫자 앞 "제"를 지운다."""
    t = _HYPHENS.sub("-", text or "")
    t = re.sub(r"\s*번지", "", t)
    t = re.sub(r"제\s*(?=\d)", "", t)
    return _WS.sub(" ", t).strip()


def jibun_core(address: Optional[str]) -> Optional[AddressCore]:
    """"경기도 용인시 수지구 죽전동 123-4" → 죽전동 123-4. 못 찾으면 마지막 두 낱말."""
    t = tidy_address(address)
    if not t:
        return None
    m = _JIBUN_RE.search(t)
    if m:
        number = ("산" if m.group(2) else "") + m.group(3) + (f"-{m.group(4)}" if m.group(4) else "")
        return AddressCore("jibun", m.group(1), number)
    tokens = t.split(" ")
    if len(tokens) >= 2 and re.search(r"\d", tokens[-1]):
        return AddressCore("jibun", tokens[-2], tokens[-1])
    return None


def road_core(address: Optional[str]) -> Optional[AddressCore]:
    """"경기도 용인시 수지구 포은대로 123" → 포은대로 123."""
    m = _ROAD_RE.search(tidy_address(address))
    if not m:
        return None
    number = m.group(2) + (f"-{m.group(3)}" if m.group(3) else "")
    return AddressCore("road", m.group(1), number)


def address_has_core(address: Optional[str], core: AddressCore) -> bool:
    """주소에 지번·도로명 핵심이 그대로 있는지. "123-4"는 "123-45"와 맞지 않는다."""
    pattern = re.escape(compact(core.name)) + r"\s*"
    lot = _LOT_RE.fullmatch(compact(core.number))
    if lot:
        pattern += (r"산\s*" if lot.group(1) else "") + lot.group(2)
        if lot.group(3):
            pattern += r"\s*-\s*" + lot.group(3)
    else:
        pattern += re.escape(compact(core.number))
    pattern += r"(?!\d)(?!\s*-\s*\d)"
    if core.kind == "road":
        pattern += r"(?!\s*번\s*길)"  # "포은대로 123"이 "포은대로123번길"과 맞지 않게
    return re.search(pattern, tidy_address(address)) is not None


# ---------------------------------------------------------------------------
# 동·호 (R11)
# ---------------------------------------------------------------------------

# 주소 안의 호수: "302호", "제302호", "빌라302호", "지하102호", "B102호", "비102호", "302-1호".
# "지"·"비"는 앞이 한글이 아닐 때만 지하 표시로 본다 ("○○빌리지 302호"는 지하가 아니다).
_HO_IN_ADDR = re.compile(
    r"(?:제\s*)?(?P<mark>지하\s*|(?<![가-힣])[지비]|(?<![A-Za-z])[Bb])?(?:제\s*)?(?P<num>\d+(?:-\d+)?)\s*호"
)
# 호수 바로 앞(또는 주소 끝)의 건물 동: 숫자, 영문 한 글자, 한글 한 글자("가동").
# 한글은 앞이 한글이 아닐 때만 인정해 "죽전동" 같은 법정동 이름을 건물 동으로 읽지 않는다.
_DONG_AT_END = re.compile(
    r"(?:(?<![0-9])(?P<num>\d+)|(?<![A-Za-z])(?P<lat>[A-Za-z])|(?<![가-힣])(?P<han>[가-힣]))"
    r"\s*동\s*(?:제?\s*(?:지하|지|비|[Bb])?\s*\d+\s*층\s*)?$"
)
# 호수 바로 앞의 지하층 표기 ("지하1층 102호" → 지하 호수)
_BASEMENT_FLOOR_BEFORE = re.compile(r"(?:지하|(?<![가-힣])[지비]|(?<![A-Za-z])[Bb])\s*\d+\s*층\s*$")


def unit_key(text: Optional[str], suffix: str = "호") -> Optional[str]:
    """동·호 비교용 값: 공백·"제"·"호"(동은 "동")를 지우고 호수의 지하 표시를 "B"로 통일한다.

    숫자 앞의 0은 무시한다. "제302호"·"0302호" → "302", "지하102호"·"비102호"·"B102호" → "B102",
    "302-1호" → "302-1", "가동" → "가".
    """
    t = compact(text).replace("제", "").replace(suffix, "").upper()
    if suffix == "호":
        t = re.sub(r"^(?:지하|지|비|B)(?=\d)", "B", t)
    t = re.sub(r"(?<!\d)0+(?=\d)", "", t)
    return t or None


def unit_text(text: Optional[str], suffix: str) -> Optional[str]:
    """화면용 동·호 표기: 원문을 살리고 앞의 "제"만 뗀다 ("B102호", "302-1호", "101" → "101동")."""
    t = re.sub(r"^제\s*", "", _WS.sub(" ", (text or "").strip()))
    if not t:
        return None
    return t if t.endswith(suffix) else t + suffix


def unit_in_address(address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """주소에서 건물 동·호를 원문 표기로 읽는다. 띄어쓰기가 없어도 읽는다.

    "…빌라302호" → (None, "302호"), "…101동302호" → ("101동", "302호"), "…가동 지하102호" → ("가동", "지하102호").
    호수 바로 앞에 지하층이 적혀 있으면 지하 호수로 본다: "…지하1층 102호" → (None, "지하102호").
    """
    text = address or ""
    matches = list(_HO_IN_ADDR.finditer(text))
    last = matches[-1] if matches else None
    ho = None
    if last:
        mark = compact(last.group("mark"))
        if not mark and _BASEMENT_FLOOR_BEFORE.search(text[: last.start()]):
            mark = "지하"
        ho = f"{mark}{last.group('num')}호"
    head = (text[: last.start()] if last else text).rstrip(" ,")
    m = _DONG_AT_END.search(head)
    dong = f"{m.group('num') or m.group('lat') or m.group('han')}동" if m else None
    return dong, ho


def unit_label(dong: Optional[str], ho: Optional[str]) -> str:
    """("101동", "302호") → "101동 302호"."""
    return " ".join(p for p in (dong, ho) if p)
