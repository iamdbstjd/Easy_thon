"""계약서 변경 추적 (수정 전·후 비교) 테스트."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from app.rules import build_compare, build_report, compare, content
from app.schemas import RULE_NAMES, CheckRequest, CompareReport, CompareRequest

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"
ID_SHAPE = re.compile(r"\d{6}\s*-\s*[\d*]{7}")
TRUST = "○○부동산신탁(주)"


def load(name: str) -> CheckRequest:
    return CheckRequest.model_validate_json((DEMO_DIR / f"{name}.json").read_bytes())


def fixture() -> CompareRequest:
    return CompareRequest.model_validate_json((DEMO_DIR / "compare-C.json").read_bytes())


def compare_with(before: CheckRequest, after: CheckRequest, **kw) -> CompareReport:
    return build_compare(CompareRequest(before=before, after=after, **kw))


def c_terms() -> list[str]:
    return build_report(load("C")).amendment.terms


def by_kind(report: CompareReport, kind: str) -> list[tuple[str, str]]:
    return [(f.item, f.status) for f in report.fulfillment if f.kind == kind]


def changed(report: CompareReport) -> list[tuple]:
    return [(d.id, d.before, d.after, d.change) for d in report.rule_deltas if d.change != "그대로"]


def texts(report: CompareReport) -> list[str]:
    out = [report.headline, report.address or "", report.disclaimer]
    for o in (report.before_overall, report.after_overall):
        out += [o.title, o.message, o.unknown_note or ""]
    for f in report.fulfillment:
        out += [f.item, f.note]
    for d in report.rule_deltas:
        out += [d.name, d.after_title]
    for c in report.contract_changes:
        out += [c.field, c.before or "", c.after or ""]
    return out


# ---------------------------------------------------------------------------
# 발표용 예시 (compare-C.json)
# ---------------------------------------------------------------------------


def test_fixture_is_example_c_with_only_the_contract_fixed():
    raw = json.loads((DEMO_DIR / "compare-C.json").read_text(encoding="utf-8"))
    assert (raw["mode"], raw["today"]) == ("demo", "2026-11-14")
    req = CompareRequest.model_validate(raw)
    assert req.before == load("C")
    after = req.after
    assert after.registry == req.before.registry and after.market == req.before.market
    assert after.building == req.before.building and after.manual == req.before.manual
    assert after.contract.landlord_names == [TRUST]
    assert after.contract.special_terms == c_terms()  # 요청서의 특약 4개 그대로
    unchanged = {"landlord_names", "special_terms", "sources"}
    assert after.contract.model_dump(exclude=unchanged) == req.before.contract.model_dump(exclude=unchanged)


def test_fixture_result():
    report = build_compare(fixture())
    assert report.headline == "위험 3건 → 2건, 주의 2건 → 1건, 요청 5건 중 5건 반영"
    assert (report.rate.done, report.rate.total) == (5, 5)
    assert report.address == "경기도 용인시 수지구 죽전동 789-1 ○○파크빌 302호"
    assert (report.before_overall.title, report.after_overall.title) == ("계약 보류 권장", "계약 보류 권장")
    assert (report.after_counts.red, report.after_counts.yellow) == (2, 1)
    assert by_kind(report, "fix") == [("임대인", "반영")]
    assert by_kind(report, "term") == [(t, "반영") for t in c_terms()]
    assert [s for _, s in by_kind(report, "document")] == ["직접 확인"] * 6
    assert changed(report) == [("R1", "red", "green", "개선"), ("R12", "yellow", "green", "개선")]
    remaining = {d.id: (d.after, d.after_title) for d in report.rule_deltas if d.after in ("red", "yellow")}
    assert remaining == {
        "R2": ("red", "집이 신탁회사 소유예요"),
        "R5": ("red", "보증금이 집값에 비해 위험한 수준이에요"),
        "R8": ("yellow", "최근에 집주인이 바뀌었어요"),
    }
    assert [(c.field, c.before, c.after) for c in report.contract_changes] == [("임대인", "이○○", TRUST)] + [
        ("특약 추가", None, t) for t in c_terms()
    ]


def test_rule_deltas_cover_all_rules_in_order():
    deltas = build_compare(fixture()).rule_deltas
    assert sorted(d.id for d in deltas) == sorted(RULE_NAMES)
    assert all(d.name == RULE_NAMES[d.id] for d in deltas)
    assert [d.id for d in deltas] == ["R1", "R12", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R13"]
    assert all(d.after_title == "" for d in deltas if d.after not in ("red", "yellow"))


# ---------------------------------------------------------------------------
# 같은 계약서·악화·일부 반영
# ---------------------------------------------------------------------------


def test_same_contract_reflects_nothing():
    report = compare_with(load("C"), load("C"))
    assert (report.rate.done, report.rate.total) == (0, 5)
    assert all(d.change == "그대로" for d in report.rule_deltas)
    assert report.contract_changes == []
    assert report.headline == "위험 3건 → 3건, 주의 2건 → 2건, 요청 5건 중 0건 반영"
    assert by_kind(report, "fix") == [("임대인", "미반영")]
    assert [f.note for f in report.fulfillment if f.kind == "fix"] == ["수정 후에도 임대인이 등기부상 소유자와 달라요"]


def test_term_already_in_the_contract_is_not_counted_as_reflected():
    before = load("C")
    before.contract.special_terms = [content.TERM_SHOW_DOCUMENTS]
    report = compare_with(before, before.model_copy(deep=True))
    (docs,) = [f for f in report.fulfillment if f.item == content.TERM_SHOW_DOCUMENTS]
    assert (docs.status, docs.note) == ("미반영", "수정 전 계약서에도 있던 특약이라 새로 반영된 것은 아니에요")
    assert report.rate.done == 0


def test_worsened_case():
    before = load("A")
    after = before.model_copy(deep=True)
    after.contract.landlord_names = ["이○○"]
    after.contract.unit.ho = "303호"
    report = compare_with(before, after)
    assert changed(report) == [("R1", "green", "red", "악화"), ("R11", "green", "red", "악화")]
    assert [d.after_title for d in report.rule_deltas[:2]] == ["계약하는 사람과 집주인이 달라요", "계약서의 호수가 등기부와 달라요"]
    assert report.headline == "위험 0건 → 2건, 요청 1건 중 0건 반영"
    assert report.after_overall.title == "계약 보류 권장"
    assert [(c.field, c.before, c.after) for c in report.contract_changes] == [
        ("임대인", "김○○", "이○○"),
        ("동·호", "302호", "303호"),
    ]


def test_improved_comes_before_worsened():
    before = load("C")
    after = before.model_copy(deep=True)
    after.contract.landlord_names = [TRUST]  # R1 개선
    after.contract.unit.ho = "303호"  # R11 악화
    assert changed(compare_with(before, after)) == [("R1", "red", "green", "개선"), ("R11", "green", "red", "악화")]


def test_terms_partly_reflected():
    before = load("C")
    after = before.model_copy(deep=True)
    after.contract.landlord_names = [TRUST]
    after.contract.special_terms = [
        "임대인은 근저당 등 담보를 새로 잡지 않기로 한다.",  # 문안이 달라도 핵심어(담보)가 있으면 반영
        "임대인은 계약할 때 납세증명서를 보여 준다.",
    ]
    report = compare_with(before, after)
    assert by_kind(report, "term") == [
        (content.TERM_NO_NEW_MORTGAGE, "반영"),
        (content.TERM_JEONSE_GUARANTEE, "미반영"),
        (content.TERM_SHOW_DOCUMENTS, "반영"),
        (content.TERM_TRUST_CONSENT, "미반영"),
    ]
    assert [f.note for f in report.fulfillment if f.status == "미반영"] == ["수정 후 계약서 특약에 없어요"] * 2
    assert (report.rate.done, report.rate.total) == (3, 5)
    assert report.headline.endswith("요청 5건 중 3건 반영")


def test_removal_clause_does_not_count_as_no_new_mortgage():
    before = load("B")
    after = before.model_copy(deep=True)
    after.contract.special_terms = ["임대인은 잔금일까지 근저당권을 말소한다."]
    report = compare_with(before, after)
    terms = dict(by_kind(report, "term"))
    assert terms[content.TERM_NO_NEW_MORTGAGE] == "미반영"  # 말소 약속의 "저당"은 담보 설정 금지가 아니다
    assert terms["임대인은 잔금일까지 등기부상 근저당권(채권최고액 1억 2,000만 원)을 말소한다."] == "반영"


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_documents_are_shown_but_not_counted(name):
    report = compare_with(load(name), load(name))
    amendment = build_report(load(name)).amendment
    documents = [f for f in report.fulfillment if f.kind == "document"]
    assert [f.item for f in documents] == amendment.documents
    assert all((f.status, f.note) == ("직접 확인", "계약서로는 확인할 수 없어요. 받았는지 직접 확인하세요.") for f in documents)
    assert report.rate.total == len(amendment.fixes) + len(amendment.terms)


def test_address_fix_notes():
    before = load("A")
    before.contract.unit.ho = "303호"
    before.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 303호"
    after = load("A")
    report = compare_with(before, after)
    assert [(f.item, f.status, f.note) for f in report.fulfillment if f.kind == "fix"] == [
        ("소재지", "반영", "수정 후 소재지·호수가 등기부와 같아요")
    ]
    assert report.headline == "위험 1건 → 0건, 요청 2건 중 1건 반영"


def test_headline_leaves_out_zero_to_zero_parts():
    from app.schemas import FulfillmentRate

    a = build_report(load("A"))  # 위험·주의 0건
    assert compare.headline_of(a, a, FulfillmentRate(done=0, total=1)) == "요청 1건 중 0건 반영"
    # 요청서에는 "항상" 특약이 있어 실제로는 요청이 0건일 수 없지만, 모두 0이어도 빈 문장을 내지 않는다
    assert compare.headline_of(a, a, FulfillmentRate(done=0, total=0)) == "수정 전·후 모두 위험·주의 신호와 요청 항목이 없어요"
    c = build_report(load("C"))
    assert compare.headline_of(a, c, FulfillmentRate(done=0, total=1)) == "위험 0건 → 3건, 주의 0건 → 2건, 요청 1건 중 0건 반영"


# ---------------------------------------------------------------------------
# 기준일·문구·결정성
# ---------------------------------------------------------------------------


def test_today_and_mode_are_shared_by_both_sides():
    req = fixture()
    req.today = None
    req.before.today = dt.date(2026, 11, 20)
    req.after.today = dt.date(2027, 1, 1)  # 수정 후 입력의 today는 쓰지 않는다
    req.mode = "live"
    report = build_compare(req)
    assert (report.today, report.mode) == (dt.date(2026, 11, 20), "live")
    req.before.today = None
    from app.rules.common import today_kst

    assert build_compare(req).today == today_kst()


@pytest.mark.parametrize("side", ["before", "after"])
def test_compare_needs_both_contracts(side):
    from pydantic import ValidationError

    sides = {"before": load("C"), "after": load("C")}
    sides[side] = sides[side].model_copy(update={"contract": None})
    with pytest.raises(ValidationError, match="수정 전·후 모두 계약서가 있어야 비교할 수 있어요."):
        CompareRequest(**sides)
    raw = json.loads((DEMO_DIR / "compare-C.json").read_text(encoding="utf-8"))
    raw[side]["contract"] = None
    with pytest.raises(ValidationError):
        CompareRequest.model_validate(raw)


def test_no_id_numbers_or_banned_phrases():
    req = fixture()
    req.before.contract.landlord_names = ["이○○ 900101-1234567"]
    req.after.contract.landlord_names = ["○○부동산신탁(주) 110111-1xxxxxx"]
    req.after.contract.special_terms.append("임대인(900101-1234567)은 관리비를 따로 받지 않는다.")
    report = build_compare(req)
    for text in texts(report):
        assert not ID_SHAPE.search(text), text
        for phrase in content.BANNED_PHRASES:
            assert phrase not in text
    assert ("임대인", "이○○", TRUST) in [(c.field, c.before, c.after) for c in report.contract_changes]


def test_deterministic_and_round_trip():
    first, second = build_compare(fixture()), build_compare(fixture())
    assert first.model_dump(exclude={"generated_at"}) == second.model_dump(exclude={"generated_at"})
    assert CompareReport.model_validate_json(first.model_dump_json()) == first
    assert first.generated_at.utcoffset() == dt.timedelta(hours=9)
    assert first.disclaimer == content.DISCLAIMER


def test_severity_order():
    s = compare.SEVERITY
    assert s["red"] > s["yellow"] > s["unknown"] > s["green"]


def test_fix_not_reflected_unless_rule_turns_green():
    before = load("C")
    co_owned = before.model_copy(deep=True)
    co_owned.registry.gapgu[-1].holders = [TRUST, "박○○"]  # 수정 후 등기부 기준으로도 공동소유 → R1 🟡
    co_owned.contract.landlord_names = [TRUST]
    before_co = co_owned.model_copy(deep=True)
    before_co.contract.landlord_names = ["이○○"]
    report = compare_with(before_co, co_owned)
    assert [(f.status, f.note) for f in report.fulfillment if f.kind == "fix"] == [
        ("미반영", "수정 후에도 공동 소유자 모두의 동의를 계약서로 확인할 수 없어요")
    ]
    no_name = before.model_copy(deep=True)
    no_name.contract.landlord_names = []  # R1 ⚪
    report = compare_with(before, no_name)
    assert [(f.status, f.note) for f in report.fulfillment if f.kind == "fix"] == [("미반영", "수정 후 결과를 확인하지 못했어요")]


def test_after_side_uses_the_shared_today():
    req = CompareRequest(before=load("C"), after=load("C"))
    req.after.today = dt.date(2027, 1, 1)  # 따로 쓰면 R13(오래된 등기부)이 🟡로 바뀐다
    assert all(d.change == "그대로" for d in build_compare(req).rule_deltas)


def test_fulfillment_labels():
    report = build_compare(fixture())
    assert [(f.kind, f.label) for f in report.fulfillment] == [
        ("fix", "임대인"),
        ("term", "담보 설정 금지"),
        ("term", "반환보증 불가 시 무효"),
        ("term", "납세증명서·확정일자 제시"),
        ("term", "신탁회사 동의서"),
        ("document", "확정일자 부여현황"),
        ("document", "국세·지방세 납세증명서"),
        ("document", "신탁원부"),
        ("document", "신탁회사(수탁자)의 임대 동의서"),
        ("document", "위임장"),
        ("document", "인감증명서"),
    ]


def test_mortgage_and_address_labels():
    b = compare_with(load("B"), load("B"))
    assert [f.label for f in b.fulfillment if f.kind == "term"] == [
        "담보 설정 금지",
        "근저당 말소",
        "납세증명서·확정일자 제시",
    ]
    before = load("A")
    before.contract.unit.ho = "303호"
    a = compare_with(before, load("A"))
    assert [(f.item, f.label) for f in a.fulfillment if f.kind == "fix"] == [("소재지", "소재지")]


def test_unknown_term_gets_a_generic_label():
    term = "임대인은 관리비를 받지 않는다."
    assert compare._term_kind(term) is None
    row = compare._term_fulfillment(term, load("C").contract, load("C").contract)
    assert (row.label, row.status) == ("추가 특약", "미반영")
