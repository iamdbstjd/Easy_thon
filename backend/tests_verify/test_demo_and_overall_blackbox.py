"""PRD 11.2 expected-grade table, P0-only variant, 7.3 overall verdict, 8.6 report shape.

Written from PRD.md only.
"""

from __future__ import annotations

import copy
import datetime as dt
import re

import pytest

from app.rules import build_report
from app.schemas import RULE_NAMES, CheckRequest, RegistryExtract
from verify_helpers import (
    BANNED,
    CORE,
    DISCLAIMER,
    EMOJI_RE,
    EXCEPTION_REASON,
    OV_GREEN,
    OV_INCOMPLETE,
    OV_RED,
    OV_YELLOW,
    R5_DAGAGU_REASON,
    RULE_IDS,
    TODAY,
    E,
    all_texts,
    demo,
    expected_overall,
    lv,
    p0,
    res,
    run,
)

G, Y, R, U = "green", "yellow", "red", "unknown"

# PRD 11.2
TABLE = {
    "A": dict(R1=G, R2=G, R3=G, R4=G, R5=G, R6=G, R7=G, R8=G, R9=G, R10=G, R11=G, R12=G, R13=G),
    "B": dict(R1=G, R2=G, R3=G, R4=G, R5=U, R6=Y, R7=Y, R8=Y, R9=G, R10=G, R11=G, R12=Y, R13=Y),
    "C": dict(R1=R, R2=R, R3=G, R4=G, R5=R, R6=G, R7=G, R8=Y, R9=G, R10=G, R11=G, R12=Y, R13=G),
}
OVERALL = {"A": OV_GREEN, "B": OV_YELLOW, "C": OV_RED}


# ---------------------------------------------------------------------------
# 11.2 table, full (P1 data present)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scenario", ["A", "B", "C"])
@pytest.mark.parametrize("rid", RULE_IDS)
def test_11_2_table_full(scenario, rid):
    assert lv(demo(scenario), rid) == TABLE[scenario][rid]


@pytest.mark.parametrize("scenario", ["A", "B", "C"])
def test_11_2_overall_full(scenario):
    rep = run(demo(scenario))
    assert rep.overall.level == OVERALL[scenario][0]
    assert rep.overall.title == OVERALL[scenario][1]


def test_11_2_messages_and_counts_full():
    a, b, c = run(demo("A")), run(demo("B")), run(demo("C"))
    assert a.overall.message == OV_GREEN[2]
    assert a.overall.unknown_note is None
    assert a.counts.model_dump() == {"red": 0, "yellow": 0, "unknown": 0, "green": 13}

    assert b.overall.message == "계약 전에 확인할 것이 5개 있어요."
    assert b.overall.unknown_note == "확인하지 못한 항목 1개"
    assert b.counts.model_dump() == {"red": 0, "yellow": 5, "unknown": 1, "green": 7}

    # 4.3 wireframe: 위험 3 · 주의 2 · 해당 없음 8
    assert c.overall.message == "보증금을 잃을 수 있는 위험 신호가 3개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요."
    assert c.overall.unknown_note is None
    assert c.counts.model_dump() == {"red": 3, "yellow": 2, "unknown": 0, "green": 8}


def test_11_2_r5_ratios():
    a = res(run(demo("A")), "R5")
    assert "5%" in a.summary, a.summary  # 11.2: 🟢 (5%) and 7.2: 🟢일 때도 비율은 보여준다
    assert "15%" not in a.summary
    c = res(run(demo("C")), "R5")
    assert "90%" in c.summary, c.summary
    b = res(run(demo("B")), "R5")
    assert b.unknown_reason and R5_DAGAGU_REASON in b.unknown_reason, b.unknown_reason


# ---------------------------------------------------------------------------
# 11.2 note: P1 absent -> R5/R9 unknown, overall unchanged
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scenario", ["A", "B", "C"])
@pytest.mark.parametrize("rid", RULE_IDS)
def test_11_2_table_p0_only(scenario, rid):
    exp = dict(TABLE[scenario])
    exp["R5"] = U
    exp["R9"] = U
    assert lv(p0(demo(scenario)), rid) == exp[rid]


@pytest.mark.parametrize("scenario", ["A", "B", "C"])
def test_11_2_overall_p0_only(scenario):
    rep = run(p0(demo(scenario)))
    assert (rep.overall.level, rep.overall.title) == OVERALL[scenario][:2]
    assert rep.overall.unknown_note == "확인하지 못한 항목 2개"


def test_11_2_p0_messages():
    a, b, c = (run(p0(demo(s))) for s in "ABC")
    assert a.overall.message == OV_GREEN[2]
    assert b.overall.message == "계약 전에 확인할 것이 5개 있어요."
    assert c.overall.message == "보증금을 잃을 수 있는 위험 신호가 2개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요."
    assert c.counts.model_dump() == {"red": 2, "yellow": 2, "unknown": 2, "green": 7}


