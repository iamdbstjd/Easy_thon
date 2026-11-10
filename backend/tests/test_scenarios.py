"""데모 시나리오 A·B·C 통합 테스트."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from app.rules import build_report
from app.rules.content import BANNED_PHRASES
from app.schemas import RULE_NAMES, CheckRequest, Report

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"
SCENARIOS = ["A", "B", "C"]

G, Y, R, U = "green", "yellow", "red", "unknown"

# 예시 A·B·C 기대 등급표
_TABLE = {
    #       A  B  C
    "R1": (G, G, R),
    "R2": (G, G, R),
    "R3": (G, G, G),
    "R4": (G, G, G),
    "R5": (G, U, R),
    "R6": (G, Y, G),
    "R7": (G, Y, G),
    "R8": (G, Y, Y),
    "R9": (G, G, G),
    "R10": (G, G, G),
    "R11": (G, G, G),
    "R12": (G, Y, Y),
    "R13": (G, Y, G),
}
EXPECTED = {name: {rid: row[i] for rid, row in _TABLE.items()} for i, name in enumerate(SCENARIOS)}
OVERALL = {
    "A": ("green", "큰 위험 신호 없음"),
    "B": ("yellow", "추가 확인 필요"),
    "C": ("red", "계약 보류 권장"),
}


def load(name: str) -> CheckRequest:
    return CheckRequest.model_validate_json((DEMO_DIR / f"{name}.json").read_bytes())


def p0_only(name: str) -> CheckRequest:
    """P1 데이터(건축물대장·시세)가 없는 경우."""
    return load(name).model_copy(update={"building": None, "market": None})


def levels(report: Report) -> dict[str, str]:
    return {r.id: r.level for r in report.results}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


# ---------------------------------------------------------------------------
# 데모 입력 파일
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixture_is_a_complete_demo_request(name):
    raw = json.loads((DEMO_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert raw["today"] == "2026-11-14"
    assert raw["mode"] == "demo"
    req = CheckRequest.model_validate(raw)
    assert req.registry.is_registry and req.contract and req.contract.is_contract
    assert req.registry.viewed_at is not None and req.registry.address_jibun and req.registry.address_road
    assert req.contract.contract_date == dt.date(2026, 11, 14)
    assert req.contract.balance_date == dt.date(2026, 12, 1)
    for e in req.registry.gapgu + req.registry.eulgu:
        assert e.page and e.source_text.startswith(f"{e.rank} ")


def test_fixture_settings_follow_prd_11_1():
    a, b, c = load("A"), load("B"), load("C")
    assert (a.registry.registry_type, b.registry.registry_type, c.registry.registry_type) == ("집합건물", "건물", "집합건물")
    assert (a.contract.deposit, b.contract.deposit, c.contract.deposit) == (10_000_000, 30_000_000, 180_000_000)
    assert (a.contract.lease_type, b.contract.lease_type, c.contract.lease_type) == ("월세", "월세", "전세")
    assert a.market.price == c.market.price == 200_000_000 and b.market is None
    assert all(req.building.is_violating is False for req in (a, b, c))
    assert c.contract.landlord_names == ["이○○"] and c.contract.special_terms == []
    assert [e.amount for e in b.registry.eulgu] == [120_000_000]


# ---------------------------------------------------------------------------
# 기대 등급표
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_expected_grades(name):
    report = build_report(load(name))
    assert levels(report) == EXPECTED[name]
    assert (report.overall.level, report.overall.title) == OVERALL[name]


@pytest.mark.parametrize("name", SCENARIOS)
def test_p0_only_variant_keeps_overall(name):
    report = build_report(p0_only(name))
    assert levels(report) == dict(EXPECTED[name], R5=U, R9=U)
    # R5·R9는 핵심 규칙이 아니므로 A도 "큰 위험 신호 없음" 그대로다
    assert (report.overall.level, report.overall.title) == OVERALL[name]
    assert report.overall.unknown_note == "확인하지 못한 항목 2개"
    for r in report.results:
        if r.level == U:
            assert r.unknown_reason


@pytest.mark.parametrize(
    "name, level, title, message",
    [
        (
            "A",
            "yellow",
            "확인 미완료",
            "위험 신호는 찾지 못했지만, 꼭 확인해야 할 항목 1개를 확인하지 못했어요. 빠진 내용을 채운 뒤 다시 검사하세요.",
        ),
        ("B", "yellow", "추가 확인 필요", "계약 전에 확인할 것이 4개 있어요."),
        ("C", "red", "계약 보류 권장", "보증금을 잃을 수 있는 위험 신호가 1개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요."),
    ],
)
def test_registry_only_upload(name, level, title, message):
    """등기부만 올린 경우 (계약서·직접 입력·P1 데이터 없음): 임대인 이름이 없어 R1이 ⚪다."""
    report = build_report(load(name).model_copy(update={"contract": None, "building": None, "market": None}))
    assert levels(report)["R1"] == U
    assert (report.overall.level, report.overall.title, report.overall.message) == (level, title, message)


def test_overall_banners():
    a, b, c = (build_report(load(n)) for n in SCENARIOS)
    assert a.overall.message == (
        "확인한 범위에서는 큰 위험 신호를 찾지 못했어요. 안전을 보장하는 것은 아니니 아래 할 일은 꼭 챙기세요."
    )
    assert a.overall.unknown_note is None
    assert b.overall.message == "계약 전에 확인할 것이 5개 있어요."
    assert b.overall.unknown_note == "확인하지 못한 항목 1개"
    assert c.overall.message == "보증금을 잃을 수 있는 위험 신호가 3개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요."
    assert c.overall.unknown_note is None
    # 검토서 예시: 위험 3 · 주의 2 · 해당 없음 8
    assert c.counts.model_dump() == {"red": 3, "yellow": 2, "unknown": 0, "green": 8}
    assert a.counts.model_dump() == {"red": 0, "yellow": 0, "unknown": 0, "green": 13}
    assert b.counts.model_dump() == {"red": 0, "yellow": 5, "unknown": 1, "green": 7}


def test_scenario_c_copy_matches_prd():
    report = build_report(load("C"))
    # 🔴 → 🟡 → 🟢, 같은 등급 안에서는 규칙 번호 순서
    order = ["R1", "R2", "R5", "R8", "R12", "R3", "R4", "R6", "R7", "R9", "R10", "R11", "R13"]
    assert [r.id for r in report.results] == order
    res = {r.id: r for r in report.results}
    assert res["R1"].title == "계약하는 사람과 집주인이 달라요"
    assert res["R1"].summary == "등기부상 소유자는 ○○부동산신탁(주)인데, 계약서의 임대인은 이○○이에요."
    assert [(e.doc, e.page) for e in res["R1"].evidence] == [("registry", 2), ("contract", None)]
    assert res["R2"].summary.startswith("등기부상 소유권이 ○○부동산신탁(주)에게 넘어가 있어요.")
    assert res["R5"].summary.startswith(
        "선순위 0원 + 내 보증금 1억 8,000만 원 = 시세(2억 원, 같은 건물 실거래가)의 90%예요."
    )
    assert "market" in [e.doc for e in res["R5"].evidence]
    assert res["R8"].summary.startswith("2026년 8월 26일에 소유권이 신탁으로 바뀌었어요 (기준일 80일 전).")
    assert res["R12"].evidence[0].text == "특약 없음"


def test_scenario_c_content():
    report = build_report(load("C"))
    assert report.request_message.startswith(
        "안녕하세요. 경기도 용인시 수지구 죽전동 789-1 ○○파크빌 302호 임대차 계약 건으로 연락드립니다."
    )
    for line in ["1. 확정일자 부여현황", "2. 국세·지방세 납세증명서", "3. 신탁원부", "4. 신탁회사(수탁자)의 임대 동의서", "5. 위임장", "6. 인감증명서"]:
        assert line in report.request_message
    assert len(report.special_terms) == 4  # R12, 전세, 항상, R2
    assert report.special_terms[0].startswith("임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다.")
    assert report.special_terms[-1].startswith("임대인은 잔금일 전까지 수탁자(신탁회사)의 임대 동의서를 제출한다.")
    assert "전세보증금 반환보증 가입" in [c.title for c in report.checklist]


@pytest.mark.parametrize("name", ["A", "C"])
def test_market_evidence_reads_as_plain_korean(name):
    r5 = {r.id: r for r in build_report(load(name)).results}["R5"]
    assert r5.name == "시세 대비 보증금 비율"
    market = [e.text for e in r5.evidence if e.doc == "market"]
    assert market == ["같은 건물 매매 실거래가 2건 기준 2억 원 (2025년 12월 ~ 2026년 11월)"]


def test_scenario_a_and_b_details():
    a = {r.id: r for r in build_report(load("A")).results}
    assert a["R5"].summary == "선순위 0원 + 내 보증금 1,000만 원 = 시세(2억 원, 같은 건물 실거래가)의 5%예요."

    report = build_report(load("B"))
    b = {r.id: r for r in report.results}
    assert b["R5"].unknown_reason == "다가구는 시세를 추정하기 어려워요"
    assert b["R6"].summary == "채권최고액 등 1억 2,000만 원이 내 보증금보다 먼저 돌려받아요."
    assert b["R8"].summary.startswith("2026년 9월 15일에 소유권이 매매로 바뀌었어요 (기준일 60일 전).")
    assert b["R13"].title == "5일 전에 뗀 등기부예요"
    assert "3. 근저당 대출을 잔금일에 갚고 말소할 계획인지" in report.request_message
    assert "임대인은 잔금일까지 등기부상 근저당권(채권최고액 1억 2,000만 원)을 말소한다." in report.special_terms


# ---------------------------------------------------------------------------
# 리포트 형식·결정성·금지 표현
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCENARIOS)
def test_report_shape(name):
    report = build_report(load(name))
    assert report.mode == "demo"
    assert report.today == dt.date(2026, 11, 14)
    assert report.generated_at.utcoffset() == dt.timedelta(hours=9)
    assert sorted(r.id for r in report.results) == sorted(RULE_NAMES)
    order = {"red": 0, "yellow": 1, "unknown": 2, "green": 3}
    keys = [(order[r.level], int(r.id[1:])) for r in report.results]
    assert keys == sorted(keys)
    counted = {lvl: sum(1 for r in report.results if r.level == lvl) for lvl in order}
    assert report.counts.model_dump() == counted
    for r in report.results:
        assert r.name == RULE_NAMES[r.id]
        if r.level in ("red", "yellow"):
            assert r.title and r.summary and r.action and r.evidence
        assert (r.unknown_reason is not None) == (r.level == "unknown")
    assert report.request_message
    assert report.special_terms
    assert report.checklist
    assert report.disclaimer.startswith("이 결과는 올려주신 서류와 공개 데이터를")


ID_SHAPE = re.compile(r"\d{6}\s*-\s*[\d*]{7}")


def test_scenario_c_evidence_hides_id_numbers_but_keeps_the_quote():
    """근거 원문의 등록번호 형식만 "******-*******"로 가리고 나머지는 그대로 둔다 (발표 화면에 띄우는 리포트)."""
    req = load("C")
    r1 = {r.id: r for r in build_report(req).results}["R1"]
    registry_quote = req.registry.gapgu[2].source_text
    landlord_quote = req.contract.sources.landlord
    assert "110111-*******" in registry_quote and "900101-*******" in landlord_quote
    assert [(e.doc, e.text) for e in r1.evidence] == [
        ("registry", registry_quote.replace("110111-*******", "******-*******")),
        ("contract", landlord_quote.replace("900101-*******", "******-*******")),
    ]


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("variant", ["full", "p0"])
def test_no_visible_id_numbers_anywhere(name, variant):
    req = load(name) if variant == "full" else p0_only(name)
    leaks = [t for t in strings(build_report(req).model_dump(mode="json")) if ID_SHAPE.search(t)]
    assert leaks == []


@pytest.mark.parametrize("name", SCENARIOS)
def test_request_message_sentence_is_not_broken(name):
    message = build_report(load(name)).request_message
    assert "임대인이 보여주도록 주택임대차보호법에 정해져 있다고 알고 있습니다.\n" in message
    assert message.endswith("계약일 전에 받아볼 수 있을까요? 감사합니다.")


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic(name):
    first = build_report(load(name)).model_dump(exclude={"generated_at"})
    second = build_report(load(name)).model_dump(exclude={"generated_at"})
    assert first == second


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("variant", ["full", "p0"])
def test_no_banned_phrases(name, variant):
    req = load(name) if variant == "full" else p0_only(name)
    for text in strings(build_report(req).model_dump(mode="json")):
        for phrase in BANNED_PHRASES:
            assert phrase not in text


@pytest.mark.parametrize("name", SCENARIOS)
def test_report_round_trip(name):
    report = build_report(load(name))
    assert Report.model_validate(report.model_dump(mode="json")) == report
    assert Report.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("name", SCENARIOS)
def test_demo_mode_copy_matches_endpoint_usage(name):
    """/api/demo는 mode를 "demo"로 덮어써 돌려준다. 그 값으로 검사해도 결과가 같다."""
    req = load(name)
    again = CheckRequest.model_validate_json(req.model_copy(update={"mode": "demo"}).model_dump_json())
    assert levels(build_report(again)) == EXPECTED[name]
