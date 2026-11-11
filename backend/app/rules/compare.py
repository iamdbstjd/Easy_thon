"""계약서 변경 추적: 수정 전·후 비교.

같은 등기부·직접 입력·공공 데이터로 수정 전 계약서와 수정 후 계약서를 각각 검사하고,
요청서가 얼마나 반영됐는지, 위험 신호가 어떻게 바뀌었는지, 계약 내용이 무엇이 바뀌었는지 보여 준다.
- 규칙으로 확인할 수 있는 것만 비교한다. 조항의 유불리를 판단하지 않는다.
- 남은 위험은 그대로 보여 주고, 효과를 부풀리지 않는다.
- 수정 전 결과·계약서를 저장하지 않는다.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.schemas import (
    RULE_NAMES,
    CheckRequest,
    CompareReport,
    CompareRequest,
    ContractChange,
    ContractExtract,
    FulfillmentRate,
    Report,
    RequestFulfillment,
    RuleDelta,
)

from . import content
from .common import (
    compact,
    display_name,
    fmt_date,
    fmt_money,
    mask_id_numbers,
    normalize_name,
    now_kst,
    today_kst,
    unit_label,
    unit_text,
)
from .engine import contract_address_text, registry_address_text
from .report import build_report

logger = logging.getLogger(__name__)

# 고칠 곳 → 규칙
FIX_RULES = {"임대인": "R1", "소재지": "R11"}
_FIX_DONE = {"R1": "수정 후 임대인이 등기부상 소유자와 같아요", "R11": "수정 후 소재지·호수가 등기부와 같아요"}
_FIX_NOT_DONE = {
    ("R1", "red"): "수정 후에도 임대인이 등기부상 소유자와 달라요",
    ("R1", "yellow"): "수정 후에도 공동 소유자 모두의 동의를 계약서로 확인할 수 없어요",
    ("R11", "red"): "수정 후에도 호수가 등기부와 달라요",
    ("R11", "yellow"): "수정 후에도 주소가 등기부와 같은지 확인이 필요해요",
}
NOTE_FIX_UNKNOWN = "수정 후 결과를 확인하지 못했어요"
NOTE_TERM_DONE = "수정 후 계약서 특약에 있어요"
NOTE_TERM_MISSING = "수정 후 계약서 특약에 없어요"
NOTE_TERM_ALREADY = "수정 전 계약서에도 있던 특약이라 새로 반영된 것은 아니에요"
NOTE_DOCUMENT = "계약서로는 확인할 수 없어요. 받았는지 직접 확인하세요."
NOTE_FAILED = "이 항목을 확인하는 중 문제가 생겼어요"

# 위험 정도 (클수록 나쁨). 🟢 쪽으로 가면 개선이다.
SEVERITY = {"green": 0, "unknown": 1, "yellow": 2, "red": 3}
_CHANGE_ORDER = {"개선": 0, "악화": 1, "그대로": 2}


# ---------------------------------------------------------------------------
# 요청서 반영
# ---------------------------------------------------------------------------


# 요청서 특약의 짧은 이름 (화면 label로도 쓴다)
KIND_NO_NEW_MORTGAGE = "담보 설정 금지"
KIND_CLEAR_MORTGAGE = "근저당 말소"
KIND_JEONSE_GUARANTEE = "반환보증 불가 시 무효"
KIND_SHOW_DOCUMENTS = "납세증명서·확정일자 제시"
KIND_TRUST_CONSENT = "신탁회사 동의서"
KIND_OTHER = "추가 특약"


def _term_kind(term: str) -> Optional[str]:
    """요청서 특약의 종류 (12.2 문안 기준)."""
    if term == content.TERM_NO_NEW_MORTGAGE:
        return KIND_NO_NEW_MORTGAGE
    if term.startswith(content.TERM_CLEAR_MORTGAGE.split("{")[0]):
        return KIND_CLEAR_MORTGAGE
    if term == content.TERM_JEONSE_GUARANTEE:
        return KIND_JEONSE_GUARANTEE
    if term == content.TERM_SHOW_DOCUMENTS:
        return KIND_SHOW_DOCUMENTS
    if term == content.TERM_TRUST_CONSENT:
        return KIND_TRUST_CONSENT
    return None


def _has_kind(clause: str, kind: Optional[str]) -> bool:
    """계약서 특약 한 문장에 그 종류의 핵심어가 있는지."""
    t = compact(clause)
    if kind == KIND_NO_NEW_MORTGAGE:  # 말소를 약속하는 문장의 "저당"은 담보 설정 금지가 아니다
        return "담보" in t or "설정하지" in t or ("저당" in t and "말소" not in t)
    keywords = {
        KIND_CLEAR_MORTGAGE: ("말소",),
        KIND_JEONSE_GUARANTEE: ("반환보증", "보증보험"),
        KIND_SHOW_DOCUMENTS: ("납세증명서", "확정일자"),
        KIND_TRUST_CONSENT: ("동의서", "수탁자"),
    }.get(kind or "", ())
    return any(w in t for w in keywords)


def _clauses(contract: Optional[ContractExtract]) -> list[str]:
    return [t.strip() for t in (contract.special_terms if contract else []) if t and t.strip()]


def _term_fulfillment(
    term: str, before: Optional[ContractExtract], after: Optional[ContractExtract]
) -> RequestFulfillment:
    kind = _term_kind(term)
    before_keys = {compact(t) for t in _clauses(before)}
    after_clauses = [t for t in _clauses(after) if _has_kind(t, kind)]
    new_clauses = [t for t in after_clauses if compact(t) not in before_keys]
    if new_clauses:
        status, note = "반영", NOTE_TERM_DONE
    elif after_clauses:  # 수정 전부터 있던 문장뿐이면 새로 반영된 것이 아니다
        status, note = "미반영", NOTE_TERM_ALREADY
    else:
        status, note = "미반영", NOTE_TERM_MISSING
    return RequestFulfillment(kind="term", item=term, label=kind or KIND_OTHER, status=status, note=note)


def _fix_fulfillment(item: str, after_levels: dict[str, str]) -> RequestFulfillment:
    rid = FIX_RULES.get(item)
    level = after_levels.get(rid or "", "unknown")
    if level == "green":
        return RequestFulfillment(kind="fix", item=item, label=item, status="반영", note=_FIX_DONE[rid])
    note = _FIX_NOT_DONE.get((rid or "", level), NOTE_FIX_UNKNOWN)
    return RequestFulfillment(kind="fix", item=item, label=item, status="미반영", note=note)


def fulfillment_of(before_report: Report, after_report: Report, before: CheckRequest, after: CheckRequest):
    """수정 전 요청서 항목별 반영 여부와 반영률 (받을 서류는 반영률에 넣지 않는다)."""
    amendment = before_report.amendment
    if amendment is None:
        return [], FulfillmentRate(done=0, total=0)
    after_levels = {r.id: r.level for r in after_report.results}
    items: list[RequestFulfillment] = []
    for fix in amendment.fixes:
        try:
            items.append(_fix_fulfillment(fix.item, after_levels))
        except Exception as exc:  # noqa: BLE001
            logger.error("compare fix failed: %s", type(exc).__name__)
            items.append(
                RequestFulfillment(kind="fix", item=fix.item, label=fix.item, status="미반영", note=NOTE_FAILED)
            )
    for term in amendment.terms:
        try:
            items.append(_term_fulfillment(term, before.contract, after.contract))
        except Exception as exc:  # noqa: BLE001
            logger.error("compare term failed: %s", type(exc).__name__)
            label = _term_kind(term) or KIND_OTHER
            items.append(RequestFulfillment(kind="term", item=term, label=label, status="미반영", note=NOTE_FAILED))
    items += [
        RequestFulfillment(kind="document", item=d, label=d, status="직접 확인", note=NOTE_DOCUMENT)
        for d in amendment.documents
    ]
    counted = [i for i in items if i.kind != "document"]
    rate = FulfillmentRate(done=sum(1 for i in counted if i.status == "반영"), total=len(counted))
    fields = ("item", "label", "note")
    masked = [i.model_copy(update={k: mask_id_numbers(getattr(i, k)) for k in fields}) for i in items]
    return masked, rate


# ---------------------------------------------------------------------------
# 위험 신호 변화
# ---------------------------------------------------------------------------


def rule_deltas(before_report: Report, after_report: Report) -> list[RuleDelta]:
    """규칙 13개의 수정 전·후 등급. 개선 → 악화 → 그대로, 같으면 규칙 번호 순서."""
    before = {r.id: r for r in before_report.results}
    after = {r.id: r for r in after_report.results}
    deltas = []
    for rid, name in RULE_NAMES.items():
        b, a = before[rid].level, after[rid].level
        if SEVERITY[a] < SEVERITY[b]:
            change = "개선"
        elif SEVERITY[a] > SEVERITY[b]:
            change = "악화"
        else:
            change = "그대로"
        title = after[rid].title if a in ("red", "yellow") else ""
        deltas.append(RuleDelta(id=rid, name=name, before=b, after=a, change=change, after_title=title))
    deltas.sort(key=lambda d: (_CHANGE_ORDER[d.change], int(d.id[1:])))
    return deltas


# ---------------------------------------------------------------------------
# 바뀐 계약 내용
# ---------------------------------------------------------------------------


def _contract_fields(c: Optional[ContractExtract]) -> list[tuple[str, Optional[str]]]:
    if c is None:
        return [(name, None) for name in ("임대인", "소재지", "동·호", "보증금", "월세", "계약일", "잔금일")]
    names = [display_name(n) for n in c.landlord_names if normalize_name(n)]
    return [
        ("임대인", ", ".join(names) or None),
        ("소재지", (c.address or "").strip() or None),
        ("동·호", unit_label(unit_text(c.unit.dong, "동"), unit_text(c.unit.ho, "호")) or None),
        ("보증금", fmt_money(c.deposit) if c.deposit is not None else None),
        ("월세", fmt_money(c.monthly_rent) if c.monthly_rent is not None else None),
        ("계약일", fmt_date(c.contract_date) if c.contract_date else None),
        ("잔금일", fmt_date(c.balance_date) if c.balance_date else None),
    ]


def contract_changes(before: Optional[ContractExtract], after: Optional[ContractExtract]) -> list[ContractChange]:
    """임대인·소재지·동호·보증금·월세·계약일·잔금일 중 바뀐 것과, 추가·삭제된 특약."""
    changes = []
    for (field, old), (_, new) in zip(_contract_fields(before), _contract_fields(after)):
        if old != new:
            changes.append(ContractChange(field=field, before=old, after=new))
    before_terms, after_terms = _clauses(before), _clauses(after)
    before_keys, after_keys = {compact(t) for t in before_terms}, {compact(t) for t in after_terms}
    changes += [ContractChange(field="특약 추가", after=t) for t in after_terms if compact(t) not in before_keys]
    changes += [ContractChange(field="특약 삭제", before=t) for t in before_terms if compact(t) not in after_keys]
    return [
        c.model_copy(update={k: mask_id_numbers(getattr(c, k)) for k in ("before", "after") if getattr(c, k)})
        for c in changes
    ]


# ---------------------------------------------------------------------------
# 비교서
# ---------------------------------------------------------------------------


def headline_of(before_report: Report, after_report: Report, rate: FulfillmentRate) -> str:
    """한 줄 요약. 수정 전·후 모두 0인 항목은 뺀다."""
    b, a = before_report.counts, after_report.counts
    parts = []
    if b.red or a.red:
        parts.append(f"위험 {b.red}건 → {a.red}건")
    if b.yellow or a.yellow:
        parts.append(f"주의 {b.yellow}건 → {a.yellow}건")
    if rate.total:
        parts.append(f"요청 {rate.total}건 중 {rate.done}건 반영")
    return ", ".join(parts) or "수정 전·후 모두 위험·주의 신호와 요청 항목이 없어요"


def _address(after: CheckRequest, before: CheckRequest) -> Optional[str]:
    for req in (after, before):
        text = (contract_address_text(req.contract) if req.contract else None) or registry_address_text(req.registry)
        if text:
            return mask_id_numbers(text)
    return None


def build_compare(req: CompareRequest) -> CompareReport:
    """수정 전·후 계약서를 같은 기준일로 검사해 비교서를 만든다."""
    today = req.today or req.before.today or today_kst()
    before = req.before.model_copy(update={"today": today, "mode": req.mode})
    after = req.after.model_copy(update={"today": today, "mode": req.mode})
    before_report, after_report = build_report(before), build_report(after)
    fulfillment, rate = fulfillment_of(before_report, after_report, before, after)
    try:
        changes = contract_changes(before.contract, after.contract)
    except Exception as exc:  # noqa: BLE001
        logger.error("compare contract changes failed: %s", type(exc).__name__)
        changes = []
    return CompareReport(
        mode=req.mode,
        generated_at=now_kst(),
        today=today,
        address=_address(after, before),
        before_overall=before_report.overall,
        after_overall=after_report.overall,
        before_counts=before_report.counts,
        after_counts=after_report.counts,
        rate=rate,
        headline=headline_of(before_report, after_report, rate),
        fulfillment=fulfillment,
        rule_deltas=rule_deltas(before_report, after_report),
        contract_changes=changes,
        disclaimer=content.DISCLAIMER,
    )
