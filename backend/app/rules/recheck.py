"""계약 후 재확인 (잔금 전·잔금 당일·입주 후).

계약서와 오늘 뗀 등기부만으로, 계약일(비교 기준일) 이후 새로 생긴 권리와 계약서 특약의 이행 여부를 본다.
계약 당시 등기부는 받지도 저장하지도 않는다.
- 같은 입력이면 generated_at 말고는 같은 결과가 나온다.
- 한 항목을 판단하다 실패하면 그 항목만 ⚪로 둔다.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Optional

from app.schemas import (
    ContractExtract,
    Entry,
    Overall,
    RecheckChange,
    RecheckReport,
    RecheckRequest,
    RegistryExtract,
    TermCheck,
)

from . import content
from .common import compact, fmt_date, fmt_money, mask_id_numbers, normalize_name, now_kst, to_kst, today_kst
from .engine import (
    active_segments,
    base_rank,
    contract_address_text,
    current_ownership,
    entry_evidence,
    has_word,
    holder_names,
    is_removal_record,
    registry_address_text,
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
NOTE_MOVE_IN_DAY = "전입신고와 같은 날 등기돼 세입자보다 앞서요"
NOTE_OWNER_CHANGED = "계약 후 집주인이 바뀌었어요"
NOTE_NO_DATE = "접수일을 읽지 못해 계약 후에 생긴 것인지 알 수 없어요"
NOTE_FAILED = "이 항목을 확인하는 중 문제가 생겼어요"

# 할 일
ACTION_HOLD_BALANCE = "잔금을 보내기 전에 임대인에게 말소를 요구하고, 해결되기 전에는 잔금을 미루세요."
ACTION_TERM_BROKEN = "계약서 특약({kind})에 어긋나요. 공인중개사·대한법률구조공단(국번 없이 132)과 상의해 대응하세요."
KIND_PROHIBITION, KIND_REMOVAL = "담보 설정 금지", "근저당 말소"
ACTION_AFTER_MOVE_IN = "전입신고·확정일자를 받았는지 확인하고, 대한법률구조공단이나 전세피해지원센터에 상담하세요."
ACTION_ALL_CLEAR = "잔금 보내기 직전에 한 번 더 떼어 보고, 입주 당일 전입신고와 확정일자를 받으세요."
ACTION_ALL_CLEAR_AFTER = "전입신고 다음 날에도 한 번 더 확인하세요."
ACTION_UNREAD_DATES = "접수일을 읽지 못한 항목은 등기부 원문에서 날짜를 직접 확인하세요."
ACTION_NO_BASELINE = "계약서의 계약일을 확인한 뒤 다시 확인하세요."

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


def phase_of(today: dt.date, balance: Optional[dt.date]) -> str:
    """잔금일과 오늘을 비교한 단계. 잔금일을 모르면 잔금 전으로 보고 가장 조심스럽게 안내한다."""
    if balance is None or today < balance:
        return PHASE_BEFORE
    return PHASE_BALANCE_DAY if today == balance else PHASE_AFTER


# ---------------------------------------------------------------------------
# 새로 생긴 권리
# ---------------------------------------------------------------------------


@dataclass
class _Row:
    section: str
    index: int
    entry: Entry


def _rows(registry: RegistryExtract) -> list[_Row]:
    """유효 항목 (말소 기록 행과, 같은 순위번호를 나눠 적은 권리자 없는 줄은 뺀다)."""
    rows = []
    for section, entries in (("gapgu", registry.gapgu), ("eulgu", registry.eulgu)):
        previous_rank = None
        for i, e in enumerate(entries):
            if e.is_cancelled or is_removal_record(e):
                continue
            rank = compact(e.rank)
            if rank and rank == previous_rank and not holder_names(e.holders):
                continue  # 같은 순위번호를 나눠 적은 줄 (예: "3 소유권이전 … 수탁자" 다음의 "3 신탁")
            previous_rank = rank
            rows.append(_Row(section, i, e))
    return rows


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


def _judge_row(row: _Row, baseline: dt.date, phase: str, move_in: Optional[dt.date], owner_entry) -> Optional[tuple]:
    """(등급, 결과) 또는 새로 생긴 권리가 아니면 None."""
    received = row.entry.received_at
    if received is None:
        return "unknown", NOTE_NO_DATE
    if received < baseline:
        return None
    if row.entry is owner_entry:
        return "red", NOTE_OWNER_CHANGED
    if phase == PHASE_AFTER and move_in is not None and received == move_in:
        return "red", NOTE_MOVE_IN_DAY
    if received == baseline:
        return "yellow", NOTE_SAME_DAY
    return "red", NOTE_NEW


def find_changes(req: RecheckRequest, baseline: dt.date, phase: str, move_in: Optional[dt.date]) -> list[RecheckChange]:
    try:
        owner_entry = _owner_changed(req, baseline)
    except Exception as exc:  # noqa: BLE001
        logger.error("recheck owner failed: %s", type(exc).__name__)
        owner_entry = None
    found = []
    for row in _rows(req.registry):
        try:
            judged = _judge_row(row, baseline, phase, move_in, owner_entry)
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

# 담보 설정을 막는 표현 (띄어쓰기 무시)
_PROHIBITION_WORDS = ("설정하지", "설정을하지", "설정금지", "설정을금지", "설정할수없", "설정해서는", "추가대출", "대출을받지")


def _is_prohibition(term: str) -> bool:
    t = compact(term)
    return any(w in t for w in _PROHIBITION_WORDS) or (("담보" in t or "저당" in t) and "말소" not in t)


def _is_removal_promise(term: str) -> bool:
    return "말소" in compact(term)


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
    return f"(채권최고액 {fmt_money(amount)})" if amount is not None else ""


def _check_prohibition(registry: RegistryExtract, baseline: dt.date) -> tuple[str, str, str]:
    setups = _mortgage_setups(registry)
    broken = [e for e in setups if e.received_at is not None and e.received_at > baseline]
    if broken:
        parts = [f"{fmt_date(e.received_at)}에 근저당권{_amount_phrase(e.amount)}" for e in broken]
        return "위반", "red", f"계약 후 {', '.join(parts)}이 새로 설정됐어요."
    unclear = [e for e in setups if e.received_at is None or e.received_at == baseline]
    if unclear:
        return "확인 필요", "unknown", "계약 당일 접수됐거나 접수일을 모르는 근저당이 있어 계약 후에 생긴 것인지 확인해야 해요."
    return "이행", "green", "계약 후 새로 설정된 근저당이 없어요."


def _check_removal(registry: RegistryExtract, baseline: dt.date, phase: str) -> tuple[str, str, str]:
    old, unclear = [], []
    for group in _mortgage_groups(registry):
        started = group[0].received_at
        if started is None or started == baseline:
            unclear.append(group)
        elif started < baseline:
            old.append(group)
    if old:
        amounts = [next((m.amount for m in reversed(g) if m.amount is not None), None) for g in old]
        what = ", ".join(f"근저당권{_amount_phrase(a)}" for a in amounts)
        if phase == PHASE_BEFORE:
            return "미이행", "yellow", f"잔금일까지 말소해야 해요. 계약 전부터 있던 {what}이 아직 남아 있어요."
        when = "잔금일인데" if phase == PHASE_BALANCE_DAY else "잔금일이 지났는데"
        return "미이행", "red", f"{when} 계약 전부터 있던 {what}이 아직 말소되지 않았어요."
    if unclear:
        return "확인 필요", "unknown", "계약 당일 접수됐거나 접수일을 모르는 근저당이 있어 말소 대상인지 확인해야 해요."
    return "이행", "green", "남아 있는 근저당이 없어요."


_STATUS_ORDER = {"위반": 0, "미이행": 1, "확인 필요": 2, "이행": 3}


def check_terms(
    contract: ContractExtract, registry: RegistryExtract, baseline: dt.date, phase: str
) -> list[tuple[TermCheck, list[str]]]:
    """계약서 특약 중 보증금을 지키는 특약(담보 설정 금지·근저당 말소)의 이행 여부와 어겨진 특약 종류.

    어겨진 것: 담보 설정 금지는 위반, 근저당 말소는 잔금일이 됐는데도 미이행(🔴)인 경우.
    """
    checks = []
    for term in (t.strip() for t in contract.special_terms if t and t.strip()):
        prohibition, removal = _is_prohibition(term), _is_removal_promise(term)
        if not (prohibition or removal):
            continue
        try:
            results = []
            if prohibition:
                results.append((*_check_prohibition(registry, baseline), KIND_PROHIBITION))
            if removal:
                results.append((*_check_removal(registry, baseline, phase), KIND_REMOVAL))
            broken = [r[3] for r in results if r[0] == "위반" or (r[0] == "미이행" and r[1] == "red")]
            results.sort(key=lambda r: (_STATUS_ORDER[r[0]], _STATUS_LEVEL_ORDER[r[1]]))
            status, level = results[0][0], results[0][1]
            note = " ".join(r[2] for r in results if r[0] != "이행") or results[0][2]
        except Exception as exc:  # noqa: BLE001
            logger.error("recheck term failed: %s", type(exc).__name__)
            status, level, note, broken = "확인 필요", "unknown", NOTE_FAILED, []
        checks.append((TermCheck(term=mask_id_numbers(term), status=status, level=level, note=note), broken))
    return checks


# ---------------------------------------------------------------------------
# 종합 판정·할 일
# ---------------------------------------------------------------------------


def _overall(phase: str, changes: list[RecheckChange], terms: list[TermCheck], baseline: Optional[dt.date]) -> Overall:
    levels = [c.level for c in changes] + [t.level for t in terms]
    unknown = levels.count("unknown")
    note = UNKNOWN_NOTE.format(n=unknown) if unknown else None
    if baseline is None:
        return Overall(
            level="yellow",
            title=TITLE_INCOMPLETE,
            message="계약일을 확인하지 못해 계약 후 새로 생긴 권리를 가려내지 못했어요. 계약일을 확인한 뒤 다시 확인하세요.",
            unknown_note=note,
        )
    red_changes = sum(1 for c in changes if c.level == "red")
    red_terms = sum(1 for t in terms if t.level == "red")
    if red_changes or red_terms:
        parts = []
        if red_changes:
            parts.append(f"계약 후 새로 생긴 권리 {red_changes}건")
        if red_terms:
            parts.append(f"지켜지지 않은 특약 {red_terms}건")
        found = f"{', '.join(parts)}이 있어요."
        if phase == PHASE_AFTER:
            return Overall(
                level="red",
                title=TITLE_PROTECT_DEPOSIT,
                message=f"{found} 내 보증금보다 먼저 돌려받는 권리일 수 있어요.",
                unknown_note=note,
            )
        return Overall(
            level="red",
            title=TITLE_HOLD_BALANCE,
            message=f"{found} 해결되기 전에는 잔금을 미루는 걸 권해요.",
            unknown_note=note,
        )
    yellows = levels.count("yellow")
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
    baseline: Optional[dt.date],
) -> list[str]:
    if baseline is None:
        return [ACTION_NO_BASELINE]
    new_rights = any(c.level in ("red", "yellow") for c in changes)
    term_problems = [t for t in terms if t.status in ("위반", "미이행")]
    actions = []
    if phase != PHASE_AFTER and (new_rights or term_problems):
        actions.append(ACTION_HOLD_BALANCE)
    for kinds in broken_kinds:  # 특약 원문은 2절에 있으므로 종류만 쓴다
        action = ACTION_TERM_BROKEN.format(kind=", ".join(kinds))
        if kinds and action not in actions:
            actions.append(action)
    if phase == PHASE_AFTER and new_rights:
        actions.append(ACTION_AFTER_MOVE_IN)
    if not actions:
        actions.append(ACTION_ALL_CLEAR_AFTER if phase == PHASE_AFTER else ACTION_ALL_CLEAR)
    if any(c.level == "unknown" for c in changes):
        actions.append(ACTION_UNREAD_DATES)
    return actions


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
    changes: list[RecheckChange] = []
    checked: list[tuple[TermCheck, list[str]]] = []
    if baseline is not None:
        changes = find_changes(req, baseline, phase, move_in)
        checked = check_terms(c, req.registry, baseline, phase)
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
        overall=_overall(phase, changes, terms, baseline),
        changes=changes,
        term_checks=terms,
        actions=[mask_id_numbers(a) for a in _actions(phase, changes, terms, broken_kinds, baseline)],
        disclaimer=content.DISCLAIMER,
    )