# ---------------------------------------------------------------------------
# 7.3 four banner rows, {n}, core rules, unknown_note
# ---------------------------------------------------------------------------
def test_7_3_green_with_noncore_unknown():
    d = demo("A")
    d["building"] = None  # R9 unknown (non-core); R10 falls back to registry -> green
    rep = run(d)
    assert lv(rep, "R9") == U
    assert (rep.overall.level, rep.overall.title, rep.overall.message) == OV_GREEN
    assert rep.overall.unknown_note == "확인하지 못한 항목 1개"


def test_7_3_core_unknown_row():
    d = demo("A")
    d["registry"]["viewed_at"] = None  # R13 (core) unknown
    rep = run(d)
    assert lv(rep, "R13") == U
    assert rep.overall.level == "yellow"
    assert rep.overall.title == OV_INCOMPLETE[1]
    assert rep.overall.message == OV_INCOMPLETE[2].format(n=1)
    assert rep.overall.unknown_note == "확인하지 못한 항목 1개"


def test_7_3_core_unknown_n_counts_core_only():
    d = demo("A")
    d["registry"]["viewed_at"] = None  # R13 core
    d["registry"]["registry_type"] = None  # R7 core -> unknown
    d["building"] = None  # R9 non-core unknown
    rep = run(d)
    assert lv(rep, "R7") == U and lv(rep, "R13") == U and lv(rep, "R9") == U
    assert rep.overall.title == OV_INCOMPLETE[1]
    assert rep.overall.message == OV_INCOMPLETE[2].format(n=2)
    assert rep.overall.unknown_note == "확인하지 못한 항목 3개"


def test_7_3_yellow_beats_core_unknown():
    d = demo("A")
    d["registry"]["viewed_at"] = None
    d["contract"]["special_terms"] = ["반려동물은 키우지 않는다."]  # R12 yellow
    rep = run(d)
    assert (rep.overall.level, rep.overall.title) == ("yellow", "추가 확인 필요")
    assert rep.overall.message == "계약 전에 확인할 것이 1개 있어요."
    assert rep.overall.unknown_note == "확인하지 못한 항목 1개"


def test_7_3_red_row_counts_reds_only():
    d = demo("A")
    d["building"]["is_violating"] = True  # R9 red
    d["contract"]["special_terms"] = []  # R12 yellow
    rep = run(d)
    assert (rep.overall.level, rep.overall.title) == ("red", "계약 보류 권장")
    assert rep.overall.message == OV_RED[2].format(n=1)


def test_7_1_empty_input_returns_unknown_with_reasons():
    rep = build_report(CheckRequest(registry=RegistryExtract(), today=TODAY))
    exp = dict(R1=U, R2=U, R3=U, R4=G, R5=U, R6=G, R7=U, R8=U, R9=U, R10=U, R11=U, R12=U, R13=U)
    got = {r.id: r.level for r in rep.results}
    assert got == exp
    for r in rep.results:
        if r.level == U:
            assert r.unknown_reason, f"{r.id} unknown without reason"
    assert rep.overall.title == OV_INCOMPLETE[1]
    assert rep.overall.message == OV_INCOMPLETE[2].format(n=6)
    assert rep.overall.unknown_note == "확인하지 못한 항목 11개"


def test_7_1_empty_gapgu_makes_gapgu_rules_unknown():
    d = demo("A")
    d["registry"]["gapgu"] = []
    rep = run(d)
    for rid in ("R1", "R2", "R3", "R8"):
        assert lv(rep, rid) == U, rid
        assert res(rep, rid).unknown_reason
    assert lv(rep, "R4") == G and lv(rep, "R6") == G


def test_7_4_all_cancelled_gapgu_counts_as_empty():
    d = demo("A")
    for e in d["registry"]["gapgu"]:
        e["is_cancelled"] = True
    rep = run(d)
    for rid in ("R1", "R2", "R3", "R8"):
        assert lv(rep, rid) == U, rid


def test_7_4_rule_exception_isolated():
    """7.4: 규칙 계산 중 예외가 나면 그 규칙만 ⚪ ("이 항목을 계산하는 중 문제가 생겼어요")."""
    req = CheckRequest.model_validate(demo("A"))
    bad = req.registry.model_copy(update={"viewed_at": "not-a-datetime"})  # bypasses validation
    rep = build_report(req.model_copy(update={"registry": bad}))
    r13 = res(rep, "R13")
    assert r13.level == U
    assert r13.unknown_reason == EXCEPTION_REASON
    for rid in RULE_IDS:
        if rid != "R13":
            assert lv(rep, rid) == G, rid


