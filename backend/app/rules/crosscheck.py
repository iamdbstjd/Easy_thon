"""계약서·등기부 대조표와 계약서 수정 요청서.

주소로 집만 진단하는 서비스와 달리, 사용자가 사인할 계약서를 등기부와 나란히 놓고 대조한다.
- 대조표 각 행의 등급은 해당 규칙의 등급을 그대로 쓴다 (값은 규칙과 같은 함수로 구한다).
- 화면에 나가는 값에는 주민등록번호 형식을 넣지 않는다.
"""

from __future__ import annotations

import logging
from fractions import Fraction
from typing import Callable, Mapping, Optional

from app.schemas import Amendment, AmendmentFix, ComparisonRow

from . import content
from .common import compact, fmt_date, fmt_money, mask_id_numbers, percent_floor
from .engine import (
    HO_MISSING,
    Ctx,
    contract_address_text,
    current_ownership,
    deposit_of,
    has_trust,
    landlord_of,
    market_of,
    message_address,
    protective_terms,
    registry_address_text,
    senior_claims,
    unit_facts,
    unit_mismatch,
)

logger = logging.getLogger(__name__)

NOT_IN_CONTRACT = "계약서에 없음"
NOT_CHECKED = "확인 못 함"
MANUAL_MARK = " (직접 입력)"
NO_VALUE = "—"

# 값을 만들다 실패했을 때 등급만으로 쓰는 결과
_FALLBACK_NOTE = {"red": "확인 필요", "yellow": "확인 필요", "green": "해당 없음", "unknown": NOT_CHECKED}

Cells = tuple[Optional[str], str, str]  # (계약서 쪽 값, 등기부·시세 쪽 값, 결과). 계약서 쪽이 None이면 화면에 "—"


def _missing_contract(ctx: Ctx) -> Optional[str]:
    """계약서에 값이 없을 때: 계약서가 있으면 "계약서에 없음", 계약서도 직접 입력도 없으면 None."""
    return NOT_IN_CONTRACT if ctx.contract is not None else None


def _owners(ctx: Ctx) -> Optional[str]:
    own = current_ownership(ctx.gapgu) if ctx.gapgu else None
    return ", ".join(own.owners) if own and own.owners else None


# ---------------------------------------------------------------------------
# 대조표 (5행, 고정 순서)
# ---------------------------------------------------------------------------


def _landlord_row(ctx: Ctx, level: str) -> Cells:
    landlord = landlord_of(ctx)
    if landlord is None:
        contract = _missing_contract(ctx)
    else:
        contract = ", ".join(landlord.names) + (MANUAL_MARK if landlord.manual else "")
    note = {"red": "불일치", "yellow": "공동소유", "green": "일치"}.get(level, NOT_CHECKED)
    return contract, _owners(ctx) or NOT_CHECKED, note


def _address_row(ctx: Ctx, level: str) -> Cells:
    c = ctx.contract
    contract = (contract_address_text(c) if c is not None else None) or _missing_contract(ctx)
    registry = registry_address_text(ctx.reg) or NOT_CHECKED
    if level == "red":
        note = unit_mismatch(unit_facts(ctx)) or "호수 다름"
    else:
        note = {"yellow": "주소 확인 필요", "green": "일치"}.get(level, NOT_CHECKED)
    return contract, registry, note


def _deposit_row(ctx: Ctx, level: str) -> Cells:
    deposit = deposit_of(ctx)
    if deposit is None:
        contract = _missing_contract(ctx)
    else:
        contract = fmt_money(deposit.amount) + (MANUAL_MARK if deposit.evidence.doc == "manual" else "")
    market = market_of(ctx)
    parts = [f"시세 {fmt_money(market.price)} ({market.label})" if market and market.price > 0 else "시세 정보 없음"]
    claims, prior = senior_claims(ctx)
    if claims.missing:
        parts.append(f"선순위 {fmt_money(prior)} 이상" if prior > 0 else "선순위 금액 확인 못 함")
    elif prior > 0:
        parts.append(f"선순위 {fmt_money(prior)}")
    note = NOT_CHECKED
    if level != "unknown" and deposit is not None and market is not None and market.price > 0:
        note = f"{percent_floor(Fraction(prior + deposit.amount, market.price))}%"  # R5 문구의 비율과 같은 계산
    return contract, ", ".join(parts), note


def _date_row(ctx: Ctx, level: str) -> Cells:
    c = ctx.contract
    if c is not None and c.contract_date:
        contract = fmt_date(c.contract_date)
    elif ctx.manual.contract_date:
        contract = fmt_date(ctx.manual.contract_date) + MANUAL_MARK
    else:
        contract = _missing_contract(ctx)
    own = current_ownership(ctx.gapgu) if ctx.gapgu else None
    received = own.entry.received_at if own else None
    if received is None:
        return contract, NOT_CHECKED, NOT_CHECKED if level == "unknown" else _FALLBACK_NOTE[level]
    kind = "보존" if "보존" in compact(own.entry.purpose) else "이전"
    registry = f"{fmt_date(received)} 소유권 {kind}"
    if level == "yellow":
        days = (ctx.base_date - received).days
        when = f"{days}일 전" if days > 0 else ("당일" if days == 0 else f"{-days}일 뒤")
        note = f"{when} 소유자 변경"
    else:
        note = {"green": "변경 없음"}.get(level, NOT_CHECKED)
    return contract, registry, note


