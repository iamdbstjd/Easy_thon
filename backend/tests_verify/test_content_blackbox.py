"""Content checks: request message, special terms, checklist, disclaimer. Written from the spec only."""

from __future__ import annotations

import datetime as dt

import pytest

from verify_helpers import (
    DISCLAIMER,
    MI_ALWAYS,
    MI_R1,
    MI_R2,
    MI_R6,
    MSG_HEAD,
    MSG_TAIL,
    ST_ALWAYS,
    ST_JEONSE,
    ST_NOTE,
    ST_R2,
    ST_R6,
    ST_R12,
    E,
    demo,
    parse_items,
    run,
    ws,
)

A_ADDR = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호"


# ---------------------------------------------------------------------------
# 12.4
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("s", ["A", "B", "C"])
def test_12_4_disclaimer(s):
    assert run(demo(s)).disclaimer == DISCLAIMER


# ---------------------------------------------------------------------------
# 12.1 request message
# ---------------------------------------------------------------------------
def _items(rep):
    items = parse_items(rep.request_message)
    assert [n for n, _ in items] == list(range(1, len(items) + 1)), rep.request_message
    return [t for _, t in items]


@pytest.mark.parametrize(
    "s,expected",
    [
        ("A", MI_ALWAYS),
        ("B", MI_ALWAYS + MI_R6),
        ("C", MI_ALWAYS + MI_R2 + MI_R1),
    ],
)
def test_12_1_items_selected(s, expected):
    rep = run(demo(s))
    assert rep.request_message, "request_message is null"
    assert set(_items(rep)) == set(expected), rep.request_message


@pytest.mark.parametrize(
    "s,expected",
    [("B", MI_ALWAYS + MI_R6), ("C", MI_ALWAYS + MI_R2 + MI_R1)],
)
def test_12_1_items_order_follows_table(s, expected):
    assert _items(run(demo(s))) == expected


@pytest.mark.parametrize("s", ["A", "B", "C"])
def test_12_1_template_whitespace_insensitive(s):
    d = demo(s)
    msg = run(d).request_message
    head = MSG_HEAD.format(addr=d["contract"]["address"])
    assert ws(msg).startswith(ws(head)), msg
    assert ws(msg).endswith(ws(MSG_TAIL)), msg


def test_12_1_template_exact_a():
    msg = run(demo("A")).request_message
    expected = MSG_HEAD.format(addr=A_ADDR) + "1. 확정일자 부여현황\n2. 국세·지방세 납세증명서" + MSG_TAIL
    assert msg == expected


def test_12_1_agent_adds_power_of_attorney():
    d = demo("A")
    d["contract"]["agent_name"] = "홍길동"
    items = _items(run(d))
    assert set(items) == set(MI_ALWAYS + MI_R1), items


def test_12_1_r6_yellow_from_jeonse_right_only_has_no_mortgage_item():
    # Explicit rule: "R6 🟡이고 저당 행이 있을 때" and
    # "전세권만으로 R6가 🟡이면 넣지 않는다"
    d = demo("A")
    d["registry"]["eulgu"] = [E("1", "전세권설정", "2020-01-01", "설정계약", ["홍길동"], 100_000_000)]
    items = _items(run(d))
    assert items == MI_ALWAYS, items


def test_12_1_address_fallback_registry_plus_unit():
    d = demo("A")
    d["contract"] = None
    d["manual"]["landlord_name"] = "김○○"
    msg = run(d).request_message
    assert msg
    first = msg.split("\n")[0]
    assert ("죽전동 123-4" in first or "포은대로 123" in first) and "302호" in first, first


def test_12_1_address_fallback_when_contract_address_missing():
    d = demo("A")
    d["contract"]["address"] = None
    first = run(d).request_message.split("\n")[0]
    assert ("죽전동 123-4" in first or "포은대로 123" in first) and "302호" in first, first


def test_12_1_address_last_fallback():
    d = demo("A")
    d["contract"] = None
    d["registry"]["address_jibun"] = None
    d["registry"]["address_road"] = None
    msg = run(d).request_message
    assert msg.startswith("안녕하세요. 계약하려는 집 임대차 계약 건으로 연락드립니다."), msg


# ---------------------------------------------------------------------------
# 12.2 special terms
# ---------------------------------------------------------------------------
def test_12_2_scenario_a():
    assert run(demo("A")).special_terms == [ST_ALWAYS]


def test_12_2_scenario_b():
    terms = run(demo("B")).special_terms
    assert set(terms) == {ST_R12, ST_R6.format(a="1억 2,000만 원"), ST_ALWAYS}, terms


