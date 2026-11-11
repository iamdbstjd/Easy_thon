"""계약 후 재확인 (잔금 전·잔금 당일·입주 후).

계약서와 오늘 뗀 등기부만으로, 계약일(비교 기준일) 이후 새로 생긴 권리와 계약서 특약의 이행 여부를 본다.
계약 당시 등기부는 받지도 저장하지도 않는다.
- 같은 입력이면 generated_at 말고는 같은 결과가 나온다.
- 한 항목을 판단하다 실패하면 그 항목만 ⚪로 둔다.
- 새 권리와 별개로 지금 소유자·신탁·주소를 계약서와 맞춰 본다 (계약 전부터 있던 문제도 잔금 전에 알린다).
- 올린 등기부로 계약 후 변화를 볼 수 없으면(계약일 이전에 뗀 등기부, 갑구 없음, 읽지 못한 부분, 다른 집 등기부)
  "새로 생긴 권리 없음"이라고 말하지 않고 "확인 미완료"로 둔다.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.schemas import (
    CheckRequest,
    ContractExtract,
    Entry,
    ManualInput,
    Overall,
    RecheckChange,
    RecheckReport,
    RecheckRequest,
    RegistryExtract,
    TermCheck,
)

from . import content
from .common import compact, fmt_date, fmt_money, josa_euro, mask_id_numbers, normalize_name, now_kst, to_kst, today_kst
from .engine import (
    Ctx,
    active_segments,
    base_rank,
    contract_address_text,
    current_ownership,
    entry_evidence,
    has_word,
    holder_names,
    is_prohibition_clause,
    is_removal_clause,
    is_removal_record,
    known_amount,
    make_context,
    registry_address_text,
    rule_r1,
    rule_r2,
    rule_r11,
    run_rule,
)

logger = logging.getLogger(__name__)

PHASE_BEFORE, PHASE_BALANCE_DAY, PHASE_AFTER = "before_balance", "balance_day", "after_move_in"

# 종합 판정 제목
TITLE_HOLD_BALANCE = "잔금 보류 권장"
TITLE_PROTECT_DEPOSIT = "보증금 보호 확인 필요"
TITLE_CHECK_MORE = "추가 확인 필요"
TITLE_NOTHING_NEW = "새로 생긴 권리 없음"
TITLE_INCOMPLETE = "확인 미완료"  # 모르면 "없음"이라고 말하지 않는다
UNKNOWN_NOTE = "확인하지 못한 항목 {n}개"

# 새로 생긴 권리 결과
NOTE_NEW = "계약 후 새로 생김"  # 등기목적은 따로 보여 주므로 반복하지 않는다
NOTE_SAME_DAY = "계약 당일 접수: 계약 때 본 등기부에 있었는지 확인하세요"
NOTE_VIEW_DAY = "계약 때 본 등기부를 뗀 날 접수: 그 등기부에 있었는지 확인하세요"
NOTE_BEFORE_CONTRACT = "계약 때 본 등기부 뒤, 계약 전에 생김"
NOTE_CONTRACT_DAY_AFTER_VIEW = "계약 당일 접수: 계약 때 본 등기부 뒤에 생김"
NOTE_MOVE_IN_DAY = "전입신고와 같은 날 등기돼 세입자보다 앞서요"
NOTE_OWNER_CHANGED = "계약 후 집주인이 바뀌었어요"
NOTE_SUB_CHANGE = "기존 권리 변경: 무엇이 바뀌었는지 원문을 확인하세요"
NOTE_MORTGAGE_RAISED = "기존 근저당의 채권최고액이 늘었어요"
NOTE_NO_DATE = "접수일을 읽지 못해 계약 후에 생긴 것인지 알 수 없어요"
NOTE_FAILED = "이 항목을 확인하는 중 문제가 생겼어요"
NOTE_TERM_BLOCKED = "올린 등기부로는 계약 후 변화를 확인할 수 없어 이행 여부를 판단하지 못했어요."

# 할 일
ACTION_HOLD_BALANCE = "잔금을 보내기 전에 임대인에게 말소를 요구하고, 해결되기 전에는 잔금을 미루세요."
ACTION_HOLD_STANDING = "위 내용이 확인되기 전에는 잔금을 미루세요."
ACTION_TERM_BROKEN = "계약서 특약({kind})에 어긋나요. 공인중개사·대한법률구조공단(국번 없이 132)과 상의해 대응하세요."
KIND_PROHIBITION, KIND_REMOVAL = "담보 설정 금지", "근저당 말소"
ACTION_AFTER_MOVE_IN = "전입신고·확정일자를 받았는지 확인하고, 대한법률구조공단이나 전세피해지원센터에 상담하세요."
ACTION_ALL_CLEAR = "잔금 보내기 직전에 한 번 더 떼어 보고, 입주 당일 전입신고와 확정일자를 받으세요."
ACTION_ALL_CLEAR_AFTER = "전입신고 다음 날에도 한 번 더 확인하세요."
ACTION_UNREAD_DATES = "접수일을 읽지 못한 항목은 등기부 원문에서 날짜를 직접 확인하세요."
ACTION_NO_BASELINE = "계약서의 계약일을 확인한 뒤 다시 확인하세요."
ACTION_OWNER = (
    "임대인이 등기부상 소유자와 다른 이유를 확인하세요. "
    "대리 계약이면 위임장과 인감증명서를 확인하고, 보증금은 소유자 명의 계좌로만 보내세요."
)
ACTION_TRUST = "신탁원부와 신탁회사(수탁자)의 임대 동의서를 받았는지 확인하세요."
ACTION_UNIT = "올린 등기부가 계약한 집의 것인지 확인하세요. 같은 집이라면 계약서와 전입신고에 등기부의 동·호수를 그대로 적어야 해요."
ACTION_NEW_REGISTRY = "잔금을 보내기 전에 오늘 날짜로 등기부를 다시 떼어 올려 확인하세요."
ACTION_NEW_REGISTRY_AFTER = "오늘 날짜로 등기부를 다시 떼어 올려 확인하세요."
ACTION_BALANCE_DAY_REGISTRY = "잔금을 보내기 직전에 등기부를 다시 떼어 올려 확인하세요."
ACTION_TRUST_UNKNOWN = "등기부 원문에서 신탁이 말소됐는지(신탁재산의귀속 등) 확인하세요."
ACTION_ADDRESS = "올린 등기부가 계약서의 주소·동·호수와 같은 집의 것인지 확인하고, 맞는 등기부를 다시 올려 확인하세요."
ACTION_LANDLORD = "계약서의 임대인 이름과 등기부의 소유자 이름이 잘 보이게 다시 올려 확인하세요."

# 확인 미완료 이유
REASON_NO_GAPGU = "등기부 갑구 항목을 확인하지 못했어요."
REASON_UNREADABLE = "등기부에서 읽지 못한 부분이 있어요({parts})."
REASON_NO_VIEWED_AT = "등기부 열람 일시를 확인하지 못해 계약 후에 뗀 등기부인지 알 수 없어요."
REASON_STALE = "올린 등기부는 {viewed}에 뗀 것이라 {label}({ref}) 뒤의 변화가 나오지 않아요."
REASON_NOT_BALANCE_DAY = "올린 등기부는 {viewed}에 뗀 것이라 잔금일({ref}) 당일에 접수된 권리가 나오지 않아요."
REASON_NOT_AFTER_MOVE_IN = "올린 등기부는 {viewed}에 뗀 것이라 {label}({ref}) 당일에 접수된 권리가 나오지 않아요."
REASON_MOVE_IN_SAME_DAY = "올린 등기부는 {label}({ref}) 당일에 뗀 것이라 그날 늦게 접수된 권리가 나오지 않을 수 있어요."
REASON_TRUST_UNKNOWN = "신탁이 끝났는지 등기부로 확인하지 못했어요."
REASON_ADDRESS = "계약서 주소에서 등기부의 지번이나 도로명을 찾지 못해 계약한 집의 등기부인지 알 수 없어요."
REASON_ADDRESS_UNKNOWN = "계약서와 등기부의 주소·호수를 맞춰 보지 못해 계약한 집의 등기부인지 알 수 없어요."
REASON_LANDLORD = "계약서 임대인과 등기부상 지금 소유자를 맞춰 보지 못했어요."

_STATUS_LEVEL_ORDER = {"red": 0, "yellow": 1, "unknown": 2, "green": 3}


# ---------------------------------------------------------------------------
# 기준일·단계
# ---------------------------------------------------------------------------


def baseline_date(req: RecheckRequest) -> Optional[dt.date]:
    """비교 기준일: 계약일. 계약 때 본 등기부 열람일이 있으면 그날과 계약일 중 이른 날."""
    dates = [req.contract.contract_date]
    if req.baseline_viewed_at is not None:
        dates.append(to_kst(req.baseline_viewed_at).date())
    known = [d for d in dates if d is not None]
    return min(known) if known else None


@dataclass
class _Dates:
    baseline: dt.date  # 이 날 이후 접수된 권리를 새것으로 본다 (계약 때 본 등기부 열람일이 더 이르면 그날)
    contract: dt.date  # 특약은 계약일 기준으로 판단한다 (계약일이 없으면 baseline)


def phase_of(today: dt.date, balance: Optional[dt.date]) -> str:
    """잔금일과 오늘을 비교한 단계. 잔금일을 모르면 잔금 전으로 보고 가장 조심스럽게 안내한다."""
    if balance is None or today < balance:
        return PHASE_BEFORE
    return PHASE_BALANCE_DAY if today == balance else PHASE_AFTER


# ---------------------------------------------------------------------------
# 새로 생긴 권리
# ---------------------------------------------------------------------------

_SUB_RANK = re.compile(r"^(\d+)-\d+$")  # 부기 등기 순위번호 ("1-1")
_DISPLAY_CHANGE_WORDS = ("표시변경", "표시경정")  # 등기명의인·건물 표시 변경은 권리가 아니다


@dataclass
class _Row:
    section: str
    index: int
    entry: Entry


def _is_display_change(e: Entry) -> bool:
    segs = active_segments(e)
    return bool(segs) and all(any(w in s for w in _DISPLAY_CHANGE_WORDS) for s in segs)


def _continues(e: Entry, previous: Optional[Entry]) -> bool:
    """앞 행과 같은 순위번호를 나눠 적은 줄인지 (예: "3 소유권이전 … 수탁자" 다음의 "3 신탁").

    권리자가 없고 순위번호가 같으며, "신탁"만 적혔거나 접수일이 앞 행과 같을 때만 그렇게 본다
    (순위번호를 잘못 읽은 새 가압류 등을 빠뜨리지 않게).
    """
    if previous is None or holder_names(e.holders) or not compact(e.rank) or compact(e.rank) != compact(previous.rank):
        return False
    segs = active_segments(e)
    if segs and all(s == "신탁" for s in segs):
        return True
    return e.received_at is not None and e.received_at == previous.received_at


def _rows(registry: RegistryExtract) -> list[_Row]:
    """유효 항목 (말소 기록 행, 표시 변경 행, 같은 순위번호를 나눠 적은 줄은 뺀다)."""
    rows = []
    for section, entries in (("gapgu", registry.gapgu), ("eulgu", registry.eulgu)):
        previous: Optional[Entry] = None
        for i, e in enumerate(entries):
            if e.is_cancelled or is_removal_record(e) or _is_display_change(e):
                continue
            if _continues(e, previous):
                continue
            previous = e
            rows.append(_Row(section, i, e))
    return rows


def _main_rank(rank: str) -> Optional[str]:
    """부기 등기("1-1")면 주등기 순위번호("1"), 아니면 None."""
    m = _SUB_RANK.match(compact(rank))
    return m.group(1) if m else None


def _is_mortgage_change(e: Entry) -> bool:
    return has_word(e, ("저당",)) and not has_word(e, ("질권",)) and any("변경" in s for s in active_segments(e))


@dataclass
class _MortgageChange:
    entry: Entry
    previous: Optional[int]  # 바뀌기 전 채권최고액
    raised: Optional[bool]  # 늘었는지 (금액을 몰라 알 수 없으면 None)


@dataclass
class _Facts:
    """등기부에서 한 번만 구해 두는 값 (항목·특약마다 등기부 전체를 다시 훑지 않게)."""

    mains: dict[tuple[str, str], Entry]  # (구역, 순위번호) → 주등기 (말소 표시가 있어도 접수일을 보려고 둔다)
    changes: list[_MortgageChange]  # 유효 을구의 (근)저당 변경 부기 등기
    raised: dict[int, Optional[bool]]  # id(부기 항목) → 채권최고액이 늘었는지


def registry_facts(registry: RegistryExtract) -> _Facts:
    mains: dict[tuple[str, str], Entry] = {}
    for section, entries in (("gapgu", registry.gapgu), ("eulgu", registry.eulgu)):
        for e in entries:
            mains.setdefault((section, compact(e.rank)), e)
    changes, last = [], {}  # last: 순위번호 → 그 근저당(주등기·앞선 부기)에 마지막으로 적힌 채권최고액
    for e in registry.eulgu:
        if e.is_cancelled or is_removal_record(e):
            continue
        main = _main_rank(e.rank)
        amount = known_amount(e.amount)
        if main is not None and _is_mortgage_change(e):
            previous = last.get(main)
            raised = None if amount is None or previous is None else amount > previous
            changes.append(_MortgageChange(e, previous, raised))
        rank = base_rank(e.rank)
        if rank is not None and amount is not None and not has_word(e, ("질권",)):  # 질권 금액은 근저당 금액이 아니다
            last[rank] = amount
    return _Facts(mains=mains, changes=changes, raised={id(c.entry): c.raised for c in changes})


def _owner_changed(req: RecheckRequest, baseline: dt.date) -> Optional[Entry]:
    """현재 소유자가 계약서 임대인과 다르고 그 소유권 항목이 기준일 이후 접수됐으면 그 항목."""
    gapgu = [e for e in req.registry.gapgu if not e.is_cancelled]
    own = current_ownership(gapgu) if gapgu else None
    if own is None or own.entry.received_at is None or own.entry.received_at < baseline or not own.owners:
        return None
    landlords = {normalize_name(n) for n in req.contract.landlord_names if normalize_name(n)}
    owners = {normalize_name(o) for o in own.owners}
    if not landlords or landlords <= owners:  # 임대인 이름이 없으면 비교하지 않는다 (새 권리로만 표시)
        return None
    return own.entry


def _change(row: _Row, level: str, note: str) -> RecheckChange:
    e = row.entry
    return RecheckChange(
        section=row.section,
        rank=e.rank,
        purpose=e.purpose,
        received_at=e.received_at,
        holders=holder_names(e.holders),
        amount=e.amount,
        level=level,
        note=note,
        page=e.page,
        source_text=mask_id_numbers(entry_evidence(e).text),
    )


def _sub_row_result(row: _Row, facts: _Facts, baseline: dt.date) -> Optional[tuple[str, str]]:
    """계약 전부터 있던 권리에 붙은 부기 등기면 (등급, 결과). 아니면 None."""
    main = _main_rank(row.entry.rank)
    main_entry = facts.mains.get((row.section, main)) if main else None
    if main_entry is None or main_entry.received_at is None or main_entry.received_at >= baseline:
        return None
    if facts.raised.get(id(row.entry)):
        return "red", NOTE_MORTGAGE_RAISED
    return "yellow", NOTE_SUB_CHANGE


def _judge_row(
    row: _Row,
    facts: _Facts,
    dates: _Dates,
    phase: str,
    move_in: Optional[dt.date],
    owner_entry: Optional[Entry],
) -> Optional[tuple[str, str]]:
    """(등급, 결과) 또는 새로 생긴 권리가 아니면 None."""
    received = row.entry.received_at
    if received is None:
        return "unknown", NOTE_NO_DATE
    if received < dates.baseline:
        return None
    if row.entry is owner_entry:
        return "red", NOTE_OWNER_CHANGED
    sub = _sub_row_result(row, facts, dates.baseline)
    if sub is not None:
        return sub
    if phase == PHASE_AFTER and move_in is not None and received == move_in:
        return "red", NOTE_MOVE_IN_DAY
    if received == dates.baseline:
        return "yellow", NOTE_SAME_DAY if dates.baseline == dates.contract else NOTE_VIEW_DAY
    if received < dates.contract:  # 계약 때 본 등기부를 뗀 뒤, 계약 전에 생긴 권리
        return "red", NOTE_BEFORE_CONTRACT
    if received == dates.contract:
        return "red", NOTE_CONTRACT_DAY_AFTER_VIEW
    return "red", NOTE_NEW


def find_changes(
    req: RecheckRequest,
    dates: _Dates,
    phase: str,
    move_in: Optional[dt.date],
    owner_entry: Optional[Entry],
    facts: _Facts,
) -> list[RecheckChange]:
    found = []
    for row in _rows(req.registry):
        try:
            judged = _judge_row(row, facts, dates, phase, move_in, owner_entry)
        except Exception as exc:  # noqa: BLE001
            logger.error("recheck change failed: %s", type(exc).__name__)
            judged = ("unknown", NOTE_FAILED)
        if judged is not None:
            found.append((judged, row))
    found.sort(key=lambda item: (_STATUS_LEVEL_ORDER[item[0][0]], item[1].section != "gapgu", item[1].index))
    return [_change(row, level, note) for (level, note), row in found]


# ---------------------------------------------------------------------------
# 특약 점검
# ---------------------------------------------------------------------------

# 담보 설정 금지·근저당 말소 특약의 정의는 검사(R12)·수정 전후 비교와 같은 것을 쓴다
_is_prohibition = is_prohibition_clause
_is_removal_promise = is_removal_clause


def _mortgage_setups(registry: RegistryExtract) -> list[Entry]:
    """유효 을구의 (근)저당 설정 행."""
    return [
        e
        for e in registry.eulgu
        if not e.is_cancelled
        and not is_removal_record(e)
        and any("저당" in s and "설정" in s for s in active_segments(e))
    ]


def _mortgage_groups(registry: RegistryExtract) -> list[list[Entry]]:
    """유효 을구의 (근)저당 권리 묶음 (부기 등기는 주등기와 같은 묶음)."""
    groups: dict[str, list[Entry]] = {}
    for i, e in enumerate(registry.eulgu):
        if e.is_cancelled or is_removal_record(e) or not has_word(e, ("저당",)) or has_word(e, ("질권",)):
            continue
        groups.setdefault(base_rank(e.rank) or f"#{i}", []).append(e)
    return list(groups.values())


def _amount_phrase(amount: Optional[int]) -> str:
    return f"(채권최고액 {fmt_money(amount)})" if known_amount(amount) else ""


def _group_amount(group: list[Entry]) -> Optional[int]:
    return next((m.amount for m in reversed(group) if known_amount(m.amount)), None)


def _check_prohibition(registry: RegistryExtract, contract_day: dt.date, facts: _Facts) -> tuple[str, str, str]:
    """담보 설정 금지: 계약일 뒤에 새로 설정되거나 채권최고액이 늘어난 근저당이 있으면 위반."""
    setups = _mortgage_setups(registry)
    changes = facts.changes
    after = [e for e in setups if e.received_at is not None and e.received_at > contract_day]
    raised = [c for c in changes if c.raised and c.entry.received_at is not None and c.entry.received_at > contract_day]
    if after or raised:
        notes = []
        if after:
            parts = [f"{fmt_date(e.received_at)}에 근저당권{_amount_phrase(e.amount)}" for e in after]
            notes.append(f"계약 후 {', '.join(parts)}이 새로 설정됐어요.")
        for c in raised:
            new = fmt_money(c.entry.amount)
            notes.append(
                f"계약 후 {fmt_date(c.entry.received_at)}에 기존 근저당권의 채권최고액이 "
                f"{fmt_money(c.previous)}에서 {new}{josa_euro(new)} 늘었어요."
            )
        return "위반", "red", " ".join(notes)
    notes = []
    if any(e.received_at is None or e.received_at == contract_day for e in setups):
        notes.append("계약 당일 접수됐거나 접수일을 모르는 근저당이 있어 계약 후에 생긴 것인지 확인해야 해요.")
    unclear_changes = [
        c
        for c in changes
        if (c.raised is not False and (c.entry.received_at is None or c.entry.received_at >= contract_day))
    ]
    if unclear_changes:
        notes.append("계약 후 바뀐 근저당이 있는데 채권최고액이 늘었는지 확인해야 해요.")
    if notes:
        return "확인 필요", "unknown", " ".join(notes)
    return "이행", "green", "계약 후 새로 설정된 근저당이 없어요."


def _check_removal(registry: RegistryExtract, contract_day: dt.date, phase: str) -> tuple[str, str, str]:
    """근저당 말소: 지금 남아 있는 근저당이 있으면 미이행 (계약 후 새로 설정된 것도 남아 있으면 알린다)."""
    old, new, unclear = [], [], []
    for group in _mortgage_groups(registry):
        started = group[0].received_at
        if started is None or started == contract_day:
            unclear.append(group)
        elif started < contract_day:
            old.append(group)
        else:
            new.append(group)
    if old or new:
        old_what = ", ".join(f"근저당권{_amount_phrase(_group_amount(g))}" for g in old)
        new_what = ", ".join(f"근저당권{_amount_phrase(_group_amount(g))}" for g in new)
        if phase == PHASE_BEFORE:
            notes = ["잔금일까지 말소해야 해요."]
            if old:
                notes.append(f"계약 전부터 있던 {old_what}이 아직 남아 있어요.")
            if new:
                notes.append(f"계약 후 설정된 {new_what}{'도' if old else '이'} 남아 있어요.")
            return "미이행", "yellow", " ".join(notes)
        when = "잔금일인데" if phase == PHASE_BALANCE_DAY else "잔금일이 지났는데"
        if not old:
            return "미이행", "red", f"{when} 계약 후 설정된 {new_what}이 말소되지 않았어요."
        note = f"{when} 계약 전부터 있던 {old_what}이 아직 말소되지 않았어요."
        if new:
            note += f" 계약 후 설정된 {new_what}도 남아 있어요."
        return "미이행", "red", note
    if unclear:
        return "확인 필요", "unknown", "계약 당일 접수됐거나 접수일을 모르는 근저당이 있어 말소 대상인지 확인해야 해요."
    return "이행", "green", "남아 있는 근저당이 없어요."


_STATUS_ORDER = {"위반": 0, "미이행": 1, "확인 필요": 2, "이행": 3}


def check_terms(
    contract: ContractExtract,
    registry: RegistryExtract,
    contract_day: dt.date,
    phase: str,
    blocked: bool = False,
    facts: Optional[_Facts] = None,
) -> list[tuple[TermCheck, list[str]]]:
    """계약서 특약 중 보증금을 지키는 특약(담보 설정 금지·근저당 말소)의 이행 여부와 어겨진 특약 종류.

    어겨진 것: 담보 설정 금지는 위반, 근저당 말소는 잔금일이 됐는데도 미이행(🔴)인 경우.
    blocked: 올린 등기부로 계약 후 변화를 볼 수 없으면 "이행"이라고 하지 않고 "확인 필요"로 둔다.
    판정은 특약 종류마다 한 번만 하고 같은 종류의 특약에 다시 쓴다.
    """
    judged: dict[str, tuple[str, str, str]] = {}

    def judge(kind: str) -> tuple[str, str, str, str]:
        if kind not in judged:
            nonlocal facts
            if facts is None:
                facts = registry_facts(registry)
            if kind == KIND_PROHIBITION:
                judged[kind] = _check_prohibition(registry, contract_day, facts)
            else:
                judged[kind] = _check_removal(registry, contract_day, phase)
        return (*judged[kind], kind)

    checks = []
    for term in (t.strip() for t in contract.special_terms if t and t.strip()):
        prohibition, removal = _is_prohibition(term), _is_removal_promise(term)
        if not (prohibition or removal):
            continue
        try:
            results = []
            if prohibition:
                results.append(judge(KIND_PROHIBITION))
            if removal:
                results.append(judge(KIND_REMOVAL))
            broken = [r[3] for r in results if r[0] == "위반" or (r[0] == "미이행" and r[1] == "red")]
            results.sort(key=lambda r: (_STATUS_ORDER[r[0]], _STATUS_LEVEL_ORDER[r[1]]))
            status, level = results[0][0], results[0][1]
            note = " ".join(r[2] for r in results if r[0] != "이행") or results[0][2]
            if blocked and status == "이행":
                status, level, note = "확인 필요", "unknown", NOTE_TERM_BLOCKED
        except Exception as exc:  # noqa: BLE001
            logger.error("recheck term failed: %s", type(exc).__name__)
            status, level, note, broken = "확인 필요", "unknown", NOTE_FAILED, []
        checks.append((TermCheck(term=mask_id_numbers(term), status=status, level=level, note=note), broken))
    return checks


# ---------------------------------------------------------------------------
# 지금 소유자·신탁·주소 (계약 전부터 있던 문제도 본다)와 확인 미완료 이유
# ---------------------------------------------------------------------------


@dataclass
class _Blocker:
    reason: str
    action: str
    registry: bool  # 등기부로 계약 후 변화를 볼 수 없는 경우 (특약 이행도 판단하지 않는다)


@dataclass
class _Standing:
    reds: list[tuple[str, str]] = field(default_factory=list)  # (설명 문장, 할 일)
    blockers: list[_Blocker] = field(default_factory=list)


def _check_context(req: RecheckRequest, today: dt.date) -> Ctx:
    """검사 규칙(R1·R2·R11)을 재확인에도 쓰기 위한 입력 (입력 검증은 이미 끝났다)."""
    check = CheckRequest.model_construct(
        registry=req.registry,
        contract=req.contract,
        manual=ManualInput(),
        building=None,
        market=None,
        today=today,
        mode=req.mode,
    )
    return make_context(check, today)


def _viewed_blocker(
    registry: RegistryExtract,
    req: RecheckRequest,
    dates: _Dates,
    phase: str,
    today: dt.date,
    balance: Optional[dt.date],
    move_in: Optional[dt.date],
) -> Optional[_Blocker]:
    """등기부를 뗀 날이 단계에 맞는지.

    잔금 전: 계약일 뒤. 잔금 당일: 잔금일 당일. 입주 후: 지난 잔금일·입주일 중 늦은 날의 다음 날 이후
    (그날 접수된 권리가 세입자보다 앞서므로 그날까지 다 나온 등기부여야 한다).
    """
    action = ACTION_NEW_REGISTRY_AFTER if phase == PHASE_AFTER else ACTION_NEW_REGISTRY
    if registry.viewed_at is None:
        return _Blocker(REASON_NO_VIEWED_AT, action, registry=True)
    viewed = to_kst(registry.viewed_at).date()
    if phase == PHASE_BALANCE_DAY and balance is not None and viewed < balance:
        reason = REASON_NOT_BALANCE_DAY.format(viewed=fmt_date(viewed), ref=fmt_date(balance))
        return _Blocker(reason, ACTION_BALANCE_DAY_REGISTRY, registry=True)
    if phase == PHASE_AFTER:
        past = [d for d in (balance, move_in) if d is not None and d < today]
        if past and viewed <= max(past):
            key = max(past)
            label = "입주일" if key == move_in else "잔금일"
            template = REASON_MOVE_IN_SAME_DAY if viewed == key else REASON_NOT_AFTER_MOVE_IN
            reason = template.format(viewed=fmt_date(viewed), label=label, ref=fmt_date(key))
            return _Blocker(reason, ACTION_NEW_REGISTRY_AFTER, registry=True)
    if viewed > dates.contract:
        return None
    label = "계약일" if req.contract.contract_date is not None else "계약 때 본 등기부 열람일"
    reason = REASON_STALE.format(viewed=fmt_date(viewed), label=label, ref=fmt_date(dates.contract))
    return _Blocker(reason, action, registry=True)


def standing_checks(
    req: RecheckRequest,
    today: dt.date,
    dates: Optional[_Dates],
    phase: str,
    owner_entry: Optional[Entry],
    balance: Optional[dt.date] = None,
    move_in: Optional[dt.date] = None,
) -> _Standing:
    """계약서와 지금 등기부를 맞춰 본다: 소유자(R1)·신탁(R2)·주소(R11), 그리고 등기부를 믿을 수 있는지."""
    out = _Standing()
    registry = req.registry
    action = ACTION_NEW_REGISTRY_AFTER if phase == PHASE_AFTER else ACTION_NEW_REGISTRY
    ctx = _check_context(req, today)
    if not ctx.gapgu:
        out.blockers.append(_Blocker(REASON_NO_GAPGU, action, registry=True))
    parts = content.unreadable_parts(registry.unreadable)
    if parts:
        reason = REASON_UNREADABLE.format(parts=content.unreadable_phrase(parts))
        out.blockers.append(_Blocker(reason, action, registry=True))
    if dates is not None:
        blocker = _viewed_blocker(registry, req, dates, phase, today, balance, move_in)
        if blocker is not None:
            out.blockers.append(blocker)

    r1, r2, r11 = (run_rule(rid, fn, ctx) for rid, fn in (("R1", rule_r1), ("R2", rule_r2), ("R11", rule_r11)))
    if r1.level == "red" and owner_entry is None:  # 계약 후 바뀐 소유자는 새 권리 표에서 알린다
        out.reds.append((r1.summary, ACTION_OWNER))
    elif r1.level == "unknown" and ctx.gapgu:
        out.blockers.append(_Blocker(REASON_LANDLORD, ACTION_LANDLORD, registry=False))
    if r2.level == "red":
        out.reds.append((r2.summary, ACTION_TRUST))
    elif r2.level == "unknown" and ctx.gapgu:
        out.blockers.append(_Blocker(REASON_TRUST_UNKNOWN, ACTION_TRUST_UNKNOWN, registry=False))
    if r11.level == "red":
        out.reds.append((r11.summary, ACTION_UNIT))
    elif r11.level == "yellow":
        out.blockers.append(_Blocker(REASON_ADDRESS, ACTION_ADDRESS, registry=True))
    elif r11.level == "unknown":
        out.blockers.append(_Blocker(REASON_ADDRESS_UNKNOWN, ACTION_ADDRESS, registry=True))
    return out


# ---------------------------------------------------------------------------
# 종합 판정·할 일
# ---------------------------------------------------------------------------


def _red_overall(
    phase: str, changes: list[RecheckChange], terms: list[TermCheck], standing: _Standing, dates: Optional[_Dates], note
) -> Optional[Overall]:
    red_changes = [c for c in changes if c.level == "red"]
    red_terms = sum(1 for t in terms if t.level == "red")
    if not (red_changes or red_terms or standing.reds):
        return None
    before_contract = [
        c for c in red_changes if dates is not None and c.received_at is not None and c.received_at < dates.contract
    ]
    after_contract = len(red_changes) - len(before_contract)
    parts = []
    if after_contract:
        parts.append(f"계약 후 새로 생긴 권리 {after_contract}건")
    if before_contract:
        parts.append(f"계약 때 본 등기부 뒤에 생긴 권리 {len(before_contract)}건")
    if red_terms:
        parts.append(f"지켜지지 않은 특약 {red_terms}건")
    sentences = [f"{', '.join(parts)}이 있어요."] if parts else []
    sentences += [text for text, _ in standing.reds]
    if phase == PHASE_AFTER:
        title = TITLE_PROTECT_DEPOSIT
        tail = "내 보증금보다 먼저 돌려받는 권리일 수 있어요." if parts else "대한법률구조공단(국번 없이 132) 등 전문가와 상의하세요."
    else:
        title, tail = TITLE_HOLD_BALANCE, "해결되기 전에는 잔금을 미루는 걸 권해요."
    return Overall(level="red", title=title, message=" ".join(sentences + [tail]), unknown_note=note)


def _overall(
    phase: str,
    changes: list[RecheckChange],
    terms: list[TermCheck],
    dates: Optional[_Dates],
    standing: _Standing,
) -> Overall:
    levels = [c.level for c in changes] + [t.level for t in terms]
    unknown = levels.count("unknown") + len(standing.blockers)
    note = UNKNOWN_NOTE.format(n=unknown) if unknown else None
    red = _red_overall(phase, changes, terms, standing, dates, note)
    if red is not None:
        return red
    if dates is None:
        return Overall(
            level="yellow",
            title=TITLE_INCOMPLETE,
            message="계약일을 확인하지 못해 계약 후 새로 생긴 권리를 가려내지 못했어요. 계약일을 확인한 뒤 다시 확인하세요.",
            unknown_note=note,
        )
    yellows = levels.count("yellow")
    if standing.blockers:
        sentences = [b.reason for b in standing.blockers]
        if yellows:
            sentences.append(f"그 밖에 확인할 것이 {yellows}건 있어요.")
        sentences.append(standing.blockers[0].action)
        return Overall(level="yellow", title=TITLE_INCOMPLETE, message=" ".join(sentences), unknown_note=note)
    if yellows:
        return Overall(
            level="yellow", title=TITLE_CHECK_MORE, message=f"계약 전후로 확인할 것이 {yellows}건 있어요.", unknown_note=note
        )
    unread = sum(1 for c in changes if c.level == "unknown")
    if unread:
        return Overall(
            level="yellow",
            title=TITLE_INCOMPLETE,
            message=f"새로 생긴 권리는 찾지 못했지만, 접수일을 읽지 못한 항목 {unread}건을 확인하지 못했어요. "
            "등기부 원문에서 날짜를 확인하세요.",
            unknown_note=note,
        )
    if unknown:  # 특약 점검만 확인하지 못한 경우
        return Overall(
            level="yellow",
            title=TITLE_INCOMPLETE,
            message=f"새로 생긴 권리는 찾지 못했지만, 확인하지 못한 항목 {unknown}건이 있어요. 등기부 원문을 확인하세요.",
            unknown_note=note,
        )
    return Overall(
        level="green",
        title=TITLE_NOTHING_NEW,
        message="계약일 이후 새로 접수된 권리를 찾지 못했어요. 안전을 보장하는 것은 아니니 아래 할 일은 꼭 챙기세요.",
        unknown_note=note,
    )


def _actions(
    phase: str,
    changes: list[RecheckChange],
    terms: list[TermCheck],
    broken_kinds: list[list[str]],
    dates: Optional[_Dates],
    standing: _Standing,
) -> list[str]:
    actions: list[str] = []

    def add(action: str) -> None:
        if action not in actions:
            actions.append(action)

    if dates is None:
        add(ACTION_NO_BASELINE)
    new_rights = any(c.level in ("red", "yellow") for c in changes)
    term_problems = [t for t in terms if t.status in ("위반", "미이행")]
    if phase != PHASE_AFTER and (new_rights or term_problems):
        add(ACTION_HOLD_BALANCE)
    for _, action in standing.reds:
        add(action)
    if standing.reds and phase != PHASE_AFTER and ACTION_HOLD_BALANCE not in actions:
        add(ACTION_HOLD_STANDING)
    for kinds in broken_kinds:  # 특약 원문은 2절에 있으므로 종류만 쓴다
        if kinds:
            add(ACTION_TERM_BROKEN.format(kind=", ".join(kinds)))
    if phase == PHASE_AFTER and (new_rights or standing.reds):
        add(ACTION_AFTER_MOVE_IN)
    for blocker in standing.blockers:
        add(blocker.action)
    if not actions:
        add(ACTION_ALL_CLEAR_AFTER if phase == PHASE_AFTER else ACTION_ALL_CLEAR)
    if any(c.level == "unknown" for c in changes):
        add(ACTION_UNREAD_DATES)
    return actions


def _masked(overall: Overall) -> Overall:
    return overall.model_copy(update={"message": mask_id_numbers(overall.message)})


def _address(req: RecheckRequest) -> Optional[str]:
    text = contract_address_text(req.contract) or registry_address_text(req.registry)
    return mask_id_numbers(text) if text else None


def build_recheck(req: RecheckRequest) -> RecheckReport:
    """계약서와 오늘 뗀 등기부로 계약 후 새로 생긴 권리와 특약 이행 여부를 확인한다."""
    today = req.today or today_kst()
    c = req.contract
    balance = c.balance_date or c.move_in_date
    move_in = c.move_in_date or c.balance_date
    phase = phase_of(today, balance)
    baseline = baseline_date(req)
    dates = _Dates(baseline=baseline, contract=c.contract_date or baseline) if baseline is not None else None
    changes: list[RecheckChange] = []
    checked: list[tuple[TermCheck, list[str]]] = []
    owner_entry = None
    try:
        facts = registry_facts(req.registry)
    except Exception as exc:  # noqa: BLE001
        logger.error("recheck facts failed: %s", type(exc).__name__)
        facts = _Facts(mains={}, changes=[], raised={})
    if dates is not None:
        try:
            owner_entry = _owner_changed(req, dates.baseline)
        except Exception as exc:  # noqa: BLE001
            logger.error("recheck owner failed: %s", type(exc).__name__)
        changes = find_changes(req, dates, phase, move_in, owner_entry, facts)
    standing = standing_checks(req, today, dates, phase, owner_entry, balance, move_in)
    if dates is not None:
        blocked = any(b.registry for b in standing.blockers)
        checked = check_terms(c, req.registry, dates.contract, phase, blocked, facts)
    terms = [check for check, _ in checked]
    broken_kinds = [kinds for _, kinds in checked]
    return RecheckReport(
        mode=req.mode,
        generated_at=now_kst(),
        today=today,
        phase=phase,
        baseline_date=baseline,
        contract_date=c.contract_date,
        balance_date=c.balance_date,
        move_in_date=move_in,
        address=_address(req),
        overall=_masked(_overall(phase, changes, terms, dates, standing)),
        changes=changes,
        term_checks=terms,
        actions=[mask_id_numbers(a) for a in _actions(phase, changes, terms, broken_kinds, dates, standing)],
        disclaimer=content.DISCLAIMER,
    )
