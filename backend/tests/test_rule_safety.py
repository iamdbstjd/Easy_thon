"""규칙 엔진 안전장치 테스트: 느려지는 입력, 날짜 끝값, 모르는 것을 🟢로 말하지 않기, 재확인·비교의 경계 사례.

입력 검증(크기·날짜 범위)과 별개로 규칙 엔진도 스스로 버티는지 본다. 그래서 일부 입력은 검증을 건너뛰어 만든다.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pytest

from app.rules import build_compare, build_recheck, build_report, compare, engine, recheck
from app.rules.common import (
    _DONG_AT_END,
    fmt_money,
    _HO_IN_ADDR,
    _JIBUN_RE,
    _ROAD_RE,
    KST as KST_ZONE,
    AddressCore,
    address_has_core,
    is_floor_line,
    jibun_core,
    line_has_floor,
    road_core,
    tidy_address,
    to_kst,
    unit_in_address,
)
from app.schemas import CheckRequest, CompareRequest, Entry, RecheckRequest

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"
KST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.date(2026, 11, 29)
PROHIBITION = "임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다. 위반 시 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다."
REMOVAL = "임대인은 잔금일까지 등기부상 근저당권을 말소한다."
FAST = 0.5  # 초


def load(name: str) -> CheckRequest:
    return CheckRequest.model_validate_json((DEMO_DIR / f"{name}.json").read_bytes())


def entry(rank, purpose, received_at, holders=("○○은행",), amount=None, cause=None, cancelled=False):
    return Entry(
        rank=rank,
        purpose=purpose,
        received_at=received_at,
        cause=cause,
        holders=list(holders),
        amount=amount,
        is_cancelled=cancelled,
        page=2,
        source_text=f"{rank} {purpose}",
    )


def fresh_a(today=TODAY) -> RecheckRequest:
    """예시 A의 계약서와, 오늘 다시 뗀 (내용은 같은) 등기부."""
    a = load("A")
    a.registry.viewed_at = dt.datetime(today.year, today.month, today.day, 10, 0, tzinfo=KST)
    return RecheckRequest(registry=a.registry, contract=a.contract, today=today, mode="demo")


def levels(report) -> dict[str, str]:
    return {r.id: r.level for r in report.results}


def timed(fn):
    start = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - start


# ---------------------------------------------------------------------------
# 긴 입력에서 느려지지 않는다 (정규식이 길이에 비례해서만 일한다)
# ---------------------------------------------------------------------------

N = 50_000


@pytest.mark.parametrize(
    "name, fn",
    [
        # 길이 제한을 건너뛰어 정규식 자체가 선형인지 본다
        ("등기목적 숫자열", lambda: engine._SEGMENT_SPLIT.split("1" * N)),
        ("등기목적 N번 반복", lambda: engine._SEGMENT_SPLIT.split("1번" * (N // 2) + "지분")),
        ("공유자 지분 이전", lambda: engine._SHARE_SELLER.search("1" * N + "지분전부이전")),
        ("지번 정규식 한글열", lambda: _JIBUN_RE.search("가" * N)),
        ("지번 정규식 한글·숫자", lambda: _JIBUN_RE.search("나1" * (N // 2))),
        ("도로명 정규식", lambda: _ROAD_RE.search("나1" * (N // 2))),
        ("호수 정규식 숫자열", lambda: list(_HO_IN_ADDR.finditer("1" * N + "x"))),
        ("동 정규식", lambda: _DONG_AT_END.search("1동 " * (N // 3) + "x")),
        ("등기목적 (길이 제한 포함)", lambda: engine.purpose_segments(Entry.model_construct(rank="1", purpose="1" * N))),
        ("주소 정리 공백열", lambda: tidy_address(" " * N + "x")),
        ("지번 핵심", lambda: jibun_core("가" * N)),
        ("도로명 핵심", lambda: road_core("로" * N)),
        ("주소의 동·호", lambda: unit_in_address("1" * N + "x")),
        ("주소 비교", lambda: address_has_core("가" * N, AddressCore("jibun", "가" * 200 + "동", "1"))),
        ("층별 줄 숫자열", lambda: is_floor_line("1" * N)),
        ("층 찾기 숫자열", lambda: line_has_floor("지" + "1" * N, (True, 3))),
    ],
)
def test_long_text_is_handled_in_linear_time(name, fn):
    _, elapsed = timed(fn)
    assert elapsed < FAST, f"{name}: {elapsed:.2f}s"


def test_long_fields_do_not_freeze_the_whole_report():
    """검증을 건너뛴 긴 값 (예전에는 수십 초 걸리던 입력)."""
    req = load("A")
    req.registry.gapgu[1].purpose = "1" * 8000  # 예전 9.8초 (필드에 직접 넣어 입력 검증을 건너뛴다)
    req.registry.address_jibun = "가" * 20000  # 예전 16초
    req.contract.address = "1" * 20000 + "x"  # 예전 30초
    req.registry.building_use_lines = ["1" * N]
    report, elapsed = timed(lambda: build_report(req))
    assert elapsed < FAST, f"{elapsed:.2f}s"
    r11 = next(r for r in report.results if r.id == "R11")
    assert r11.level == "unknown" and r11.unknown_reason == "주소가 너무 길어 주소로 읽지 못했어요"


def test_largest_allowed_lists_stay_fast():
    """항목 500개·권리자 50명·특약 100개 (입력 검증이 허용하는 끝값 근처)."""
    owners = [entry("1", "소유권보존", dt.date(2010, 1, 1), ["김○○"])] + [
        entry(str(i + 2), "소유권일부이전, 신탁", dt.date(2020, 1, 1), [f"신탁{i}-{j}" for j in range(50)])
        for i in range(499)
    ]
    check = load("A")
    check.registry.gapgu = owners
    _, elapsed = timed(lambda: build_report(check))
    assert elapsed < 2, f"check {elapsed:.2f}s"

    req = fresh_a()
    req.registry.eulgu = [entry("1", "근저당권설정", dt.date(2024, 1, 1), amount=1)] + [
        entry(f"1-{i}", "1번근저당권변경", dt.date(2026, 11, 20), holders=[], amount=i + 2) for i in range(499)
    ]
    req.contract.special_terms = ["임대인은 잔금일까지 근저당권을 말소하고 담보권을 설정하지 않는다."] * 100
    report, elapsed = timed(lambda: build_recheck(req))
    assert elapsed < 2, f"recheck {elapsed:.2f}s"  # 예전 45초
    assert report.overall.title == "잔금 보류 권장"


# ---------------------------------------------------------------------------
# 날짜 끝값
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, date",
    [
        (dt.datetime(1, 1, 1, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=14))), dt.date(1, 1, 1)),
        (dt.datetime(9999, 12, 31, 20, 0, tzinfo=dt.timezone.utc), dt.date(9999, 12, 31)),
        (dt.datetime(9999, 12, 31, 23, 59, 59, tzinfo=dt.timezone(dt.timedelta(hours=-12))), dt.date(9999, 12, 31)),
    ],
)
def test_to_kst_does_not_overflow(value, date):
    local = to_kst(value)
    assert local.date() == date
    assert local.tzinfo is KST_ZONE


@pytest.mark.parametrize(
    "viewed",
    [
        dt.datetime(1, 1, 1, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=14))),
        dt.datetime(9999, 12, 31, 20, 0, tzinfo=dt.timezone.utc),
    ],
)
def test_extreme_view_times_do_not_crash_recheck_or_check(viewed):
    req = RecheckRequest.model_validate_json((DEMO_DIR / "recheck-A.json").read_bytes())
    req.baseline_viewed_at = viewed  # 검증을 건너뛴 값
    req.registry.viewed_at = viewed
    build_recheck(req)
    check = load("A")
    check.registry.viewed_at = viewed
    build_report(check)


# ---------------------------------------------------------------------------
# 재확인: 등기부로 계약 후 변화를 볼 수 없으면 "새로 생긴 권리 없음"이라고 하지 않는다
# ---------------------------------------------------------------------------


def test_recheck_with_empty_registry_is_incomplete():
    req = fresh_a()
    req.registry.gapgu, req.registry.eulgu = [], []
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert report.overall.message == (
        "등기부 갑구 항목을 확인하지 못했어요. 잔금을 보내기 전에 오늘 날짜로 등기부를 다시 떼어 올려 확인하세요."
    )
    assert [(t.status, t.level) for t in report.term_checks] == [("확인 필요", "unknown")]
    assert report.actions == ["잔금을 보내기 전에 오늘 날짜로 등기부를 다시 떼어 올려 확인하세요."]


def test_recheck_with_empty_gapgu_still_reports_a_new_mortgage():
    req = fresh_a()
    req.registry.gapgu = []
    req.registry.eulgu = [entry("1", "근저당권설정", dt.date(2026, 11, 27), amount=120_000_000)]
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("red", "잔금 보류 권장")
    assert [(t.status, t.level) for t in report.term_checks] == [("위반", "red")]


def test_recheck_after_move_in_asks_for_a_new_registry_without_mentioning_the_balance():
    req = fresh_a(today=dt.date(2026, 12, 5))
    req.registry.gapgu = []
    report = build_recheck(req)
    assert report.overall.title == "확인 미완료"
    assert report.overall.message.endswith("오늘 날짜로 등기부를 다시 떼어 올려 확인하세요.")
    assert "잔금" not in report.overall.message


def test_recheck_with_unreadable_parts_is_incomplete():
    req = fresh_a()
    req.registry.unreadable = ["을구 2쪽 하단이 흐림", "  ", "갑구 3쪽 누락 (소유자 850315-1234567 옆)"]
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert report.overall.message.startswith(
        "등기부에서 읽지 못한 부분이 있어요(을구 2쪽 하단이 흐림, 갑구 3쪽 누락 (소유자 ******-******* 옆))."
    )
    assert [t.status for t in report.term_checks] == ["확인 필요"]


# ---------------------------------------------------------------------------
# 재확인: 지금 소유자·신탁·주소를 계약서와 맞춰 본다 (계약 전부터 있던 문제도)
# ---------------------------------------------------------------------------


def test_recheck_flags_an_owner_who_is_not_the_landlord_even_before_the_contract():
    req = fresh_a()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 11, 13), ["박○○"], cause="매매"))  # 계약 전날
    report = build_recheck(req)
    assert report.changes == []  # 계약 후 새로 생긴 권리는 아니다
    assert (report.overall.level, report.overall.title) == ("red", "잔금 보류 권장")
    assert report.overall.message == (
        "등기부상 소유자는 박○○인데, 계약서의 임대인은 김○○이에요. 해결되기 전에는 잔금을 미루는 걸 권해요."
    )
    assert report.actions == [recheck.ACTION_OWNER, recheck.ACTION_HOLD_STANDING]
    check = load("A")
    check.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 11, 13), ["박○○"], cause="매매"))
    assert build_report(check).overall.title == "계약 보류 권장"  # 검사와 같은 결론


def test_owner_change_after_the_contract_is_listed_once():
    req = fresh_a()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 11, 20), ["박○○"], cause="매매"))
    report = build_recheck(req)
    assert [(c.level, c.note) for c in report.changes] == [("red", "계약 후 집주인이 바뀌었어요")]
    assert report.overall.message == "계약 후 새로 생긴 권리 1건이 있어요. 해결되기 전에는 잔금을 미루는 걸 권해요."


def test_recheck_flags_a_trust_owner_even_when_the_landlord_is_the_trustee():
    c = load("C")
    c.registry.viewed_at = dt.datetime(2026, 11, 29, 10, 0, tzinfo=KST)
    req = RecheckRequest(registry=c.registry, contract=c.contract, today=TODAY)
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("red", "잔금 보류 권장")
    assert "등기부상 소유권이 ○○부동산신탁(주)에게 넘어가 있어요." in report.overall.message
    assert recheck.ACTION_TRUST in report.actions and recheck.ACTION_OWNER in report.actions
    fixed = CompareRequest.model_validate_json((DEMO_DIR / "compare-C.json").read_bytes()).after.contract
    report = build_recheck(RecheckRequest(registry=c.registry, contract=fixed, today=TODAY))
    assert report.overall.level == "red"  # 임대인을 신탁회사로 고쳐도 신탁은 남는다
    assert recheck.ACTION_TRUST in report.actions and recheck.ACTION_OWNER not in report.actions


def test_recheck_with_another_buildings_registry_is_not_green():
    req = fresh_a()
    req.registry.address_jibun = "경기도 용인시 수지구 죽전동 999-9"
    req.registry.address_road = "경기도 용인시 수지구 죽전로 99"
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert report.overall.message.startswith("계약서 주소에서 등기부의 지번이나 도로명을 찾지 못해")
    assert [t.status for t in report.term_checks] == ["확인 필요"]


def test_recheck_with_another_units_registry_is_red():
    req = fresh_a()
    req.registry.unit.ho = "303호"
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("red", "잔금 보류 권장")
    assert report.overall.message.startswith("등기부는 303호, 계약서는 302호예요.")
    assert report.actions[0] == recheck.ACTION_UNIT


def test_recheck_without_landlord_names_is_incomplete():
    req = fresh_a()
    req.contract.landlord_names = []
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert report.overall.message.startswith("계약서 임대인과 등기부상 지금 소유자를 맞춰 보지 못했어요.")
    assert [(t.status, t.level) for t in report.term_checks] == [("이행", "green")]  # 등기부는 믿을 수 있다


# ---------------------------------------------------------------------------
# 재확인: 부기 등기·표시 변경·근저당 변경
# ---------------------------------------------------------------------------


def test_owner_address_change_is_not_a_new_right():
    req = fresh_a()
    req.registry.gapgu.append(entry("2-1", "2번등기명의인표시변경", dt.date(2026, 11, 20), [], cause="전거"))
    report = build_recheck(req)
    assert report.changes == []
    assert report.overall.title == "새로 생긴 권리 없음"


def test_change_to_a_mortgage_from_before_the_contract_is_yellow():
    req = fresh_a()
    req.contract.special_terms.append(REMOVAL)
    req.registry.eulgu = [
        entry("1", "근저당권설정", dt.date(2024, 1, 10), amount=60_000_000),
        entry("1-1", "1번근저당권이전", dt.date(2026, 11, 20), ["△△캐피탈"], cause="확정채권양도"),
    ]
    report = build_recheck(req)
    assert [(c.rank, c.level, c.note) for c in report.changes] == [
        ("1-1", "yellow", "기존 권리 변경: 무엇이 바뀌었는지 원문을 확인하세요")
    ]
    assert [(t.status, t.level) for t in report.term_checks] == [("이행", "green"), ("미이행", "yellow")]
    assert report.overall.title == "추가 확인 필요"


@pytest.mark.parametrize(
    "amount, level, note, term",
    [
        (150_000_000, "red", "기존 근저당의 채권최고액이 늘었어요", ("위반", "red")),
        (50_000_000, "yellow", "기존 권리 변경: 무엇이 바뀌었는지 원문을 확인하세요", ("이행", "green")),
        (None, "yellow", "기존 권리 변경: 무엇이 바뀌었는지 원문을 확인하세요", ("확인 필요", "unknown")),
    ],
)
def test_raising_an_old_mortgage_breaks_the_no_mortgage_clause(amount, level, note, term):
    req = fresh_a()
    req.registry.eulgu = [
        entry("1", "근저당권설정", dt.date(2024, 1, 10), amount=60_000_000),
        entry("1-1", "1번근저당권변경", dt.date(2026, 11, 20), [], amount=amount, cause="변경계약"),
    ]
    report = build_recheck(req)
    assert [(c.level, c.note) for c in report.changes] == [(level, note)]
    (check,) = report.term_checks
    assert (check.status, check.level) == term
    if amount == 150_000_000:
        assert check.note == "계약 후 2026년 11월 20일에 기존 근저당권의 채권최고액이 6,000만 원에서 1억 5,000만 원으로 늘었어요."
        assert report.overall.title == "잔금 보류 권장"


def test_refinanced_mortgage_is_not_reported_as_no_mortgage_left():
    req = fresh_a()
    req.contract.special_terms = [REMOVAL]
    req.registry.eulgu = [
        entry("1", "근저당권설정", dt.date(2024, 1, 10), amount=60_000_000, cancelled=True),
        entry("2", "1번근저당권설정등기말소", dt.date(2026, 11, 20), [], cause="해지"),
        entry("3", "근저당권설정", dt.date(2026, 11, 20), ["△△캐피탈"], amount=150_000_000),
    ]
    report = build_recheck(req)
    (check,) = report.term_checks
    assert (check.status, check.level) == ("미이행", "yellow")
    assert check.note == "잔금일까지 말소해야 해요. 계약 후 설정된 근저당권(채권최고액 1억 5,000만 원)이 남아 있어요."
    assert "남아 있는 근저당이 없어요" not in check.note
    req.today = dt.date(2026, 12, 1)
    (check,) = build_recheck(req).term_checks
    assert (check.status, check.level) == ("미이행", "red")
    assert check.note == "잔금일인데 계약 후 설정된 근저당권(채권최고액 1억 5,000만 원)이 말소되지 않았어요."


# ---------------------------------------------------------------------------
# 재확인: 특약은 계약일 기준, 계약 때 본 등기부는 새 권리를 가려낼 때만
# ---------------------------------------------------------------------------


def early_view(received_at):
    """계약 때 본 등기부는 11-10, 계약일은 11-14."""
    req = fresh_a()
    req.baseline_viewed_at = dt.datetime(2026, 11, 10, 10, 0, tzinfo=KST)
    req.contract.special_terms = [PROHIBITION, REMOVAL]
    req.registry.eulgu = [entry("1", "근저당권설정", received_at, amount=120_000_000)]
    return build_recheck(req)


def test_mortgage_between_the_viewed_registry_and_the_contract():
    report = early_view(dt.date(2026, 11, 12))
    assert report.baseline_date == dt.date(2026, 11, 10)
    assert [(c.level, c.note) for c in report.changes] == [("red", "계약 때 본 등기부 뒤, 계약 전에 생김")]
    statuses = [(t.status, t.level) for t in report.term_checks]
    assert statuses == [("이행", "green"), ("미이행", "yellow")]  # 계약 전 근저당은 금지 특약 위반이 아니다
    assert report.term_checks[1].note.startswith("잔금일까지 말소해야 해요. 계약 전부터 있던 근저당권")
    assert report.overall.message.startswith("계약 때 본 등기부 뒤에 생긴 권리 1건이 있어요.")
    assert "계약 후" not in report.overall.message


@pytest.mark.parametrize(
    "received, note",
    [
        (dt.date(2026, 11, 10), "계약 때 본 등기부를 뗀 날 접수: 그 등기부에 있었는지 확인하세요"),
        (dt.date(2026, 11, 14), "계약 당일 접수: 계약 때 본 등기부 뒤에 생김"),
        (dt.date(2026, 11, 20), "계약 후 새로 생김"),
    ],
)
def test_notes_follow_the_viewed_day_and_the_contract_day(received, note):
    report = early_view(received)
    assert [c.note for c in report.changes] == [note]


def test_mortgage_after_the_contract_still_breaks_the_clause_with_an_early_view():
    report = early_view(dt.date(2026, 11, 20))
    assert [(t.status, t.level) for t in report.term_checks][0] == ("위반", "red")


# ---------------------------------------------------------------------------
# 검사: 등기부 종류를 모를 때 동·호·층을 건너뛰고 🟢로 말하지 않는다
# ---------------------------------------------------------------------------


def test_unknown_registry_type_with_a_unit_is_compared_like_a_collective_building():
    req = load("A")
    req.registry.registry_type = None
    req.contract.unit.ho = "303호"
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 303호"
    report = build_report(req)
    r11 = next(r for r in report.results if r.id == "R11")
    assert (r11.level, r11.summary) == (
        "red",
        "등기부는 302호, 계약서는 303호예요. 전입신고 주소가 등기와 다르면 대항력을 인정받지 못할 수 있어요.",
    )
    assert [(row.level, row.note) for row in report.comparison if row.rule_id == "R11"] == [("red", "호수 다름")]


def test_unknown_registry_type_without_a_unit_is_not_green():
    req = load("A")
    req.registry.registry_type = None
    req.registry.unit.ho = None
    r11 = next(r for r in build_report(req).results if r.id == "R11")
    assert r11.level == "unknown" and "동·호수를 비교하지 못했어요" in r11.unknown_reason


def test_unknown_registry_type_uses_my_floor_for_the_use_check():
    req = load("A")
    req.building = None
    req.registry.registry_type = None
    req.registry.unit.ho, req.registry.unit.floor = "101호", "1층"
    req.registry.building_use_lines = [
        "철근콘크리트구조 4층 공동주택 및 근린생활시설",
        "1층 제2종근린생활시설(사무소) 66.20㎡",
        "2층 다세대주택 112.30㎡",
    ]
    req.contract.unit.ho = "101호"
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 101호"
    assert levels(build_report(req))["R10"] == "yellow"  # 예전에는 건물 전체를 보고 🟢
    req.registry.unit.ho = req.registry.unit.floor = None
    req.contract.unit.ho = None
    assert levels(build_report(req))["R10"] == "unknown"  # 내 층을 모르고 섞인 건물이면 ⚪


# ---------------------------------------------------------------------------
# 검사: 등기부에 읽지 못한 부분이 있으면 "큰 위험 신호 없음"이라고 하지 않는다
# ---------------------------------------------------------------------------


def test_unreadable_registry_parts_block_a_green_banner():
    req = load("A")
    req.registry.unreadable = ["을구 2쪽 하단이 흐림", "갑구 3쪽 누락"]
    overall = build_report(req).overall
    assert (overall.level, overall.title) == ("yellow", "확인 미완료")
    assert overall.message == (
        "위험 신호는 찾지 못했지만, 등기부에서 읽지 못한 부분이 있어요(을구 2쪽 하단이 흐림, 갑구 3쪽 누락). "
        "그 부분이 잘 보이는 등기부를 다시 올려 검사하세요."
    )
    assert overall.unknown_note == "등기부에서 읽지 못한 부분 2곳"


def test_unreadable_parts_are_added_to_other_banners():
    req = load("C")
    req.registry.unreadable = ["1쪽", "2쪽", "3쪽", "4쪽", "아주 긴 설명 " * 10]
    overall = build_report(req).overall
    assert overall.title == "계약 보류 권장"
    assert overall.message.endswith(" 등기부에서 읽지 못한 부분도 있어요(1쪽, 2쪽, 3쪽 외 2곳).")
    assert overall.unknown_note == "등기부에서 읽지 못한 부분 5곳"
    req.registry.unreadable = ["", "   "]  # 빈 값은 없는 것으로 본다
    assert build_report(req).overall.message == build_report(load("C")).overall.message


# ---------------------------------------------------------------------------
# 검사: 끝난 신탁은 신탁등기로 보지 않는다
# ---------------------------------------------------------------------------


def with_gapgu(*rows) -> CheckRequest:
    req = load("A")
    req.registry.gapgu += list(rows)
    return req


@pytest.mark.parametrize(
    "rows",
    [
        [
            entry("3", "소유권이전, 신탁", dt.date(2023, 1, 10), ["○○부동산신탁(주)"], cause="신탁"),
            entry("4", "소유권이전, 3번신탁등기말소", dt.date(2024, 5, 2), ["김○○"], cause="신탁재산의귀속"),
        ],
        [
            entry("3", "소유권이전", dt.date(2023, 1, 10), ["○○부동산신탁(주)"], cause="신탁"),
            entry("3", "신탁", dt.date(2023, 1, 10), []),
            entry("4", "소유권이전", dt.date(2024, 5, 2), ["김○○"], cause="신탁재산의귀속"),
            entry("4", "3번신탁등기말소", dt.date(2024, 5, 2), [], cause="신탁재산의귀속"),
        ],
        [  # 말소 기록 없이 신탁재산의귀속으로 소유권만 돌아온 경우
            entry("3", "소유권이전", dt.date(2023, 1, 10), ["○○부동산신탁(주)"], cause="신탁"),
            entry("4", "소유권이전", dt.date(2024, 5, 2), ["김○○"], cause="신탁재산의귀속"),
        ],
    ],
)
def test_ended_trust_is_not_flagged(rows):
    report = build_report(with_gapgu(*rows))
    assert levels(report)["R2"] == "green"
    assert levels(report)["R1"] == "green"
    assert "신탁원부" not in report.amendment.documents


@pytest.mark.parametrize(
    "rows",
    [
        [entry("3", "소유권이전, 신탁", dt.date(2023, 1, 10), ["김○○"], cause="신탁")],  # 지금 소유권이 신탁
        [entry("3", "신탁", dt.date(2023, 1, 10), [])],  # 뒤에 소유권이 다시 넘어가지 않았다
        [  # 다른 순위의 신탁이 말소됐다고 이 신탁이 끝난 것은 아니다
            entry("3", "소유권이전, 신탁", dt.date(2023, 1, 10), ["김○○"], cause="신탁"),
            entry("4", "1번신탁등기말소", dt.date(2024, 5, 2), [], cause="해지"),
        ],
    ],
)
def test_current_trust_is_still_flagged(rows):
    assert levels(build_report(with_gapgu(*rows)))["R2"] == "red"


# ---------------------------------------------------------------------------
# 특약 종류: 검사(R12)·재확인·비교가 같은 정의를 쓴다
# ---------------------------------------------------------------------------

CLAUSES = [
    (PROHIBITION, True, False),
    ("임대인은 근저당 등 담보를 새로 잡지 않기로 한다.", True, False),
    ("임대인은 잔금일까지 추가 대출을 받지 않는다.", True, False),
    ("임대인은 잔금일까지 등기부상 담보권(근저당권)을 모두 말소한다.", False, True),
    ("임대인은 잔금일까지 근저당권을 말소하고, 잔금일 다음 날까지 담보권을 설정하지 않는다.", True, True),
    ("임대인은 임차인이 전세보증금 반환채권을 담보로 전세자금대출을 받는 데 협조한다.", False, False),
    ("임차인이 전세자금대출을 받지 못하면 계약을 무효로 한다.", False, False),
    ("반려동물은 키우지 않는다.", False, False),
    # 임차인의 의무는 임대인의 담보 설정 금지가 아니다
    ("임차인은 임대인의 동의 없이 임차권에 질권을 설정할 수 없다.", False, False),
    ("임차인은 임대인 동의 없이 전대하거나 담보로 제공할 수 없다.", False, False),
    ("임대인 동의 없이 임차권을 담보로 제공할 수 없다.", False, False),
    ("임차인은 계약이 끝나면 임차권등기를 말소한다.", False, False),
    # 임대인의 금지 약속은 임차인 대출 협조 문구가 함께 있어도 금지 특약이다
    ("임대인은 담보 설정 등 권리 변동을 하지 않으며, 임차인의 전세자금대출에 협조한다.", True, False),
    ("임대인은 잔금일 다음 날까지 근저당권 등 담보권 설정을 하지 않고 임차인의 전입신고에 협조한다.", True, False),
    ("임대인은 잔금일 다음 날까지 담보권을 설정하거나 매도하지 않는다. 임차인의 전세대출 실행에 협조한다.", True, False),
    ("갑(임대인)은 잔금일까지 담보권을 설정하지 않는다.", True, False),
    ("을(임차인)은 담보권을 설정하지 않는다.", False, False),
    ("임대인이 동의하지 않는 한 임차인은 임차권을 담보로 제공하지 않는다.", False, False),
    ("임대인은 임차인이 전세자금대출을 받지 못하면 계약금을 돌려준다.", False, False),
    ("임대인은 잔금 후 근저당을 설정하면 임차인에게 알린다.", False, False),  # 금지가 아니다
    ("잔금일까지 담 보 제공 금지.", True, False),
]


@pytest.mark.parametrize("clause, prohibition, removal", CLAUSES)
def test_one_definition_of_protective_clauses(clause, prohibition, removal):
    assert engine.is_prohibition_clause(clause) is prohibition
    assert engine.is_removal_clause(clause) is removal
    assert recheck._is_prohibition(clause) is prohibition
    assert compare._has_kind(clause, compare.KIND_NO_NEW_MORTGAGE) is prohibition
    assert compare._has_kind(clause, compare.KIND_CLEAR_MORTGAGE) is removal
    req = load("A")
    req.contract.special_terms = [clause]
    assert levels(build_report(req))["R12"] == ("green" if prohibition or removal else "yellow")


def test_tenant_loan_clause_is_not_counted_as_reflected():
    before = load("C")
    after = before.model_copy(deep=True)
    after.contract.special_terms = ["임대인은 임차인이 전세보증금 반환채권을 담보로 전세자금대출을 받는 데 협조한다."]
    report = build_compare(CompareRequest(before=before, after=after))
    assert dict((f.label, f.status) for f in report.fulfillment if f.kind == "term")["담보 설정 금지"] == "미반영"
    assert all(d.change == "그대로" for d in report.rule_deltas)


def test_numbering_and_final_period_do_not_make_a_new_clause():
    before = load("A")
    before.contract.special_terms.append("임대인은 계약 체결 시 국세·지방세 납세증명서와 확정일자 부여현황을 제시한다.")
    after = before.model_copy(deep=True)
    after.contract.special_terms = [f"{i}. " + t.rstrip(".") for i, t in enumerate(before.contract.special_terms, 1)]
    report = build_compare(CompareRequest(before=before, after=after))
    assert report.contract_changes == []
    assert report.rate.done == 0


# ---------------------------------------------------------------------------
# 비교: ⚪로 바뀐 것은 개선이 아니다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "before, after, change",
    [
        ("red", "unknown", "확인 못 함"),
        ("yellow", "unknown", "확인 못 함"),
        ("green", "unknown", "확인 못 함"),
        ("unknown", "unknown", "그대로"),
        ("unknown", "green", "개선"),
        ("unknown", "red", "악화"),
        ("red", "yellow", "개선"),
        ("green", "yellow", "악화"),
    ],
)
def test_change_of(before, after, change):
    assert compare.change_of(before, after) == change


def test_landlord_removed_from_the_contract_is_not_an_improvement():
    req = CompareRequest.model_validate_json((DEMO_DIR / "compare-C.json").read_bytes())
    req.after.contract = req.before.contract.model_copy(deep=True)
    req.after.contract.landlord_names = []
    req.after.contract.sources.landlord = None
    report = build_compare(req)
    assert [(d.id, d.before, d.after, d.change) for d in report.rule_deltas if d.change != "그대로"] == [
        ("R1", "red", "unknown", "확인 못 함")
    ]
    assert report.headline == "위험 3건 → 2건(1건은 확인 못 함으로 바뀜), 주의 2건 → 2건, 요청 5건 중 0건 반영"
    assert report.rule_deltas[0].id == "R1"  # 바뀐 것은 위에 둔다


def test_green_rule_becoming_unknown_is_mentioned():
    before = load("A")
    after = before.model_copy(deep=True)
    after.contract.address = None  # R11 🟢 → ⚪
    report = build_compare(CompareRequest(before=before, after=after))
    assert [(d.id, d.change) for d in report.rule_deltas if d.change != "그대로"] == [("R11", "확인 못 함")]
    assert report.headline == "확인 못 함으로 바뀐 항목 1건, 요청 1건 중 0건 반영"



# ---------------------------------------------------------------------------
# 특약 종류: 임차인의 의무를 임대인의 금지 약속으로 세지 않는다
# ---------------------------------------------------------------------------

TENANT_PLEDGE = "임차인은 임대인의 동의 없이 임차권에 질권을 설정할 수 없다."


def test_tenant_restriction_is_not_a_protective_clause_anywhere():
    before = load("B")
    after = before.model_copy(deep=True)
    after.contract.special_terms = [TENANT_PLEDGE]
    assert levels(build_report(after))["R12"] == "yellow"
    report = build_compare(CompareRequest(before=before, after=after))
    assert dict((f.label, f.status) for f in report.fulfillment if f.kind == "term")["담보 설정 금지"] == "미반영"
    assert all(d.change == "그대로" for d in report.rule_deltas)
    req = RecheckRequest.model_validate_json((DEMO_DIR / "recheck-A.json").read_bytes())
    req.contract.special_terms = [TENANT_PLEDGE]
    recheck_report = build_recheck(req)
    assert recheck_report.term_checks == []  # 점검할 보호 특약이 아니다
    assert not any(a.startswith("계약서 특약(") for a in recheck_report.actions)


# ---------------------------------------------------------------------------
# 재확인: 질권 금액은 근저당 채권최고액이 아니다
# ---------------------------------------------------------------------------


def test_pledge_amount_is_not_the_mortgage_amount():
    req = fresh_a()
    req.registry.eulgu = [
        entry("1", "근저당권설정", dt.date(2024, 1, 10), amount=60_000_000),
        entry("1-1", "1번근저당권부질권", dt.date(2025, 3, 1), ["△△캐피탈"], amount=30_000_000),
        entry("1-2", "1번근저당권변경", dt.date(2026, 11, 20), [], amount=50_000_000),  # 6,000만 → 5,000만 (감액)
    ]
    report = build_recheck(req)
    assert [(c.rank, c.level, c.note) for c in report.changes] == [
        ("1-2", "yellow", "기존 권리 변경: 무엇이 바뀌었는지 원문을 확인하세요")
    ]
    assert [(t.status, t.level) for t in report.term_checks] == [("이행", "green")]
    req.registry.eulgu[2].amount = 70_000_000  # 6,000만 → 7,000만 (증액)
    (check,) = build_recheck(req).term_checks
    assert (check.status, check.note) == (
        "위반",
        "계약 후 2026년 11월 20일에 기존 근저당권의 채권최고액이 6,000만 원에서 7,000만 원으로 늘었어요.",
    )


# ---------------------------------------------------------------------------
# 재확인: 잔금 당일·입주 후에는 그날까지 나온 등기부여야 한다
# ---------------------------------------------------------------------------


def viewed_on(viewed: dt.date, today: dt.date) -> RecheckRequest:
    """예시 A (잔금·입주 2026-12-01)를 viewed에 뗀 등기부로 today에 확인."""
    req = fresh_a(today=today)
    req.registry.viewed_at = dt.datetime(viewed.year, viewed.month, viewed.day, 9, 0, tzinfo=KST)
    return req


@pytest.mark.parametrize(
    "viewed, today, title, message",
    [
        # 잔금 전: 계약일 뒤에 뗀 등기부면 된다
        (dt.date(2026, 11, 20), dt.date(2026, 11, 29), "새로 생긴 권리 없음", None),
        # 잔금 당일: 잔금일 당일에 뗀 등기부여야 한다
        (
            dt.date(2026, 11, 20),
            dt.date(2026, 12, 1),
            "확인 미완료",
            "올린 등기부는 2026년 11월 20일에 뗀 것이라 잔금일(2026년 12월 1일) 당일에 접수된 권리가 나오지 않아요. "
            "잔금을 보내기 직전에 등기부를 다시 떼어 올려 확인하세요.",
        ),
        (dt.date(2026, 12, 1), dt.date(2026, 12, 1), "새로 생긴 권리 없음", None),
        # 입주 후: 입주일 다음 날 이후에 뗀 등기부여야 한다
        (
            dt.date(2026, 11, 20),
            dt.date(2026, 12, 3),
            "확인 미완료",
            "올린 등기부는 2026년 11월 20일에 뗀 것이라 입주일(2026년 12월 1일) 당일에 접수된 권리가 나오지 않아요. "
            "오늘 날짜로 등기부를 다시 떼어 올려 확인하세요.",
        ),
        (
            dt.date(2026, 12, 1),
            dt.date(2026, 12, 3),
            "확인 미완료",
            "올린 등기부는 입주일(2026년 12월 1일) 당일에 뗀 것이라 그날 늦게 접수된 권리가 나오지 않을 수 있어요. "
            "오늘 날짜로 등기부를 다시 떼어 올려 확인하세요.",
        ),
        (dt.date(2026, 12, 2), dt.date(2026, 12, 3), "새로 생긴 권리 없음", None),
    ],
)
def test_registry_must_cover_the_balance_and_move_in_day(viewed, today, title, message):
    report = build_recheck(viewed_on(viewed, today))
    assert report.overall.title == title
    if message is not None:
        assert (report.overall.level, report.overall.message) == ("yellow", message)
        assert [t.status for t in report.term_checks] == ["확인 필요"]


def test_after_move_in_uses_the_last_past_date_when_move_in_is_later():
    req = viewed_on(dt.date(2026, 12, 2), dt.date(2026, 12, 5))
    req.contract.balance_date, req.contract.move_in_date = dt.date(2026, 12, 1), dt.date(2026, 12, 10)
    report = build_recheck(req)
    assert (report.phase, report.overall.title) == ("after_move_in", "새로 생긴 권리 없음")


def test_recheck_demo_is_unchanged_by_the_view_day_rule():
    report = build_recheck(RecheckRequest.model_validate_json((DEMO_DIR / "recheck-A.json").read_bytes()))
    assert (report.phase, report.overall.title) == ("before_balance", "잔금 보류 권장")


# ---------------------------------------------------------------------------
# 재확인: 순위번호가 앞 행과 같아도 다른 권리면 빠뜨리지 않는다
# ---------------------------------------------------------------------------


def test_holderless_row_with_a_reused_rank_is_still_a_new_right():
    req = fresh_a()
    req.registry.gapgu.append(entry("2", "가압류", dt.date(2026, 11, 28), [], cause="가압류결정"))
    report = build_recheck(req)
    assert [(c.rank, c.purpose, c.level) for c in report.changes] == [("2", "가압류", "red")]
    assert report.overall.title == "잔금 보류 권장"
    check = load("A")
    check.registry.gapgu.append(entry("2", "가압류", dt.date(2026, 11, 28), [], cause="가압류결정"))
    assert levels(build_report(check))["R3"] == "red"  # 검사와 같은 결론


def test_split_lines_of_one_rank_are_still_merged():
    req = fresh_a()
    req.registry.gapgu += [
        entry("3", "소유권이전", dt.date(2026, 11, 22), ["김○○"], cause="매매"),
        entry("3", "신탁", None, []),  # "신탁"만 적힌 줄은 접수일이 없어도 나눠 적은 줄이다
        entry("4", "가처분", dt.date(2026, 11, 23), ["○○캐피탈"]),
        entry("4", "가처분", dt.date(2026, 11, 23), []),  # 접수일이 같은 권리자 없는 줄
    ]
    assert [(c.rank, c.purpose) for c in build_recheck(req).changes] == [("3", "소유권이전"), ("4", "가처분")]


# ---------------------------------------------------------------------------
# 검사: 0원·음수 금액은 비율 계산에 쓰지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("deposit", [0, -180_000_000])
def test_zero_or_negative_deposit_is_unknown(deposit):
    req = load("C")
    req.contract.deposit = deposit
    report = build_report(req)
    r5 = next(r for r in report.results if r.id == "R5")
    assert (r5.level, r5.unknown_reason) == ("unknown", "보증금 값이 올바르지 않아요")
    row = next(row for row in report.comparison if row.rule_id == "R5")
    assert (row.contract, row.level, row.note) == (fmt_money(deposit), "unknown", "확인 못 함")


def test_negative_deposit_falls_back_to_a_valid_typed_deposit():
    req = load("C")
    req.contract.deposit = -1
    req.manual.deposit = 180_000_000
    r5 = next(r for r in build_report(req).results if r.id == "R5")
    assert r5.level == "red" and "(직접 입력)" in r5.evidence[-2].text


def test_negative_typed_prior_deposits_is_unknown():
    req = load("C")
    req.manual.prior_deposits = -100_000_000  # 예전에는 🔴가 🟢로 바뀌었다
    r5 = next(r for r in build_report(req).results if r.id == "R5")
    assert (r5.level, r5.unknown_reason) == ("unknown", "직접 입력한 선순위 보증금 값이 올바르지 않아요")
    req.manual.prior_deposits = 0  # 0은 "선순위 없음"이다
    assert levels(build_report(req))["R5"] == "red"


@pytest.mark.parametrize("amount", [0, -120_000_000])
def test_zero_or_negative_claim_amount_is_unread(amount):
    req = load("B")
    req.registry.eulgu[0].amount = amount
    report = build_report(req)
    r6 = next(r for r in report.results if r.id == "R6")
    assert r6.summary == "채권최고액 등 확인되지 않은 금액이 내 보증금보다 먼저 돌려받아요."
    assert "근저당권(채권최고액 ○○원)" in " ".join(report.special_terms)
    lease = load("A")
    lease.registry.eulgu = [entry("1", "임차권설정", dt.date(2020, 1, 1), ["이○○"], amount=amount)]
    r4 = next(r for r in build_report(lease).results if r.id == "R4")
    assert r4.summary == "이○○의 임차권이 먼저 등기돼 있어요."


# ---------------------------------------------------------------------------
# 검사: 신탁 뒤 소유권 이전을 읽지 못했으면 신탁이 끝났다고 하지 않는다
# ---------------------------------------------------------------------------


def test_trust_followed_by_an_unreadable_transfer_is_unknown():
    req = with_gapgu(
        entry("3", "소유권이전, 신탁", dt.date(2023, 1, 10), ["○○신탁(주)"], cause="신탁"),
        entry("4", "소유권이전", dt.date(2024, 1, 1), [], cause=None),
    )
    report = build_report(req)
    r2 = next(r for r in report.results if r.id == "R2")
    assert r2.level == "unknown"
    assert r2.unknown_reason == "신탁 뒤 소유권 이전 항목의 권리자와 원인을 읽지 못해 신탁이 끝났는지 확인하지 못했어요"
    assert len(r2.evidence) == 2
    assert report.overall.title == "확인 미완료"
    req.registry.gapgu[-1].cause = "신탁재산의귀속"  # 원인을 읽었으면 끝난 신탁이다
    assert levels(build_report(req))["R2"] == "green"


def test_recheck_with_an_unclear_trust_is_incomplete():
    req = fresh_a()
    req.registry.gapgu += [
        entry("3", "소유권이전, 신탁", dt.date(2023, 1, 10), ["○○신탁(주)"], cause="신탁"),
        entry("4", "소유권이전", dt.date(2024, 1, 1), [], cause=None),
    ]
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert "신탁이 끝났는지 등기부로 확인하지 못했어요." in report.overall.message
    assert recheck.ACTION_TRUST_UNKNOWN in report.actions