def _terms_row(ctx: Ctx, level: str) -> Cells:
    c = ctx.contract
    contract = None if c is None else ("보호 특약 있음" if protective_terms(c) else "보호 특약 없음")
    note = {"green": "특약 있음", "yellow": "특약 없음"}.get(level, NOT_CHECKED)
    return contract, NO_VALUE, note


ROWS: list[tuple[str, str, Callable[[Ctx, str], Cells]]] = [
    ("임대인", "R1", _landlord_row),
    ("소재지·호수", "R11", _address_row),
    ("보증금", "R5", _deposit_row),
    ("계약일", "R8", _date_row),
    ("특약", "R12", _terms_row),
]


def build_comparison(ctx: Ctx, levels: Mapping[str, str]) -> list[ComparisonRow]:
    """계약서·등기부 대조표. 한 행을 만들다 실패해도 그 행만 등급으로 채운다."""
    rows = []
    for item, rid, make in ROWS:
        level = levels.get(rid, "unknown")
        try:
            contract, registry, note = make(ctx, level)
        except Exception as exc:  # noqa: BLE001
            logger.error("comparison %s failed: %s", rid, type(exc).__name__)
            contract, registry, note = None, NO_VALUE, _FALLBACK_NOTE[level]
        rows.append(
            ComparisonRow(
                item=item,
                rule_id=rid,
                contract=mask_id_numbers(contract) if contract is not None else None,
                registry=mask_id_numbers(registry),
                level=level,
                note=note,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# 계약서 수정 요청서
# ---------------------------------------------------------------------------


def _address_fix(ctx: Ctx, level: str) -> AmendmentFix:
    c = ctx.contract
    if level == "red":
        mismatch = unit_mismatch(unit_facts(ctx))
        reason = "계약서에 호수 없음" if mismatch == HO_MISSING else f"등기부와 {mismatch or '호수 다름'}"
    else:
        reason = "등기부 주소와 다르게 적힘"
    return AmendmentFix(
        item="소재지",
        current=contract_address_text(c) or NOT_IN_CONTRACT,
        proposed=registry_address_text(ctx.reg) or "등기부에 적힌 주소와 동·호수",
        reason=reason,
    )


def _landlord_fix(ctx: Ctx, level: str) -> Optional[AmendmentFix]:
    c = ctx.contract
    owners = _owners(ctx)
    if owners is None:
        return None
    landlord = landlord_of(ctx)
    current = ", ".join(landlord.names) if landlord and not landlord.manual else NOT_IN_CONTRACT
    if level == "yellow":
        proposed, reason = f"공동 소유자({owners}) 모두의 동의서 첨부", "공동소유"
    elif has_trust(current_ownership(ctx.gapgu).entry):
        proposed = f"{owners} 명의로 계약하거나 {owners}의 임대 동의서 첨부"
        reason = "등기부상 소유자는 신탁회사"
    elif c is not None and (c.agent_name or "").strip():
        proposed, reason = f"소유자 {owners}의 위임장·인감증명서 첨부", "대리 계약"
    else:
        proposed = f"{owners} 명의로 변경 (대리 계약이면 위임장·인감증명서 첨부)"
        reason = "등기부상 소유자와 다름"
    return AmendmentFix(item="임대인", current=current, proposed=proposed, reason=reason)


def _fixes(ctx: Ctx, levels: Mapping[str, str]) -> list[AmendmentFix]:
    fixes: list[AmendmentFix] = []
    if levels.get("R11") in ("red", "yellow"):
        fixes.append(_address_fix(ctx, levels["R11"]))
    if levels.get("R1") in ("red", "yellow"):
        fix = _landlord_fix(ctx, levels["R1"])
        if fix is not None:
            fixes.append(fix)
    return [
        f.model_copy(update={k: mask_id_numbers(getattr(f, k)) for k in ("current", "proposed", "reason")})
        for f in fixes
    ]


def build_amendment(
    ctx: Ctx, levels: Mapping[str, str], terms: list[str], documents: list[str]
) -> Amendment:
    """계약서 수정 요청서. 계약서가 없으면 고칠 곳 없이 "계약 전 요청서"로 만든다."""
    has_contract = ctx.contract is not None
    title = content.AMENDMENT_TITLE if has_contract else content.AMENDMENT_TITLE_NO_CONTRACT
    fixes: list[AmendmentFix] = []
    if has_contract:
        try:
            fixes = _fixes(ctx, levels)
        except Exception as exc:  # noqa: BLE001
            logger.error("amendment fixes failed: %s", type(exc).__name__)
    text = content.build_amendment_text(title, message_address(ctx), ctx.today, fixes, terms, documents)
    return Amendment(
        title=title,
        fixes=fixes,
        terms=list(terms),
        documents=list(documents),
        text=mask_id_numbers(text),
    )
