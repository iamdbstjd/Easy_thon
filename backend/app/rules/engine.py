"""규칙 엔진: R1–R13 판정과 판정에 쓰는 값 (대조표·요청서도 같은 값을 쓴다).

- AI나 외부 API를 부르지 않는다. 같은 입력이면 generated_at 말고는 같은 결과가 나온다.
- 규칙은 서로 독립적으로 계산한다. 한 규칙이 실패해도 그 규칙만 ⚪가 된다.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Optional

from app.schemas import (
    RULE_NAMES,
    CheckRequest,
    ContractExtract,
    Entry,
    Evidence,
    ManualInput,
    RegistryExtract,
    RuleResult,
)

from . import content
from .common import (
    address_has_core,
    address_too_long,
    compact,
    display_name,
    floor_from_ho,
    fmt_date,
    fmt_money,
    fmt_period,
    is_basement_unit,
    is_floor_line,
    jibun_core,
    josa_euro,
    josa_iga,
    josa_ieyo,
    line_has_floor,
    mask_id_numbers,
    normalize_name,
    parse_floor,
    percent_floor,
    road_core,
    to_kst,
    unit_in_address,
    unit_key,
    unit_label,
    unit_text,
)

logger = logging.getLogger(__name__)

# 기준값
RATIO_DANGER = Fraction(8, 10)  # R5 🔴
RATIO_WARN = Fraction(7, 10)  # R5 🟡
RECENT_OWNERSHIP_DAYS = 90  # R8
STALE_REGISTRY_DAYS = 3  # R13

LEVEL_ORDER = {"red": 0, "yellow": 1, "unknown": 2, "green": 3}

NO_GAPGU = "등기부 갑구 항목을 확인하지 못했어요"
RULE_FAILED = "이 항목을 계산하는 중 문제가 생겼어요"


# ---------------------------------------------------------------------------
# 입력 정리
# ---------------------------------------------------------------------------


@dataclass
class Ctx:
    req: CheckRequest
    reg: RegistryExtract
    contract: Optional[ContractExtract]
    manual: ManualInput
    today: dt.date
    base_date: dt.date  # 기준일
    gapgu: list[Entry]  # 유효 항목만
    eulgu: list[Entry]
    ownership_cache: list = field(default_factory=list, repr=False)  # 현재 소유권을 한 번만 계산해 둔다


def make_context(req: CheckRequest, today: dt.date) -> Ctx:
    contract = req.contract
    base_date = (contract.contract_date if contract else None) or req.manual.contract_date or today
    return Ctx(
        req=req,
        reg=req.registry,
        contract=contract,
        manual=req.manual,
        today=today,
        base_date=base_date,
        gapgu=[e for e in req.registry.gapgu if not e.is_cancelled],
        eulgu=[e for e in req.registry.eulgu if not e.is_cancelled],
    )


# ---------------------------------------------------------------------------
# 갑구·을구 항목 해석
# ---------------------------------------------------------------------------

# 한 순위번호의 등기목적이 여러 개면 쉼표 등으로 이어 온다 ("소유권이전, 신탁").
# "소유권이전 3번신탁등기말소"처럼 붙어 와도 "N번" 앞에서 나눈다.
# "N번"은 숫자 덩어리의 첫 글자에서만 찾는다 ("123번"을 "1|2|3번"으로 쪼개지 않고, 긴 숫자열에서 느려지지 않게).
_SEGMENT_SPLIT = re.compile(r"[,，/·ㆍ]|및|(?<![\d-])(?=\d+(?:-\d+)?번)")
# 등기목적으로 읽는 최대 길이 (실제 등기목적은 수십 자 안이다)
PURPOSE_MAX_CHARS = 300


def purpose_segments(e: Entry) -> list[str]:
    purpose = (e.purpose or "")[:PURPOSE_MAX_CHARS]
    return [s for s in (compact(p) for p in _SEGMENT_SPLIT.split(purpose)) if s]


def _is_removal(segment: str) -> bool:
    """말소 기록 ("3번가압류등기말소")은 권리가 살아 있다는 뜻이 아니다."""
    return "말소" in segment and "회복" not in segment


def active_segments(e: Entry) -> list[str]:
    return [s for s in purpose_segments(e) if not _is_removal(s)]


def is_removal_record(e: Entry) -> bool:
    segs = purpose_segments(e)
    return bool(segs) and all(_is_removal(s) for s in segs)


def has_word(e: Entry, words: tuple[str, ...]) -> bool:
    return any(w in s for s in active_segments(e) for w in words)


def _entry_text(e: Entry) -> str:
    """근거 원문. 원문이 비어 있으면 항목 값으로 만든다."""
    if e.source_text and e.source_text.strip():
        return e.source_text.strip()
    parts = [
        e.rank,
        e.purpose,
        fmt_date(e.received_at) if e.received_at else "",
        e.cause or "",
        ", ".join(holder_names(e.holders)),
        fmt_money(e.amount) if e.amount is not None else "",
    ]
    return " ".join(p.strip() for p in parts if p and p.strip())


def entry_evidence(e: Entry) -> Evidence:
    return Evidence(doc="registry", page=e.page, text=_entry_text(e))


def holder_names(holders: list[str]) -> list[str]:
    return [display_name(h) for h in holders if normalize_name(h)]


# --- 현재 소유권 ---

_OWNERSHIP_WORDS = ("소유권보존", "소유권이전", "소유권일부이전")
_SHARE_SELLER = re.compile(r"(?<!\d)\d+(?:-\d+)?번(.+?)지분전부이전")


def _is_ownership_segment(seg: str) -> bool:
    if "가등기" in seg or "청구권" in seg:
        return False
    if any(w in seg for w in _OWNERSHIP_WORDS):
        return True
    if "지분" in seg and "이전" in seg:  # "2번김○○지분전부이전", "공유자전원지분전부이전"
        return True
    return seg == "신탁"  # 신탁만 따로 적혀 와도 수탁자에게 소유권이 넘어간 것이다


def _is_partial_segment(seg: str) -> bool:
    return "일부이전" in seg or ("지분" in seg and "공유자전원지분전부이전" not in seg)


@dataclass
class Ownership:
    entry: Entry  # 현재 소유권 항목 (마지막 것)
    owners: list[str]  # 현재 소유자 (화면용 이름)
    shared: bool  # 공동소유
    entries: list[Entry]  # 현재 소유자를 정한 항목들 (근거)


def current_ownership(gapgu: list[Entry]) -> Optional[Ownership]:
    """유효 갑구에서 소유권보존·이전 항목 중 마지막 것과 그 소유자.

    - 일부이전·지분이전은 앞선 소유자에 더한다 (공동소유).
    - 권리자가 비어 있는 행:
      - "신탁"만 적힌 행이나, 앞 소유권 행과 순위번호가 같은 행(예: "3 소유권이전 … 수탁자" 다음의
        "3 신탁")은 나눠 적은 줄이므로 소유자도 현재 소유권 항목도 바꾸지 않는다.
      - 순위번호가 따로 있는 이전 행이면 현재 소유자를 모른다 (이전 소유자를 쓰지 않는다 → R1 ⚪).
        뒤에 권리자가 있는 전부 이전이 오기 전까지는 모르는 상태로 둔다.
    """
    owners: list[str] = []
    keys: list[str] = []  # owners와 같은 순서의 이름 비교용 값 (항목마다 다시 정리하지 않게)
    seen: set[str] = set()
    entries: list[Entry] = []
    last: Optional[Entry] = None
    known = True
    for e in gapgu:
        segs = [s for s in active_segments(e) if _is_ownership_segment(s)]
        if not segs:
            continue
        names = holder_names(e.holders)
        if not names:
            rank = base_rank(e.rank)
            same_rank = last is not None and rank is not None and rank == base_rank(last.rank)
            if all(s == "신탁" for s in segs) or same_rank:
                continue
            owners, keys, seen, entries, last, known = [], [], set(), [e], e, False
            continue
        if any(_is_partial_segment(s) for s in segs):
            for seg in segs:
                m = _SHARE_SELLER.search(seg) if "지분전부이전" in seg else None
                if m:  # 지분을 모두 넘긴 공유자는 뺀다
                    seller = normalize_name(m.group(1))
                    kept = [(o, k) for o, k in zip(owners, keys) if k != seller]
                    owners, keys = [o for o, _ in kept], [k for _, k in kept]
                    seen = set(keys)
            for name in names:  # 이미 있는 소유자는 다시 넣지 않는다
                key = normalize_name(name)
                if key not in seen:
                    owners.append(name)
                    keys.append(key)
                    seen.add(key)
            entries.append(e)
        else:
            owners, keys, entries, known = list(names), [normalize_name(n) for n in names], [e], True
            seen = set(keys)
        last = e
    if last is None:
        return None
    if not known:
        owners = []
    partial = any("일부이전" in s for s in active_segments(last))
    return Ownership(entry=last, owners=owners, shared=len(owners) >= 2 or partial, entries=entries)


def ownership(ctx: Ctx) -> Optional[Ownership]:
    """ctx의 현재 소유권. 여러 규칙·대조표가 쓰므로 한 번만 계산한다."""
    if not ctx.ownership_cache:
        ctx.ownership_cache.append(current_ownership(ctx.gapgu))
    return ctx.ownership_cache[0]


# --- 선순위 금액 (R5·R6) ---


@dataclass
class Claims:
    total: int  # 확인된 금액 합계
    missing: bool  # 금액을 읽지 못한 권리가 있는지
    entries: list[Entry]


def known_amount(amount: Optional[int]) -> Optional[int]:
    """금액이 0 이하면 읽지 못한 값으로 본다 (채권최고액·보증금·시세에 0원이나 음수는 없다)."""
    return amount if amount is not None and amount > 0 else None


def base_rank(rank: str) -> Optional[str]:
    m = re.match(r"\s*(\d+)", rank or "")
    return m.group(1) if m else None


def prior_claims(eulgu: list[Entry], words: tuple[str, ...]) -> Claims:
    """을구에서 words가 들어간 권리의 금액 합계.

    부기등기("1-1 1번근저당권변경")는 주등기와 같은 권리이므로 순위번호로 묶고,
    묶음마다 마지막으로 적힌 금액(변경된 채권최고액)만 더한다. 0 이하 금액은 읽지 못한 것으로 본다.
    """
    groups: dict[str, list[Entry]] = {}
    for i, e in enumerate(eulgu):
        if is_removal_record(e) or not has_word(e, words):
            continue
        groups.setdefault(base_rank(e.rank) or f"#{i}", []).append(e)
    total, missing, entries = 0, False, []
    for members in groups.values():
        entries.extend(members)
        amounts = [m.amount for m in members if known_amount(m.amount) and not has_word(m, ("질권",))]
        if amounts:
            total += amounts[-1]
        else:
            missing = True
    return Claims(total=total, missing=missing, entries=entries)


# ---------------------------------------------------------------------------
# 계약서·직접 입력 값 (계약서 → 직접 입력 순서)
# ---------------------------------------------------------------------------


@dataclass
class Landlord:
    names: list[str]  # 화면용 이름 (등록번호 제외)
    evidence: Evidence
    manual: bool  # 직접 입력에서 왔는지


def landlord_of(ctx: Ctx) -> Optional[Landlord]:
    """임대인 이름: 계약서 → 직접 입력 순서."""
    c = ctx.contract
    if c is not None:
        names = [display_name(n) for n in c.landlord_names if normalize_name(n)]
        if names:
            text = (c.sources.landlord or "").strip() or "계약서 임대인: " + ", ".join(names)
            return Landlord(names, Evidence(doc="contract", text=text), manual=False)
    if normalize_name(ctx.manual.landlord_name):
        name = display_name(ctx.manual.landlord_name)
        return Landlord([name], Evidence(doc="manual", text=f"임대인 이름(직접 입력): {name}"), manual=True)
    return None


@dataclass
class Deposit:
    amount: int
    evidence: Evidence


def deposit_of(ctx: Ctx) -> Optional[Deposit]:
    """보증금: 계약서 → 직접 입력 순서. 0 이하 값은 없는 것으로 본다 (비율 계산에 쓰지 않는다)."""
    c = ctx.contract
    if c is not None and known_amount(c.deposit):
        text = (c.sources.deposit or "").strip() or f"계약서 보증금: {fmt_money(c.deposit)}"
        return Deposit(c.deposit, Evidence(doc="contract", text=text))
    if known_amount(ctx.manual.deposit):
        amount = ctx.manual.deposit
        return Deposit(amount, Evidence(doc="manual", text=f"보증금(직접 입력): {fmt_money(amount)}"))
    return None


def deposit_given(ctx: Ctx) -> bool:
    """보증금 값이 어딘가에 적혀 있는지 (0 이하라 쓰지 못한 값 포함)."""
    c = ctx.contract
    return (c is not None and c.deposit is not None) or ctx.manual.deposit is not None


METHOD_LABEL = {
    "same_building": "같은 건물 실거래가",
    "same_dong": "같은 동 비슷한 집 추정",
    "manual": "직접 입력",
}
_METHOD_SOURCE = {
    "same_building": "같은 건물 매매 실거래가",
    "same_dong": "같은 동·비슷한 면적 매매 실거래가 (추정)",
    "manual": "직접 입력한 시세",
}


@dataclass
class Market:
    price: int
    label: str
    evidence: Evidence


def market_of(ctx: Ctx) -> Optional[Market]:
    """시세: 사용자가 직접 입력한 값 → 조회한 시세 순서. 0 이하 입력은 입력하지 않은 것으로 본다."""
    price = ctx.manual.market_price
    if price is not None and price > 0:
        text = f"알고 있는 시세(직접 입력): {fmt_money(price)}"
        return Market(price, METHOD_LABEL["manual"], Evidence(doc="manual", text=text))
    m = ctx.req.market
    if m is not None and m.price is not None:
        # 예: "같은 건물 매매 실거래가 2건 기준 2억 원 (2025년 12월 ~ 2026년 11월)"
        text = _METHOD_SOURCE[m.method]
        text += f" {m.deals}건 기준 {fmt_money(m.price)}" if m.deals > 0 else f" {fmt_money(m.price)}"
        if m.period:
            text += f" ({fmt_period(m.period)})"
        return Market(m.price, METHOD_LABEL[m.method], Evidence(doc="market", text=text))
    return None


# ---------------------------------------------------------------------------
# 결과 만들기
# ---------------------------------------------------------------------------


def _result(
    rid: str,
    level: str,
    title: str = "",
    summary: str = "",
    action: str = "",
    evidence: Optional[list[Evidence]] = None,
    unknown_reason: Optional[str] = None,
) -> RuleResult:
    return RuleResult(
        id=rid,
        name=RULE_NAMES[rid],
        level=level,
        title=title,
        summary=summary,
        action=action,
        evidence=evidence or [],
        unknown_reason=unknown_reason,
    )


def _unknown(rid: str, reason: str, evidence: Optional[list[Evidence]] = None) -> RuleResult:
    return _result(rid, "unknown", evidence=evidence, unknown_reason=reason)


def _green(rid: str, evidence: Optional[list[Evidence]] = None, summary: str = "") -> RuleResult:
    return _result(rid, "green", summary=summary, evidence=evidence)


# ---------------------------------------------------------------------------
# R1–R13
# ---------------------------------------------------------------------------


def rule_r1(ctx: Ctx) -> RuleResult:
    """임대인·소유자 불일치."""
    if not ctx.gapgu:
        return _unknown("R1", NO_GAPGU)
    landlord = landlord_of(ctx)
    if landlord is None:
        return _unknown("R1", "임대인 이름을 확인하지 못했어요")
    own = ownership(ctx)
    if own is None:
        return _unknown("R1", "등기부에서 현재 소유자를 찾지 못했어요")
    if not own.owners:
        return _unknown("R1", "등기부에서 현재 소유자 이름을 읽지 못했어요", [entry_evidence(own.entry)])
    evidence = [entry_evidence(e) for e in own.entries] + [landlord.evidence]
    owner_keys = {normalize_name(o) for o in own.owners}
    if any(normalize_name(n) not in owner_keys for n in landlord.names):
        owners, landlords = ", ".join(own.owners), ", ".join(landlord.names)
        whose = "입력한 임대인은" if landlord.manual else "계약서의 임대인은"
        return _result(
            "R1",
            "red",
            "계약하는 사람과 집주인이 달라요",
            f"등기부상 소유자는 {owners}인데, {whose} {landlords}{josa_ieyo(landlords)}.",
            "대리 계약이라면 위임장과 인감증명서를 확인하고 소유자와 직접 통화하세요. "
            "보증금은 소유자 명의 계좌로만 보내세요.",
            evidence,
        )
    if own.shared:
        count = f"{len(own.owners)}명" if len(own.owners) >= 2 else "여러 명"
        return _result(
            "R1",
            "yellow",
            "집주인이 여러 명이에요",
            f"이 집은 {count}이 함께 소유하고 있어요.",
            "다른 소유자들도 이 계약에 동의했는지 확인하세요. 가능하면 소유자 모두와 계약하세요.",
            evidence,
        )
    return _green("R1", evidence)


_TRUST_ENDED = ("귀속", "해지", "종료")


def has_trust(e: Entry) -> bool:
    """등기목적이나 등기원인에 "신탁"이 있는 항목. 신탁이 끝난 기록(신탁재산의귀속 등)은 뺀다."""
    if is_removal_record(e):
        return False
    if has_word(e, ("신탁",)):
        return True
    cause = compact(e.cause)
    return "신탁" in cause and not any(w in cause for w in _TRUST_ENDED)


_RANK_REF = re.compile(r"(\d+)(?:-\d+)?번")


def _removed_trust_ranks(gapgu: list[Entry]) -> set[str]:
    """"3번신탁등기말소"처럼 말소 기록에 적힌 신탁의 순위번호."""
    ranks = set()
    for e in gapgu:
        for seg in purpose_segments(e):
            m = _RANK_REF.match(seg) if _is_removal(seg) and "신탁" in seg else None
            if m:
                ranks.add(m.group(1))
    return ranks


def trust_state(gapgu: list[Entry], own: Optional[Ownership] = None) -> tuple[list[Entry], list[Entry]]:
    """(지금도 살아 있는 신탁 항목, 끝났는지 알 수 없는 신탁 항목).

    - "N번신탁등기말소"로 말소된 N번 신탁은 뺀다.
    - 신탁 뒤에 소유권이 다시 넘어갔으면(신탁재산의귀속 등) 끝난 신탁으로 본다.
      단 그 이전 행에 권리자도 등기원인도 없으면 끝났는지 알 수 없다.
    - 지금 소유자를 정한 항목이거나 그와 순위번호가 같은 신탁 행은 살아 있다.
    - 지금 소유권 항목보다 뒤에 적힌 신탁 행은 끝났다고 볼 근거가 없으므로 살아 있다.
    """
    hits = [(i, e) for i, e in enumerate(gapgu) if has_trust(e)]
    if not hits:
        return [], []
    removed = _removed_trust_ranks(gapgu)
    own = own if own is not None else current_ownership(gapgu)
    own_index = next((i for i, e in enumerate(gapgu) if own is not None and e is own.entry), None)
    own_rank = base_rank(own.entry.rank) if own is not None else None
    own_ids = {id(x) for x in own.entries} if own is not None else set()
    blind = own is not None and not own.owners and not _cause_text(own.entry.cause)  # 누구에게 왜 넘어갔는지 모른다
    live, unclear = [], []
    for i, e in hits:
        rank = base_rank(e.rank)
        if rank is not None and rank in removed:
            continue
        current = own is not None and (id(e) in own_ids or (rank is not None and rank == own_rank))
        if not current and own_index is not None and i < own_index:
            if blind:
                unclear.append(e)
            continue
        live.append(e)
    return live, unclear


def live_trusts(gapgu: list[Entry], own: Optional[Ownership] = None) -> list[Entry]:
    """지금도 살아 있는 신탁 항목."""
    return trust_state(gapgu, own)[0]


def rule_r2(ctx: Ctx) -> RuleResult:
    """신탁등기. 신탁이 끝난 뒤(말소·귀속)에는 지금 소유권이 신탁이 아니므로 🟢."""
    if not ctx.gapgu:
        return _unknown("R2", NO_GAPGU)
    own = ownership(ctx)
    hits, unclear = trust_state(ctx.gapgu, own)
    if not hits and unclear:
        evidence = [entry_evidence(e) for e in unclear] + [entry_evidence(own.entry)]
        return _unknown("R2", "신탁 뒤 소유권 이전 항목의 권리자와 원인을 읽지 못해 신탁이 끝났는지 확인하지 못했어요", evidence)
    if not hits:
        return _green("R2")
    trustees = next((names for e in reversed(hits) if (names := holder_names(e.holders))), [])
    trustee = ", ".join(trustees) or "신탁회사"
    return _result(
        "R2",
        "red",
        "집이 신탁회사 소유예요",
        f"등기부상 소유권이 {trustee}에게 넘어가 있어요. 신탁회사 동의 없이 맺은 계약은 보호받기 어려워요.",
        "신탁원부와 신탁회사의 임대 동의서를 요구하세요. 받기 전에는 계약을 미루세요.",
        [entry_evidence(e) for e in hits],
    )


_RESTRICTION_WORDS = ("압류", "가처분", "가등기", "경매")  # "압류"는 가압류를 포함한다


def rule_r3(ctx: Ctx) -> RuleResult:
    """압류·경매 등 제한."""
    if not ctx.gapgu:
        return _unknown("R3", NO_GAPGU)
    hits = [e for e in ctx.gapgu if not is_removal_record(e) and has_word(e, _RESTRICTION_WORDS)]
    if not hits:
        return _green("R3")
    if len(hits) == 1 and hits[0].received_at:  # 7.2 문구: "{접수일}에 {등기목적} 기록이 있어요."
        records = f"{fmt_date(hits[0].received_at)}에 {(hits[0].purpose or '').strip()}"
    else:  # 7.4: 기록마다 날짜를 붙인다 ("가압류(2026년 10월 1일), 압류(날짜 확인 안 됨)")
        records = ", ".join(
            f"{(e.purpose or '').strip()}({fmt_date(e.received_at) if e.received_at else '날짜 확인 안 됨'})"
            for e in hits
        )
    return _result(
        "R3",
        "red",
        "집에 압류·경매 같은 제한이 걸려 있어요",
        f"{records} 기록이 있어요. 집이 경매로 넘어가거나 소유자가 바뀔 수 있어요.",
        "이 기록이 말소되기 전에는 계약을 미루세요. 보증보험 가입도 어려울 수 있어요.",
        [entry_evidence(e) for e in hits],
    )


def rule_r4(ctx: Ctx) -> RuleResult:
    """임차권등기."""
    live = [e for e in ctx.eulgu if not is_removal_record(e)]
    orders = [e for e in live if has_word(e, ("주택임차권",)) or "임차권등기명령" in compact(e.cause)]
    if orders:
        return _result(
            "R4",
            "red",
            "이전 세입자가 보증금을 못 돌려받은 기록이 있어요",
            "임차권등기명령은 계약이 끝났는데 보증금을 돌려받지 못한 세입자가 하는 등기예요.",
            "집주인이 보증금을 돌려줄 능력이 있는지 의심해야 해요. 계약을 미루는 걸 권해요.",
            [entry_evidence(e) for e in orders],
        )
    leases = [e for e in live if has_word(e, ("임차권",))]
    if not leases:
        return _green("R4")
    parts = []
    for e in leases:
        who = ", ".join(holder_names(e.holders)) or "다른 임차인"
        amount = f"({fmt_money(e.amount)})" if known_amount(e.amount) else ""
        parts.append(f"{who}의 임차권{amount}")
    return _result(
        "R4",
        "yellow",
        "등기된 다른 임차인이 있어요",
        f"{', '.join(parts)}이 먼저 등기돼 있어요.",
        "이 금액이 내 보증금보다 먼저 돌려받는다는 점을 고려하세요.",
        [entry_evidence(e) for e in leases],
    )


_MULTI_WORDS = ("다가구", "단독", "다중")


def multi_household_lines(reg: RegistryExtract) -> list[str]:
    """R7 조건: 건물 등기부이고 용도 줄에 다가구·단독·다중이 있으면 그 줄들."""
    if reg.registry_type != "건물":
        return []
    return [line for line in reg.building_use_lines if any(w in compact(line) for w in _MULTI_WORDS)]


def senior_claims(ctx: Ctx) -> tuple[Claims, int]:
    """R5 선순위: 유효 을구의 저당·전세권·임차권 금액 + 직접 입력한 선순위 보증금 (합계)."""
    claims = prior_claims(ctx.eulgu, ("저당", "전세권", "임차권"))
    return claims, claims.total + max(ctx.manual.prior_deposits or 0, 0)


def rule_r5(ctx: Ctx) -> RuleResult:
    """시세 대비 보증금 비율."""
    if multi_household_lines(ctx.reg):
        return _unknown("R5", "다가구는 시세를 추정하기 어려워요")
    deposit = deposit_of(ctx)
    if deposit is None:
        if deposit_given(ctx):
            return _unknown("R5", "보증금 값이 올바르지 않아요")
        return _unknown("R5", "보증금을 확인하지 못했어요")
    if ctx.manual.prior_deposits is not None and ctx.manual.prior_deposits < 0:
        return _unknown("R5", "직접 입력한 선순위 보증금 값이 올바르지 않아요")
    market = market_of(ctx)
    if market is None:
        return _unknown("R5", "시세 정보가 없어요")
    if market.price <= 0:
        return _unknown("R5", "시세 값이 올바르지 않아요", [market.evidence])
    claims, prior = senior_claims(ctx)
    claim_evidence = [entry_evidence(e) for e in claims.entries]
    if claims.missing:
        return _unknown("R5", "선순위 권리 중 금액을 읽지 못한 항목이 있어요", claim_evidence)
    evidence = claim_evidence
    if ctx.manual.prior_deposits is not None:
        text = f"알고 있는 선순위 보증금(직접 입력): {fmt_money(ctx.manual.prior_deposits)}"
        evidence = evidence + [Evidence(doc="manual", text=text)]
    evidence = evidence + [deposit.evidence, market.evidence]
    ratio = Fraction(prior + deposit.amount, market.price)
    share = f"시세({fmt_money(market.price)}, {market.label})의 {percent_floor(ratio)}%예요."
    money = fmt_money(deposit.amount)
    if prior > 0:
        sentence = f"선순위 {fmt_money(prior)} + 내 보증금 {money} = {share}"
    else:  # 선순위가 없으면 "선순위 0원 +"를 쓰지 않는다
        sentence = f"내 보증금 {money}{josa_iga(money)} {share}"
    if ratio < RATIO_WARN:
        return _green("R5", evidence, summary=sentence)
    return _result(
        "R5",
        "red" if ratio >= RATIO_DANGER else "yellow",
        "보증금이 집값에 비해 위험한 수준이에요",
        sentence + " 경매로 넘어가면 보증금을 다 돌려받지 못할 수 있어요.",
        "보증금을 낮추거나, 전세보증금 반환보증에 가입할 수 있는지 먼저 확인하세요.",
        evidence,
    )


def _claims_text(claims: Claims) -> str:
    if not claims.missing:
        return fmt_money(claims.total)
    return f"{fmt_money(claims.total)} 이상" if claims.total > 0 else "확인되지 않은 금액"


def rule_r6(ctx: Ctx) -> RuleResult:
    """먼저 잡힌 담보·전세권."""
    claims = prior_claims(ctx.eulgu, ("저당", "전세권"))
    if not claims.entries:
        return _green("R6")
    return _result(
        "R6",
        "yellow",
        "집에 먼저 잡힌 빚(근저당 등)이 있어요",
        f"채권최고액 등 {_claims_text(claims)}이 내 보증금보다 먼저 돌려받아요.",
        "잔금일에 대출을 갚고 근저당을 말소하는 조건을 특약에 넣거나, "
        "집값에서 이 금액을 빼고도 보증금이 충분히 남는지 확인하세요.",
        [entry_evidence(e) for e in claims.entries],
    )


def rule_r7(ctx: Ctx) -> RuleResult:
    """다가구·단독."""
    reg = ctx.reg
    if reg.registry_type == "집합건물":
        return _green("R7")
    if reg.registry_type == "건물":
        lines = multi_household_lines(reg)
        if not lines:
            return _unknown("R7", "등기부 용도 줄에서 다가구·단독·다중주택 여부를 확인하지 못했어요")
        return _result(
            "R7",
            "yellow",
            "다른 세입자 보증금을 등기부로는 알 수 없어요",
            "이 건물은 한 사람이 통째로 소유해서, 먼저 들어온 세입자들의 보증금이 등기부에 나오지 않아요.",
            "집주인에게 확정일자 부여현황을 요구해 먼저 들어온 보증금 합계를 확인하세요.",
            [Evidence(doc="registry", text=line.strip()) for line in lines],
        )
    if reg.registry_type is None:
        return _unknown("R7", "등기부 종류(건물·집합건물)를 확인하지 못했어요")
    return _unknown("R7", "건물 등기부가 아니에요")


# 등기원인 앞의 날짜: "2026년8월20일", "2026년8월20일자", "[2026년8월20일]", "2026-08-20", "2026. 8. 20.",
# "2026/08/20", "20260820"
_CAUSE_DATE = re.compile(
    r"^\s*[\[(（]?\s*"
    r"(?:\d{4}\s*(?:년|[-./])\s*\d{1,2}\s*(?:월|[-./])\s*\d{1,2}(?:\s*(?:일|\.))?|\d{8}(?!\d))"
    r"(?:자)?\s*[\])）]?\s*"
)


def _cause_text(cause: Optional[str]) -> str:
    """등기원인 앞에 날짜가 붙어 와도 형식과 관계없이 원인만 남긴다 ("2026-08-20 매매" → "매매")."""
    return _CAUSE_DATE.sub("", cause or "").strip()


def rule_r8(ctx: Ctx) -> RuleResult:
    """최근 소유권 변동."""
    if not ctx.gapgu:
        return _unknown("R8", NO_GAPGU)
    own = ownership(ctx)
    if own is None:
        return _unknown("R8", "등기부에서 현재 소유권 항목을 찾지 못했어요")
    e = own.entry
    if e.received_at is None:
        return _unknown("R8", "소유권 접수일을 확인하지 못했어요", [entry_evidence(e)])
    days = (ctx.base_date - e.received_at).days
    if days > RECENT_OWNERSHIP_DAYS:
        return _green("R8", [entry_evidence(e)])
    cause = _cause_text(e.cause)
    changed = f"소유권이 {cause}{josa_euro(cause)} 바뀌었어요" if cause else "소유권이 바뀌었어요"
    if days > 0:
        when = f"기준일 {days}일 전"
    elif days == 0:
        when = "기준일 당일"
    else:
        when = f"기준일 {-days}일 후"
    return _result(
        "R8",
        "yellow",
        "최근에 집주인이 바뀌었어요",
        f"{fmt_date(e.received_at)}에 {changed} ({when}). "
        "매매와 전세 계약을 동시에 진행하는 수법에서 자주 보이는 패턴이에요.",
        "새 집주인이 이 집을 산 경위와 가격을 확인하세요. 내 보증금으로 집값을 치르는 구조라면 피하세요.",
        [entry_evidence(e)],
    )


def rule_r9(ctx: Ctx) -> RuleResult:
    """위반건축물."""
    b = ctx.req.building
    if b is None:
        return _unknown("R9", "건축물대장 정보가 없어요")
    if b.is_violating is None:
        if b.source == "api":
            # 공개 건축물대장 자료에는 위반 표시가 없다 (용도는 확인했어도)
            return _unknown(
                "R9", "공개 건축물대장 자료에는 위반건축물 표시가 없어요. 정부24나 세움터에서 건축물대장을 떼어 확인하세요"
            )
        return _unknown("R9", "건축물대장에서 위반건축물 여부를 확인하지 못했어요")
    source = "건축물대장 API" if b.source == "api" else "건축물대장"
    text = (b.source_text or "").strip() or f"{source} 위반건축물 여부: {'예' if b.is_violating else '아니오'}"
    evidence = [Evidence(doc="building", text=text)]
    if not b.is_violating:
        return _green("R9", evidence)
    return _result(
        "R9",
        "red",
        "불법 건축물로 등록돼 있어요",
        "건축물대장에 위반건축물 표시가 있어요.",
        "전세대출이나 보증보험이 거절될 수 있어요. 위반 내용과 시정 계획을 확인하세요.",
        evidence,
    )


_RESIDENTIAL_WORDS = ("주택", "아파트", "오피스텔")
_NON_RESIDENTIAL = re.compile(
    r"시설|사무소|사무실|점포|상가|주차장|창고|공장|음식점|소매점|학원|고시원|의원|숙박|업무|판매|위락"
)


_USE_TOKEN_SPLIT = re.compile(r"[\s,，/·ㆍ]+|및")


def _is_residential(text: str) -> bool:
    return any(w in compact(text) for w in _RESIDENTIAL_WORDS)


def _use_profile(lines: list[str]) -> tuple[bool, list[str]]:
    """용도 줄의 (주거용 단어가 있는지, 주거용이 아닌 용도 낱말들).

    주거용 단어가 든 낱말("업무시설(오피스텔)")은 주거용으로만 센다.
    """
    residential, uses = False, []
    for line in lines:
        for token in _USE_TOKEN_SPLIT.split(line):
            if any(w in token for w in _RESIDENTIAL_WORDS):
                residential = True
            elif token and _NON_RESIDENTIAL.search(token) and token not in uses:
                uses.append(token)
    return residential, uses


def _has_use_word(line: str) -> bool:
    residential, uses = _use_profile([line])
    return residential or bool(uses)


def _r10_yellow(use: str, evidence: list[Evidence]) -> RuleResult:
    return _result(
        "R10",
        "yellow",
        "주거용이 아닌 건물로 등록돼 있어요",
        f"이 호실의 용도는 '{use}'{josa_ieyo(use)}. 주거용으로 쓰면 불법 용도변경일 수 있어요.",
        "전세대출과 보증보험이 가능한지 먼저 확인하세요.",
        evidence,
    )


def _r10_from_lines(lines: list[str], mixed_is_unknown: bool) -> RuleResult:
    """용도 줄 묶음으로 판정한다. 주거용 단어 → 🟢, 비주거용 단어만 → 🟡, 없으면 ⚪.

    mixed_is_unknown: 두 종류가 섞여 있으면 ⚪ (집합건물에서 내 층을 알 수 없을 때).
    """
    used = [line for line in lines if _has_use_word(line)]
    residential, uses = _use_profile(used)
    evidence = [Evidence(doc="registry", text=line) for line in used]
    if residential and uses and mixed_is_unknown:
        return _unknown("R10", "주거용과 비주거용이 섞인 건물이라 내 층의 용도를 알 수 없어요", evidence)
    if residential:
        return _green("R10", evidence)
    if uses:
        return _r10_yellow(", ".join(uses), evidence)
    return _unknown("R10", "등기부 용도 줄에서 용도를 찾지 못했어요")


def rule_r10(ctx: Ctx) -> RuleResult:
    """주거용이 아닌 용도. 건축물대장 값이 있으면 그 값, 없으면 등기부 표제부 용도 줄."""
    b = ctx.req.building
    if b is not None:
        unit_use, main_use = (b.unit_use or "").strip(), (b.main_use or "").strip()
        use = unit_use or main_use
        if use:
            label = "전유부 용도" if unit_use else "주용도"
            text = (b.source_text or "").strip() or f"건축물대장 {label}: {use}"
            evidence = [Evidence(doc="building", text=text)]
            if _is_residential(use):
                return _green("R10", evidence)
            return _r10_yellow(use, evidence)

    reg = ctx.reg
    lines = [line.strip() for line in reg.building_use_lines if line and line.strip()]
    if not lines:
        return _unknown("R10", "건물 용도를 확인하지 못했어요")
    # 건물 등기부(다가구 등): 모든 줄을 본다. 종류를 못 읽었으면 집합건물처럼 내 층을 찾는다
    # (섞인 건물을 "주거용"으로 보지 않게)
    if reg.registry_type not in ("집합건물", None):
        return _r10_from_lines(lines, mixed_is_unknown=False)

    floor = parse_floor(reg.unit.floor)
    if floor is None:
        if is_basement_unit(reg.unit.ho):
            return _unknown("R10", "지하 호실은 등기부 용도 줄로 층을 확인하지 못했어요")
        floor = floor_from_ho(reg.unit.ho)
    if floor is not None:
        # 1. 내 층의 층별 줄에 용도 단어가 있으면 그 줄로 판정한다 (주거용 단어가 있으면 🟢)
        mine = [line for line in lines if is_floor_line(line) and line_has_floor(line, floor) and _has_use_word(line)]
        if mine:
            evidence = [Evidence(doc="registry", text=line) for line in mine]
            residential, uses = _use_profile(mine)
            return _green("R10", evidence) if residential else _r10_yellow(", ".join(uses), evidence)
    # 2. 층별 줄에 면적만 있거나 층을 모르면 건물 전체 줄과 기타 줄로 판정한다
    return _r10_from_lines([line for line in lines if not is_floor_line(line)], mixed_is_unknown=True)


_R11_RED_TITLE = "계약서의 호수가 등기부와 달라요"
_R11_RED_TAIL = "전입신고 주소가 등기와 다르면 대항력을 인정받지 못할 수 있어요."
_R11_RED_ACTION = "계약서와 전입신고에 등기부 표기를 그대로 적으세요."

# 집합건물 동·호 비교 결과 (대조표 결과 칸에도 그대로 쓴다)
HO_MISSING = "호수 없음"
HO_DIFFERS = "호수 다름"
DONG_DIFFERS = "동 다름"


@dataclass
class UnitFacts:
    """동·호의 화면용 원문 표기. 계약서 쪽은 칸이 비어 있으면 계약서 주소에서 읽은 값."""

    reg_dong: Optional[str]
    reg_ho: Optional[str]
    c_dong: Optional[str]
    c_ho: Optional[str]


def unit_facts(ctx: Ctx) -> UnitFacts:
    reg, c = ctx.reg, ctx.contract
    c_dong = c_ho = None
    if c is not None:
        addr_dong, addr_ho = unit_in_address(c.address)
        c_dong = unit_text(c.unit.dong, "동") or addr_dong
        c_ho = unit_text(c.unit.ho, "호") or addr_ho
    return UnitFacts(unit_text(reg.unit.dong, "동"), unit_text(reg.unit.ho, "호"), c_dong, c_ho)


def unit_mismatch(units: UnitFacts) -> Optional[str]:
    """집합건물 동·호 비교. 같으면 None. 동은 등기부에 동이 있을 때만 비교한다."""
    c_ho = unit_key(units.c_ho, "호")
    if c_ho is None:
        return HO_MISSING
    reg_ho = unit_key(units.reg_ho, "호")
    if reg_ho is not None and c_ho != reg_ho:
        return HO_DIFFERS
    reg_dong = unit_key(units.reg_dong, "동")
    if reg_dong is not None and unit_key(units.c_dong, "동") != reg_dong:
        return DONG_DIFFERS
    return None


def registry_address_text(reg: RegistryExtract) -> Optional[str]:
    """등기부 표기: 지번 주소(없으면 도로명 주소) + 건물 이름 + 동·호."""
    base = (reg.address_jibun or "").strip() or (reg.address_road or "").strip()
    parts = [base] if base else []
    unit = unit_label(unit_text(reg.unit.dong, "동"), unit_text(reg.unit.ho, "호"))
    for extra in ((reg.building_name or "").strip(), unit):
        if extra and compact(extra) not in compact(base):
            parts.append(extra)
    return " ".join(parts) or None


def contract_address_text(c: ContractExtract) -> Optional[str]:
    """계약서 주소. 주소에 없는 동·호 칸 값은 뒤에 붙인다."""
    address = (c.address or "").strip()
    units = (unit_text(c.unit.dong, "동"), unit_text(c.unit.ho, "호"))
    extra = [u for u in units if u and compact(u) not in compact(address)]
    return " ".join(([address] if address else []) + extra) or None


def is_collective(reg: RegistryExtract) -> bool:
    """집합건물로 볼지. 등기부 종류를 못 읽었어도 등기부에 동·호가 있으면 집합건물로 본다."""
    if reg.registry_type is not None:
        return reg.registry_type == "집합건물"
    return unit_key(reg.unit.ho, "호") is not None or unit_key(reg.unit.dong, "동") is not None


def rule_r11(ctx: Ctx) -> RuleResult:
    """주소·호수 불일치."""
    c = ctx.contract
    if c is None:
        return _unknown("R11", "계약서가 없어 주소를 비교하지 못했어요")
    address = (c.address or "").strip()
    if not address:
        return _unknown("R11", "계약서 주소가 없어요")
    reg = ctx.reg
    if any(address_too_long(a) for a in (address, reg.address_jibun, reg.address_road)):
        return _unknown("R11", "주소가 너무 길어 주소로 읽지 못했어요")
    units = unit_facts(ctx)
    reg_label = unit_label(units.reg_dong, units.reg_ho)
    reg_unit = " ".join(p for p in (reg.building_name, reg_label) if p)
    reg_text = " / ".join(p.strip() for p in (reg.address_jibun, reg.address_road, reg_unit) if p and p.strip())
    evidence = []
    if reg_text:
        evidence.append(Evidence(doc="registry", text=reg_text))
    evidence.append(Evidence(doc="contract", text=(c.sources.address or "").strip() or address))

    collective = is_collective(reg)
    if collective:
        mismatch = unit_mismatch(units)
        if mismatch == HO_MISSING:
            head = f"등기부는 {reg_label}인데, 계약서에는 호수가 없어요." if reg_label else "계약서에 호수가 없어요."
            return _result("R11", "red", _R11_RED_TITLE, f"{head} {_R11_RED_TAIL}", _R11_RED_ACTION, evidence)
        if mismatch:
            c_label = unit_label(units.c_dong, units.c_ho)
            summary = f"등기부는 {reg_label}, 계약서는 {c_label}{josa_ieyo(c_label)}. {_R11_RED_TAIL}"
            return _result("R11", "red", _R11_RED_TITLE, summary, _R11_RED_ACTION, evidence)

    cores = [core for core in (jibun_core(reg.address_jibun), road_core(reg.address_road)) if core]
    if not cores:
        return _unknown("R11", "등기부 주소를 확인하지 못했어요", evidence)
    if not any(address_has_core(address, core) for core in cores):
        return _result(
            "R11",
            "yellow",
            "계약서 주소가 등기부와 같은지 확인이 필요해요",
            "계약서 주소에서 등기부의 지번이나 도로명을 찾지 못했어요.",
            "계약서 주소를 등기부 주소와 한 글자씩 맞춰 보세요.",
            evidence,
        )
    if collective and unit_key(units.reg_ho, "호") is None:
        return _unknown("R11", "등기부에서 호수를 확인하지 못했어요", evidence)
    if reg.registry_type is None and not collective:  # 집합건물인지 몰라 호수를 비교하지 못했다
        return _unknown("R11", "등기부 종류(건물·집합건물)와 호수를 확인하지 못해 동·호수를 비교하지 못했어요", evidence)
    return _green("R11", evidence)


# 특약 문장 종류 (띄어쓰기 무시). 검사(R12)·계약 후 재확인·수정 전후 비교가 모두 이 정의를 쓴다.
# 특약이 누구의 의무인지: 맨 앞의 "갑은/을은", 아니면 "임대인은/임차인은"(주제), 아니면 "임대인이/임차인이"(주어)
_LEAD_PARTY = re.compile(r"^(?:\(?\d{1,3}[.)]|[①-⑳])?(갑|을)(?:\([^)]{0,30}\))?(?:은|는|이|가)")
_TOPIC = re.compile(r"(임대인|임차인)(?:\([^)]{0,30}\))?(?:측)?(?:은|는)")
_SUBJECT = re.compile(r"(임대인|임차인)(?:\([^)]{0,30}\))?(?:측)?(?:이|가|도)")
# 담보 설정을 분명히 막는 표현
_PROHIBITION_WORDS = ("설정하지", "설정을하지", "설정금지", "설정을금지", "설정할수없", "설정해서는", "추가대출")
# "담보"·"저당"과 같은 구절 안의 부정·금지 ("담보로 제공하지 않는다", "담보 제공 금지", "담보 설정 등 … 하지 않으며")
_SECURITY_DENIED = re.compile(r"(?:담보|저당)[^.,;:!?]{0,25}?(?:않|아니|금지|못|수없|불가)")
# 임차인의 전세대출을 돕는 문장의 낱말
_TENANT_LOAN_WORDS = ("전세자금", "전세대출", "반환채권", "질권", "협조")


def clause_party(term: str) -> Optional[str]:
    """특약이 누구의 의무인지: "landlord" · "tenant" · None(주어가 없음)."""
    t = compact(term)
    m = _LEAD_PARTY.match(t)
    if m:
        return "landlord" if m.group(1) == "갑" else "tenant"
    m = _TOPIC.search(t) or _SUBJECT.search(t)
    if m:
        return "landlord" if m.group(1) == "임대인" else "tenant"
    if "임대인의동의" in t or "임대인동의" in t:  # 임대인 동의를 받아야 하는 쪽은 임차인이다
        return "tenant"
    return None


def is_prohibition_clause(term: str) -> bool:
    """담보(근저당) 설정 금지 특약인지: 임대인이 담보 설정·추가 대출을 하지 않겠다는 문장.

    임차인의 의무(임차권 질권 설정 금지 등), 근저당 말소 약속, 임차인 전세대출 협조만 있는 문장은 아니다.
    """
    party = clause_party(term)
    if party == "tenant":
        return False
    t = compact(term)
    if any(w in t for w in _PROHIBITION_WORDS):
        return True
    if "말소" in t:
        return False
    tenant_loan = any(w in t for w in _TENANT_LOAN_WORDS)
    if party is None and tenant_loan:
        return False
    if "대출을받지" in t and not tenant_loan:
        return True
    return _SECURITY_DENIED.search(t) is not None


def is_removal_clause(term: str) -> bool:
    """근저당 말소 특약인지 ("말소"가 든 문장. 임차인의 의무는 아니다)."""
    return "말소" in compact(term) and clause_party(term) != "tenant"


def protective_terms(c: ContractExtract) -> list[str]:
    """보증금을 지키는 특약 문장: 담보 설정 금지나 말소 약속."""
    terms = [t.strip() for t in c.special_terms if t and t.strip()]
    return [t for t in terms if is_prohibition_clause(t) or is_removal_clause(t)]


def rule_r12(ctx: Ctx) -> RuleResult:
    """보호 특약 없음."""
    c = ctx.contract
    if c is None:
        return _unknown("R12", "계약서가 없어 특약을 확인하지 못했어요")
    terms = [t.strip() for t in c.special_terms if t and t.strip()]
    protective = protective_terms(c)
    if protective:
        return _green("R12", [Evidence(doc="contract", text=t) for t in protective])
    text = (c.sources.special_terms or "").strip() or "\n".join(terms) or "특약 없음"
    return _result(
        "R12",
        "yellow",
        "보증금을 지키는 특약이 없어요",
        "잔금 전후에 집주인이 새로 대출을 받지 못하게 막는 조항이 계약서에 없어요.",
        "아래 추천 특약을 계약서에 넣어 달라고 요청하세요.",
        [Evidence(doc="contract", text=text)],
    )


def rule_r13(ctx: Ctx) -> RuleResult:
    """오래된 등기부. 열람 일시를 한국 날짜로 바꿔 today와 비교한다."""
    viewed = ctx.reg.viewed_at
    if viewed is None:
        return _unknown("R13", "등기부 열람 일시를 확인하지 못했어요")
    local = to_kst(viewed)
    days = (ctx.today - local.date()).days
    evidence = [Evidence(doc="registry", text=f"열람 일시 {fmt_date(local.date())} {local:%H:%M}")]
    if days < STALE_REGISTRY_DAYS:
        return _green("R13", evidence)
    return _result(
        "R13",
        "yellow",
        f"{days}일 전에 뗀 등기부예요",
        "그 사이에 근저당 등이 새로 생겼을 수 있어요.",
        "계약 당일과 잔금 당일에 등기부를 다시 떼어 보세요.",
        evidence,
    )


RULES: list[tuple[str, Callable[[Ctx], RuleResult]]] = [
    ("R1", rule_r1),
    ("R2", rule_r2),
    ("R3", rule_r3),
    ("R4", rule_r4),
    ("R5", rule_r5),
    ("R6", rule_r6),
    ("R7", rule_r7),
    ("R8", rule_r8),
    ("R9", rule_r9),
    ("R10", rule_r10),
    ("R11", rule_r11),
    ("R12", rule_r12),
    ("R13", rule_r13),
]


def run_rule(rid: str, fn: Callable[[Ctx], RuleResult], ctx: Ctx) -> RuleResult:
    """규칙 하나를 계산한다. 실패하면 그 규칙만 ⚪로 둔다 (로그에 개인정보를 남기지 않는다).

    근거 원문에 든 등록번호 형식은 "******-*******"로 가린다. 나머지 원문은 그대로 둔다.
    """
    try:
        result = fn(ctx)
    except Exception as exc:  # noqa: BLE001
        logger.error("rule %s failed: %s", rid, type(exc).__name__)
        return _unknown(rid, RULE_FAILED)
    evidence = [e.model_copy(update={"text": mask_id_numbers(e.text)}) for e in result.evidence]
    return result.model_copy(update={"evidence": evidence})


def sort_key(r: RuleResult) -> tuple[int, int]:
    return (LEVEL_ORDER[r.level], int(r.id[1:]))


# ---------------------------------------------------------------------------
# 요청 메시지·특약·요청서에 쓰는 값
# ---------------------------------------------------------------------------


def message_address(ctx: Ctx) -> Optional[str]:
    """요청 메시지의 {주소}: 계약서 주소 → 등기부 도로명주소 → 지번주소 (등기부면 동·호를 붙인다)."""
    c = ctx.contract
    if c is not None and c.address and c.address.strip():
        return c.address.strip()
    base = (ctx.reg.address_road or "").strip() or (ctx.reg.address_jibun or "").strip()
    if not base:
        return None
    unit = unit_label(unit_text(ctx.reg.unit.dong, "동"), unit_text(ctx.reg.unit.ho, "호"))  # 원문 표기
    return f"{base} {unit}" if unit else base


def mortgage_amount(ctx: Ctx) -> Optional[str]:
    """특약용 근저당 채권최고액 합계. 근저당이 없으면 None, 금액을 모르면 자리 표시."""
    claims = prior_claims(ctx.eulgu, ("저당",))
    if not claims.entries:
        return None
    if claims.missing:
        return content.AMOUNT_PLACEHOLDER
    return fmt_money(claims.total)