def test_12_2_scenario_c():
    terms = run(demo("C")).special_terms
    assert set(terms) == {ST_R12, ST_JEONSE, ST_ALWAYS, ST_R2}, terms


@pytest.mark.parametrize("s", ["B", "C"])
def test_12_2_order_follows_table(s):
    terms = run(demo(s)).special_terms
    order = [ST_R12, "R6", ST_JEONSE, ST_ALWAYS, ST_R2]

    def key(t):
        return order.index("R6") if t.startswith("임대인은 잔금일까지 등기부상 근저당권") else order.index(t)

    assert terms == sorted(terms, key=key), terms


def test_12_2_note_not_mixed_into_terms():
    for s in "ABC":
        assert ST_NOTE not in run(demo(s)).special_terms


def test_7_4_r6_term_only_with_mortgage_row():
    d = demo("A")
    d["registry"]["eulgu"] = [E("1", "전세권설정", "2020-01-01", "설정계약", ["홍길동"], 100_000_000)]
    terms = run(d).special_terms
    assert not any("근저당권(채권최고액" in t for t in terms), terms


@pytest.mark.parametrize(
    "rows",
    [
        [E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], None)],
        [E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
         E("2", "근저당권설정", "2021-01-01", "설정계약", ["B은행"], None)],
    ],
)
def test_7_4_r6_term_unknown_amount(rows):
    d = demo("A")
    d["registry"]["eulgu"] = rows
    terms = run(d).special_terms
    assert ST_R6.format(a="○○원") in terms, terms


def test_12_2_r6_term_sum_with_bugi():
    d = demo("A")
    d["registry"]["eulgu"] = [
        E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
        E("1-1", "1번근저당권변경", "2021-01-01", "변경계약", ["A은행"], 150_000_000),
    ]
    assert ST_R6.format(a="1억 5,000만 원") in run(d).special_terms


# ---------------------------------------------------------------------------
# 12.3 checklist
# ---------------------------------------------------------------------------
WHENS = ["계약 전", "계약일", "잔금일", "입주일", "입주 후"]


def _by_when(rep):
    out = {}
    for c in rep.checklist:
        out.setdefault(c.when, []).append(c)
    return out


@pytest.mark.parametrize("s", ["A", "B", "C"])
def test_12_3_structure_and_dates(s):
    rep = run(demo(s))
    assert rep.checklist, "checklist empty"
    bw = _by_when(rep)
    assert set(bw) == set(WHENS), list(bw)
    assert all(c.date == dt.date(2026, 11, 14) for c in bw["계약일"])
    assert all(c.date == dt.date(2026, 12, 1) for c in bw["잔금일"])
    assert all(c.date == dt.date(2026, 12, 1) for c in bw["입주일"])
    titles = " ".join(c.title for c in rep.checklist)
    for kw in ["등기부", "확정일자 부여현황", "납세증명서", "신분증", "특약", "계약금", "전입신고", "계약서 원본"]:
        assert kw in titles, kw
    assert all("(전세)" not in c.title for c in rep.checklist)


def test_12_3_order():
    rep = run(demo("C"))
    idx = [WHENS.index(c.when) for c in rep.checklist]
    assert idx == sorted(idx), [c.when for c in rep.checklist]


@pytest.mark.parametrize("s,has", [("A", False), ("B", False), ("C", True)])
def test_7_4_jeonse_item_only_for_jeonse(s, has):
    rep = run(demo(s))
    hits = [c for c in rep.checklist if "반환보증" in c.title]
    assert bool(hits) == has, [c.title for c in rep.checklist]
    if has:
        assert all(c.when == "입주 후" for c in hits)


def test_12_3_move_in_fallback_and_explicit():
    d = demo("A")
    d["contract"]["balance_date"] = "2026-12-05"
    d["contract"]["move_in_date"] = None
    bw = _by_when(run(d))
    assert all(c.date == dt.date(2026, 12, 5) for c in bw["입주일"])
    assert all(c.date == dt.date(2026, 12, 5) for c in bw["잔금일"])
    d["contract"]["move_in_date"] = "2026-12-07"
    bw = _by_when(run(d))
    assert all(c.date == dt.date(2026, 12, 7) for c in bw["입주일"])


def test_8_6_example_balance_item_title():
    rep = run(demo("C"))
    assert any(c.when == "잔금일" and "잔금 보내기 전 등기부 다시 떼기" in c.title for c in rep.checklist)
