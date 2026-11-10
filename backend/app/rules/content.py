"""리포트 문구 (PRD 7.3, 12장): 종합 배너, 서류 요청 메시지, 추천 특약, 일정 체크리스트, 고지문.

규칙 판정 결과(등급)만 받아 문구를 고른다. 판정은 engine.py가 한다.
"""

from __future__ import annotations

import datetime as dt
from typing import Mapping, Optional

from app.schemas import ChecklistItem, Overall

# ---------------------------------------------------------------------------
# 7.3 종합 판정
# ---------------------------------------------------------------------------

# 핵심 규칙: 등기부를 제대로 읽었고 임대인 이름이 있으면 항상 판정할 수 있는 규칙.
# 이 중 ⚪가 있으면 "큰 위험 신호 없음"이라고 말하지 않는다.
CORE_RULES = ("R1", "R2", "R3", "R7", "R8", "R13")

OVERALL_RED = (
    "계약 보류 권장",
    "보증금을 잃을 수 있는 위험 신호가 {n}개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요.",
)
OVERALL_YELLOW = ("추가 확인 필요", "계약 전에 확인할 것이 {n}개 있어요.")
OVERALL_INCOMPLETE = (
    "확인 미완료",
    "위험 신호는 찾지 못했지만, 꼭 확인해야 할 항목 {n}개를 확인하지 못했어요. 빠진 내용을 채운 뒤 다시 검사하세요.",
)
OVERALL_GREEN = (
    "큰 위험 신호 없음",
    "확인한 범위에서는 큰 위험 신호를 찾지 못했어요. 안전을 보장하는 것은 아니니 아래 할 일은 꼭 챙기세요.",
)
UNKNOWN_NOTE = "확인하지 못한 항목 {n}개"


def build_overall(levels: Mapping[str, str]) -> Overall:
    """7.3 표를 위에서부터 보고 처음 맞는 줄을 쓴다. levels는 {규칙 ID: 등급}.

    {n}은 그 줄의 조건에 해당하는 규칙 수 (🔴 수, 🟡 수, 핵심 규칙 중 ⚪ 수).
    unknown_note는 ⚪ 전체 수다.
    """
    red = sum(1 for lvl in levels.values() if lvl == "red")
    yellow = sum(1 for lvl in levels.values() if lvl == "yellow")
    unknown = sum(1 for lvl in levels.values() if lvl == "unknown")
    core_unknown = sum(1 for rid in CORE_RULES if levels.get(rid) == "unknown")
    if red:
        level, (title, message), n = "red", OVERALL_RED, red
    elif yellow:
        level, (title, message), n = "yellow", OVERALL_YELLOW, yellow
    elif core_unknown:
        level, (title, message), n = "yellow", OVERALL_INCOMPLETE, core_unknown
    else:
        level, (title, message), n = "green", OVERALL_GREEN, 0
    return Overall(
        level=level,
        title=title,
        message=message.format(n=n),
        unknown_note=UNKNOWN_NOTE.format(n=unknown) if unknown else None,
    )


# ---------------------------------------------------------------------------
# 12.1 서류 요청 메시지
# ---------------------------------------------------------------------------

REQUEST_ALWAYS = ["확정일자 부여현황", "국세·지방세 납세증명서"]
REQUEST_TRUST = ["신탁원부", "신탁회사(수탁자)의 임대 동의서"]  # R2 🔴
REQUEST_PROXY = ["위임장", "인감증명서"]  # R1 🔴 또는 대리인
REQUEST_MORTGAGE = ["근저당 대출을 잔금일에 갚고 말소할 계획인지"]  # R6 🟡이고 저당 행이 있을 때

# 문장 중간에서 줄을 바꾸지 않는다 (휴대폰·메신저에 붙여 넣을 때 끊겨 보인다)
REQUEST_TEMPLATE = (
    "안녕하세요. {address} 임대차 계약 건으로 연락드립니다.\n"
    "계약 전에 아래 내용을 확인하고 싶습니다.\n"
    "\n"
    "{items}\n"
    "\n"
    "확정일자 부여현황과 납세증명서는 계약할 때 임대인이 보여주도록 주택임대차보호법에 정해져 있다고 알고 있습니다.\n"
    "계약일 전에 받아볼 수 있을까요? 감사합니다."
)
ADDRESS_FALLBACK = "계약하려는 집"


def request_items(levels: Mapping[str, str], has_agent: bool, has_mortgage: bool) -> list[str]:
    """12.1 표의 조건에 맞는 항목을 표 순서대로 고른다.

    has_mortgage: 유효 을구에 저당 행이 있는지 (전세권만으로 R6가 🟡이면 근저당 항목을 넣지 않는다).
    """
    items = list(REQUEST_ALWAYS)
    if levels.get("R2") == "red":
        items += REQUEST_TRUST
    if levels.get("R1") == "red" or has_agent:
        items += REQUEST_PROXY
    if levels.get("R6") == "yellow" and has_mortgage:
        items += REQUEST_MORTGAGE
    return items