# ---------------------------------------------------------------------------
# 8.6 report-level invariants over a corpus
# ---------------------------------------------------------------------------
def _corpus():
    out = {s: demo(s) for s in "ABC"}
    out.update({f"{s}_p0": p0(demo(s)) for s in "ABC"})

    d = demo("A")
    d["registry"]["gapgu"].append(E("3", "가압류", "2026-10-01", "2026년9월30일 가압류결정", ["국민은행"]))
    out["r3_red"] = d

    d = demo("A")
    d["registry"]["eulgu"] = [E("1", "주택임차권", "2026-01-05", "2026년1월5일 임차권등기명령", ["박세입"], 50_000_000)]
    out["r4_red"] = d

    d = demo("A")
    d["registry"]["eulgu"] = [E("1", "근저당권설정", "2020-01-01", "설정계약", ["국민은행"], None)]
    out["r6_unknown_amt"] = d

    d = demo("A")
    d["contract"]["unit"]["ho"] = "303호"
    out["r11_red"] = d

    d = demo("A")
    d["contract"] = None
    d["manual"] = {"deposit": 50_000_000, "monthly_rent": None, "contract_date": "2026-11-20",
                   "landlord_name": "김○○", "prior_deposits": 10_000_000, "market_price": 300_000_000}
    d["market"] = None
    out["manual_only"] = d

    d = demo("A")
    d["building"] = {"main_use": "제2종근린생활시설", "unit_use": "제2종근린생활시설", "is_violating": True,
                     "source": "pdf", "source_text": "위반건축물"}
    out["r9_r10"] = d
    return out


CORPUS = _corpus()


@pytest.mark.parametrize("name", list(CORPUS))
def test_8_6_invariants(name):
    d = CORPUS[name]
    rep = run(d)
    # all 13 rules exactly once, with PRD names
    assert sorted(r.id for r in rep.results) == sorted(RULE_IDS)
    for r in rep.results:
        assert r.name == RULE_NAMES[r.id]
    # counts
    for k in ("red", "yellow", "unknown", "green"):
        assert getattr(rep.counts, k) == sum(r.level == k for r in rep.results), k
    # overall per 7.3
    lvl, title, msg, note = expected_overall(rep.results)
    assert (rep.overall.level, rep.overall.title, rep.overall.message, rep.overall.unknown_note) == (lvl, title, msg, note)
    # red/yellow carry title + >=1 evidence (F6); unknown carries reason (F5)
    for r in rep.results:
        if r.level in ("red", "yellow"):
            assert r.title and r.summary and r.action, r.id
            assert r.evidence, f"{r.id} {r.level} without evidence"
        if r.level == "unknown":
            assert r.unknown_reason, f"{r.id} unknown without reason"
    # disclaimer 12.4
    assert rep.disclaimer == DISCLAIMER
    # echo
    assert rep.mode == d.get("mode", "live")
    assert rep.today == dt.date.fromisoformat(d["today"])


@pytest.mark.parametrize("name", list(CORPUS))
def test_10_banned_phrases_and_emoji_absent(name):
    rep = run(CORPUS[name])
    for t in all_texts(rep):
        for b in BANNED:
            assert b not in t, f"banned phrase {b!r} in {t!r}"
        assert not EMOJI_RE.search(t), f"emoji in {t!r}"


@pytest.mark.parametrize("name", list(CORPUS))
def test_4_2_result_order(name):
    """S5: 🔴 → 🟡, 같은 등급 안에서는 규칙 ID 순서 (numeric, so R2 < R10)."""
    rep = run(CORPUS[name])
    num = [int(r.id[1:]) for r in rep.results]
    for level in ("red", "yellow", "unknown", "green"):
        seq = [int(r.id[1:]) for r in rep.results if r.level == level]
        assert seq == sorted(seq), f"{level}: {seq}"
    plain = num == list(range(1, 14))
    rank = {"red": 0, "yellow": 1, "unknown": 2, "green": 2}
    ranks = [rank[r.level] for r in rep.results]
    assert plain or ranks == sorted(ranks), [r.id + ":" + r.level for r in rep.results]


@pytest.mark.parametrize("name", list(CORPUS))
def test_10_determinism(name):
    a = run(CORPUS[name]).model_dump(exclude={"generated_at"})
    b = run(CORPUS[name]).model_dump(exclude={"generated_at"})
    assert a == b


def test_8_6_mode_default_live_and_generated_at_kst():
    d = demo("A")
    d["mode"] = "live"
    rep = run(d)
    assert rep.mode == "live"
    assert rep.generated_at.tzinfo is not None
    assert rep.generated_at.utcoffset() == dt.timedelta(hours=9)  # 8.6 example: +09:00


def test_9_today_missing_uses_korean_date():
    """9: today가 없으면 현재 한국 날짜 (may be filled by the API layer instead)."""
    d = demo("A")
    d["today"] = None
    rep = run(d)
    kst = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    assert rep.today == kst