def build_request_message(address: Optional[str], items: list[str]) -> str:
    numbered = "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))
    return REQUEST_TEMPLATE.format(address=(address or "").strip() or ADDRESS_FALLBACK, items=numbered)


# ---------------------------------------------------------------------------
# 12.2 추천 특약
# ---------------------------------------------------------------------------

TERM_NO_NEW_MORTGAGE = (
    "임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다. "
    "위반 시 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다."
)
TERM_CLEAR_MORTGAGE = "임대인은 잔금일까지 등기부상 근저당권(채권최고액 {amount})을 말소한다."
TERM_JEONSE_GUARANTEE = (
    "임차인이 전세보증금 반환보증에 가입할 수 없는 경우 계약은 무효로 하며, 임대인은 계약금을 즉시 반환한다."
)
TERM_SHOW_DOCUMENTS = "임대인은 계약 체결 시 국세·지방세 납세증명서와 확정일자 부여현황을 제시한다."
TERM_TRUST_CONSENT = (
    "임대인은 잔금일 전까지 수탁자(신탁회사)의 임대 동의서를 제출한다. "
    "제출하지 못하면 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다."
)
# 특약 목록 아래에 보여줄 안내 (화면에서 표시)
SPECIAL_TERMS_NOTE = "실제로 쓰기 전에 공인중개사나 대한법률구조공단에 확인하세요."
# 근저당 금액을 모를 때 채울 자리 표시
AMOUNT_PLACEHOLDER = "○○원"


def build_special_terms(
    levels: Mapping[str, str],
    lease_type: Optional[str],
    mortgage_amount: Optional[str],
) -> list[str]:
    """12.2 표의 조건에 맞는 특약을 표 순서대로 고른다.

    mortgage_amount: 유효 을구 근저당 채권최고액 합계 문구. 근저당이 없으면 None.
    """
    terms = []
    if levels.get("R12") == "yellow":
        terms.append(TERM_NO_NEW_MORTGAGE)
    if levels.get("R6") == "yellow" and mortgage_amount is not None:
        terms.append(TERM_CLEAR_MORTGAGE.format(amount=mortgage_amount))
    if lease_type == "전세":
        terms.append(TERM_JEONSE_GUARANTEE)
    terms.append(TERM_SHOW_DOCUMENTS)
    if levels.get("R2") == "red":
        terms.append(TERM_TRUST_CONSENT)
    return terms


# ---------------------------------------------------------------------------
# 12.3 계약 일정 체크리스트
# ---------------------------------------------------------------------------


def build_checklist(
    contract_date: Optional[dt.date],
    balance_date: Optional[dt.date],
    move_in_date: Optional[dt.date],
    lease_type: Optional[str],
) -> list[ChecklistItem]:
    """12.3 표를 할 일 하나당 한 항목으로 나눈다. '계약 전'·'입주 후'는 날짜가 없다."""
    move_in = move_in_date or balance_date
    rows: list[tuple[str, Optional[dt.date], str]] = [
        ("계약 전", None, "등기부 다시 떼기"),
        ("계약 전", None, "확정일자 부여현황·납세증명서 받기"),
        ("계약 전", None, "임대인 신분증과 등기부 소유자 대조"),
        ("계약일", contract_date, "특약 넣기"),
        ("계약일", contract_date, "계약금은 소유자 명의 계좌로 보내기"),
        ("잔금일", balance_date, "잔금 보내기 전 등기부 다시 떼기 (새 근저당이 없는지)"),
        ("입주일", move_in, "전입신고 + 확정일자 받기 (당일)"),
    ]
    if lease_type == "전세":
        rows.append(("입주 후", None, "전세보증금 반환보증 가입"))
    rows.append(("입주 후", None, "계약서 원본 보관"))
    return [ChecklistItem(when=when, date=date, title=title) for when, date, title in rows]


# ---------------------------------------------------------------------------
# 12.4 고지문
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "이 결과는 올려주신 서류와 공개 데이터를 정해진 기준으로 확인한 참고 정보예요. "
    "법률 자문이 아니며 보증금의 안전을 보장하지 않아요. "
    "중요한 결정 전에는 대한법률구조공단(국번 없이 132) 등 전문가와 상의하세요."
)

# PRD 10장 금지 표현 (테스트와 점검용)
BANNED_PHRASES = ("사기입니다", "안전합니다", "안전한 집", "보장합니다")
