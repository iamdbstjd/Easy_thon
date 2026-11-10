"""규칙 엔진 단위 테스트."""

from __future__ import annotations

import datetime as dt
import re
from fractions import Fraction

import pytest

from app.rules import build_report, content, engine
from app.rules.common import (
    address_has_core,
    display_name,
    floor_from_ho,
    fmt_money,
    fmt_percent,
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
    road_core,
    to_kst,
    today_kst,
    unit_in_address,
    unit_key,
    unit_text,
)
from app.schemas import (
    RULE_NAMES,
    BuildingRegister,
    CheckRequest,
    ContractExtract,
    ContractUnit,
    Counts,
    Entry,
    MarketPrice,
    RegistryExtract,
    RegistryUnit,
    RuleResult,
)

TODAY = dt.date(2026, 11, 14)
KST = dt.timezone(dt.timedelta(hours=9))

USE_LINES = [
    "철근콘크리트구조 (철근)콘크리트지붕 4층 공동주택(다세대주택)",
    "1층 다세대주택 66.20㎡",
    "2층 다세대주택 112.30㎡",
    "3층 다세대주택 112.30㎡",
    "4층 다세대주택 98.10㎡",
]


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------


def entry(rank, purpose, received_at=None, cause=None, holders=(), amount=None, cancelled=False, page=2):
    return Entry(
        rank=rank,
        purpose=purpose,
        received_at=received_at,
        cause=cause,
        holders=list(holders),
        amount=amount,
        is_cancelled=cancelled,
        page=page,
        source_text=f"{rank} {purpose}",
    )


def base_request() -> CheckRequest:
    """모든 규칙이 🟢인 기본 요청 (시나리오 A와 같은 구조). 테스트마다 고쳐 쓴다."""
    return CheckRequest(
        registry=RegistryExtract(
            registry_type="집합건물",
            viewed_at=dt.datetime(2026, 11, 14, 9, 0, tzinfo=KST),
            address_jibun="경기도 용인시 수지구 죽전동 123-4",
            address_road="경기도 용인시 수지구 포은대로 123",
            building_name="죽전○○빌라",
            unit=RegistryUnit(ho="302호", floor="3층", area_m2=49.58),
            building_use_lines=list(USE_LINES),
            gapgu=[
                entry("1", "소유권보존", dt.date(2015, 3, 10), None, ["정○○"]),
                entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", ["김○○"]),
            ],
            eulgu=[],
        ),
        contract=ContractExtract(
            landlord_names=["김○○"],
            address="경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호",
            unit=ContractUnit(ho="302호"),
            lease_type="월세",
            deposit=10_000_000,
            monthly_rent=450_000,
            contract_date=TODAY,
            balance_date=dt.date(2026, 12, 1),
            move_in_date=dt.date(2026, 12, 1),
            special_terms=["임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다."],
        ),
        building=BuildingRegister(main_use="공동주택(다세대주택)", unit_use="다세대주택", is_violating=False),
        market=MarketPrice(price=200_000_000, method="same_building", deals=2, period="2025-12 ~ 2026-11"),
        today=TODAY,
    )


def results(req: CheckRequest) -> dict[str, RuleResult]:
    return {r.id: r for r in build_report(req).results}


def rule(req: CheckRequest, rid: str) -> RuleResult:
    return results(req)[rid]


def mortgage(rank="1", amount=120_000_000, **kw):
    return entry(rank, "근저당권설정", dt.date(2024, 1, 10), "설정계약", ["○○은행"], amount=amount, page=3, **kw)


# ---------------------------------------------------------------------------
# 공통 도구
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, text",
    [
        (120_000_000, "1억 2,000만 원"),
        (200_000_000, "2억 원"),
        (10_000_000, "1,000만 원"),
        (450_000, "45만 원"),
        (12_345_678, "1,234만 5,678원"),
        (0, "0원"),
        (5_000, "5,000원"),
        (180_000_000, "1억 8,000만 원"),
        (1_200_000_000, "12억 원"),
        (100_005_000, "1억 5,000원"),
    ],
)
def test_fmt_money(amount, text):
    assert fmt_money(amount) == text


@pytest.mark.parametrize(
    "value, text",
    [
        (0.9, "90%"),
        (Fraction(1, 20), "5%"),
        (0.29, "29%"),  # 0.29 * 100 = 28.999… 이 되지 않게
        (Fraction(79_999, 100_000), "79%"),  # 기준값 80% 미만은 80%로 보이지 않는다
        (Fraction(8, 10), "80%"),
        (1, "100%"),
        (Fraction(3, 2), "150%"),
    ],
)
def test_fmt_percent(value, text):
    assert fmt_percent(value) == text


@pytest.mark.parametrize(
    "period, text",
    [
        ("2025-12 ~ 2026-11", "2025년 12월 ~ 2026년 11월"),
        ("2025-01 ~ 2025-12", "2025년 1월 ~ 2025년 12월"),
        ("2025-1~2025-12", "2025년 1월 ~ 2025년 12월"),
        ("최근 12개월", "최근 12개월"),  # 다른 형식은 그대로
        ("2025.12 ~ 2026.11", "2025.12 ~ 2026.11"),
        ("2025-13 ~ 2026-11", "2025-13 ~ 2026-11"),  # 없는 달은 바꾸지 않는다
    ],
)
def test_fmt_period(period, text):
    assert fmt_period(period) == text


@pytest.mark.parametrize(
    "a, b",
    [
        ("○○부동산신탁(주)", "○○부동산신탁주식회사"),
        ("㈜○○부동산신탁", "주식회사 ○○부동산신탁"),
        ("○○부동산신탁 （주）", "○○부동산신탁"),
        ("김 ○○", "김○○"),
        ("수탁자 ○○부동산신탁(주)", "○○부동산신탁"),
        ("근저당권자 주식회사○○은행", "○○은행"),
        ("○○유한회사", "○○"),
        ("임대인 이○○", "이○○"),
        ("소유자 김○○ 850315-*******", "김○○"),
    ],
)
def test_normalize_name_equal(a, b):
    assert normalize_name(a) == normalize_name(b)


def test_normalize_name_keeps_different_names_apart():
    assert normalize_name("김○○") != normalize_name("이○○")
    assert normalize_name("○○부동산신탁(주)") != normalize_name("이○○")


@pytest.mark.parametrize(
    "raw, shown",
    [
        ("김철수 850315-1234567", "김철수"),
        ("소유자 김○○ 850315-*******", "김○○"),
        ("김철수 850315 - 1******", "김철수"),
        ("김철수 850315-1xxxxxx", "김철수"),
        ("김철수 850315-1○○○○○○", "김철수"),
        ("김철수 850315-1●●●●●●", "김철수"),
        ("수탁자 ○○부동산신탁주식회사 110111-*******", "○○부동산신탁주식회사"),
        ("○○부동산신탁(주)", "○○부동산신탁(주)"),
    ],
)
def test_display_name_hides_id_numbers_and_role_words(raw, shown):
    assert display_name(raw) == shown


NOT_ID_NUMBERS = "전화 010-1234-5678, 2026-11-14, 죽전동 123-4, 금120,000,000원"


@pytest.mark.parametrize(
    "text, masked",
    [
        (
            "임대인 성명 이○○ 주민등록번호 900101-******* 주소 경기도 용인시",
            "임대인 성명 이○○ 주민등록번호 ******-******* 주소 경기도 용인시",
        ),
        ("소유자 김철수 850315-1234567 서울특별시", "소유자 김철수 ******-******* 서울특별시"),
        ("850315-1******", "******-*******"),
        ("소유자 김철수 850315-1xxxxxx 서울", "소유자 김철수 ******-******* 서울"),
        ("850315-1○○○○○○", "******-*******"),
        ("850315-1●●●●●●", "******-*******"),
        ("수탁자 ○○신탁 110111-******* 신탁원부 제2026-5678호", "수탁자 ○○신탁 ******-******* 신탁원부 제2026-5678호"),
        # 등록번호 모양이 아닌 숫자는 그대로 둔다
        (NOT_ID_NUMBERS, NOT_ID_NUMBERS),
        ("1234567-1234567", "1234567-1234567"),
    ],
)
def test_mask_id_numbers(text, masked):
    assert mask_id_numbers(text) == masked


@pytest.mark.parametrize(
    "word, ieyo, euro",
    [
        ("매매", "예요", "로"),
        ("신탁", "이에요", "으로"),
        ("상속", "이에요", "으로"),
        ("이○○", "이에요", "으로"),  # 판단할 수 없으면 기본 조사 그대로
        ("김민수", "예요", "로"),
        ("제2종근린생활시설", "이에요", "로"),
        ("제2종근린생활시설(사무소)", "예요", "로"),
        ("302호", "예요", "로"),
    ],
)
def test_josa(word, ieyo, euro):
    assert josa_ieyo(word) == ieyo
    assert josa_euro(word) == euro


def test_to_kst_treats_naive_as_kst_and_converts_aware():
    naive = to_kst(dt.datetime(2026, 11, 14, 23, 30))  # UTC로 보면 다음 날이 된다
    assert (naive.date(), naive.hour) == (dt.date(2026, 11, 14), 23)
    utc = dt.datetime(2026, 11, 13, 16, 0, tzinfo=dt.timezone.utc)
    assert to_kst(utc).date() == dt.date(2026, 11, 14)
    assert to_kst(utc).utcoffset() == dt.timedelta(hours=9)


@pytest.mark.parametrize(
    "text, floor",
    [
        ("3층", (False, 3)),
        ("제3층", (False, 3)),
        ("3", (False, 3)),
        ("13층", (False, 13)),
        ("지하1층", (True, 1)),
        ("지1층", (True, 1)),
        ("B1", (True, 1)),
        ("비1층", (True, 1)),
        ("옥탑", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_floor(text, floor):
    assert parse_floor(text) == floor


@pytest.mark.parametrize(
    "ho, floor",
    [
        ("302호", (False, 3)),
        ("제302호", (False, 3)),
        ("1201호", (False, 12)),
        ("12호", None),
        ("B102호", None),
        ("지하102호", None),
        ("비102호", None),
        (None, None),
    ],
)
def test_floor_from_ho(ho, floor):
    assert floor_from_ho(ho) == floor


@pytest.mark.parametrize(
    "ho, basement",
    [
        ("B102호", True),
        ("b102", True),
        ("지하102호", True),
        ("지102호", True),
        ("비102호", True),
        ("302호", False),
        (None, False),
    ],
)
def test_is_basement_unit(ho, basement):
    assert is_basement_unit(ho) is basement


@pytest.mark.parametrize(
    "line, floor_line",
    [
        ("철근콘크리트구조 (철근)콘크리트지붕 4층 공동주택(다세대주택)", False),  # 건물 전체 줄
        ("(철근)콘크리트지붕 4층", False),
        ("3층 112.30㎡", True),
        ("B1 주차장", True),
        ("다세대주택", False),  # 기타 줄
        ("제2종근린생활시설", False),
    ],
)
def test_is_floor_line(line, floor_line):
    assert is_floor_line(line) is floor_line


@pytest.mark.parametrize(
    "floor, line, expected",
    [
        ((False, 3), "3층 다세대주택 112.30㎡", True),
        ((False, 3), "제3층 다세대주택", True),
        ((False, 3), "3 층 다세대주택", True),
        ((False, 3), "2층 다세대주택 112.30㎡", False),
        ((False, 3), "13층 다세대주택 80.00㎡", False),
        ((False, 3), "23층 다세대주택", False),
        ((False, 3), "지하3층 주차장", False),
        ((False, 3), "지하 3층 주차장", False),
        ((False, 3), "지3층 주차장", False),
        ((False, 3), "B3 주차장", False),
        ((False, 3), "비3층 주차장", False),
        ((False, 1), "기계설비 1층", True),  # "설비"의 "비"는 지하 표시가 아니다
        ((True, 1), "비1층 창고", True),
        ((False, 1), "지하1층 주차장 45.00㎡ 1층 제1종근린생활시설", True),
        ((False, 1), "지하1층 주차장 45.00㎡", False),
        ((False, 1), "11층 다세대주택", False),
        ((True, 1), "지하1층 주차장", True),
        ((True, 1), "지1층 주차장", True),
        ((True, 1), "B1 주차장", True),
        ((True, 1), "1층 다세대주택", False),
        ((True, 1), "지하11층 기계실", False),
    ],
)
def test_line_has_floor(floor, line, expected):
    assert line_has_floor(line, floor) is expected


def test_address_cores():
    assert jibun_core("경기도 용인시 수지구 죽전동 123-4").text == "죽전동 123-4"
    assert jibun_core("경기도 용인시 수지구 죽전동 123-4번지 죽전○○빌라").text == "죽전동 123-4"
    assert jibun_core("경기도 용인시 처인구 모현읍 일산리 산12-3").text == "일산리 산12-3"
    assert jibun_core("서울특별시 종로구 종로1가 24").text == "종로1가 24"
    assert road_core("경기도 용인시 수지구 포은대로 123 (죽전동, 죽전○○빌라)").text == "포은대로 123"
    assert road_core("경기도 용인시 수지구 죽전로15번길 12").text == "죽전로15번길 12"
    assert jibun_core(None) is None
    assert road_core("") is None


JIBUN = jibun_core("경기도 용인시 수지구 죽전동 123-4")
ROAD = road_core("경기도 용인시 수지구 포은대로 123")


@pytest.mark.parametrize(
    "address, expected",
    [
        ("경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호", True),
        ("용인시 수지구 죽전동 123-4번지 302호", True),
        ("경기도 용인시 수지구 죽전동123-4, 302호", True),
        ("경기도 용인시 수지구 죽전동 123 - 4 제302호", True),
        ("경기도 용인시 수지구 죽전동 123-45 302호", False),
        ("경기도 용인시 수지구 죽전동 1123-4 302호", False),
        ("경기도 용인시 수지구 죽전동 12-4 302호", False),
        ("경기도 용인시 수지구 죽전동 123 302호", False),
        ("경기도 용인시 수지구 보정동 123-4 302호", False),
    ],
)
def test_address_has_jibun(address, expected):
    assert address_has_core(address, JIBUN) is expected


@pytest.mark.parametrize(
    "address, expected",
    [
        ("경기도 용인시 수지구 포은대로 123, 302호", True),
        ("포은대로123 302호", True),
        ("경기도 용인시 수지구 포은대로 1234", False),
        ("경기도 용인시 수지구 포은대로 123번길 5", False),
        ("경기도 용인시 수지구 포은대로 123-1", False),
    ],
)
def test_address_has_road(address, expected):
    assert address_has_core(address, ROAD) is expected


@pytest.mark.parametrize(
    "text, key",
    [
        ("302호", "302"),
        ("제302호", "302"),
        ("302", "302"),
        ("제 302 호", "302"),
        ("B302호", "B302"),  # 지하 표시는 호수의 일부다
        ("b302", "B302"),
        ("지하102호", "B102"),
        ("지102호", "B102"),
        ("비102호", "B102"),
        ("302-1호", "302-1"),
        ("0302호", "302"),  # 숫자 앞의 0은 무시한다
        ("B0102호", "B102"),
        ("100호", "100"),
        ("", None),
        (None, None),
    ],
)
def test_unit_key_for_ho(text, key):
    assert unit_key(text, "호") == key


@pytest.mark.parametrize(
    "text, key",
    [("101동", "101"), ("제101동", "101"), ("A동", "A"), ("a동", "A"), ("가동", "가"), ("가", "가"), (None, None)],
)
def test_unit_key_for_dong(text, key):
    assert unit_key(text, "동") == key


@pytest.mark.parametrize(
    "text, suffix, shown",
    [
        ("302호", "호", "302호"),
        ("제302호", "호", "302호"),
        ("302", "호", "302호"),
        ("B102호", "호", "B102호"),
        ("지하102호", "호", "지하102호"),
        ("302-1호", "호", "302-1호"),
        ("101", "동", "101동"),
        ("가동", "동", "가동"),
        ("", "호", None),
        (None, "동", None),
    ],
)
def test_unit_text_keeps_original_spelling(text, suffix, shown):
    assert unit_text(text, suffix) == shown


BASE_ADDR = "경기도 용인시 수지구 죽전동 123-4"


@pytest.mark.parametrize(
    "address, unit",
    [
        (f"{BASE_ADDR} 101동 302호", ("101동", "302호")),
        (f"{BASE_ADDR} 제101동 제302호", ("101동", "302호")),
        (f"{BASE_ADDR} 죽전○○빌라302호", (None, "302호")),  # 띄어쓰기 없음
        (f"{BASE_ADDR} ○○아파트 101동302호", ("101동", "302호")),
        (f"{BASE_ADDR} ○○아파트 101동, 302호", ("101동", "302호")),
        (f"{BASE_ADDR} ○○아파트 101동 3층 302호", ("101동", "302호")),
        (f"{BASE_ADDR} ○○빌라 가동 302호", ("가동", "302호")),  # 한글 한 글자 동
        (f"{BASE_ADDR} ○○빌라 A동 302호", ("A동", "302호")),
        (f"{BASE_ADDR} 죽전○○빌라 지하102호", (None, "지하102호")),
        (f"{BASE_ADDR} 죽전○○빌라 지하 102호", (None, "지하102호")),
        (f"{BASE_ADDR} 죽전○○빌라 B102호", (None, "B102호")),
        (f"{BASE_ADDR} 죽전○○빌라 비102호", (None, "비102호")),
        (f"{BASE_ADDR} 죽전○○빌리지 302호", (None, "302호")),  # "빌리지"의 "지"는 지하 표시가 아니다
        (f"{BASE_ADDR} 죽전○○빌라 302-1호", (None, "302-1호")),
        (f"{BASE_ADDR} 죽전○○빌라 지하1층 102호", (None, "지하102호")),  # 호수 앞 지하층 → 지하 호수
        (f"{BASE_ADDR} 죽전○○빌라 지1층 제102호", (None, "지하102호")),
        (f"{BASE_ADDR} 죽전○○빌라 지하1층102호", (None, "지하102호")),
        (f"{BASE_ADDR} ○○아파트 101동 지하1층 102호", ("101동", "지하102호")),
        (f"{BASE_ADDR} 죽전○○빌라 3층 302호", (None, "302호")),  # 지상층은 그대로
        ("경기도 용인시 수지구 죽전동 302호", (None, "302호")),  # 법정동 "죽전동"은 건물 동이 아니다
        ("경기도 용인시 수지구 포은대로 123 (죽전1동) 302호", (None, "302호")),
        (f"{BASE_ADDR} ○○아파트 101동", ("101동", None)),
        (BASE_ADDR, (None, None)),
        (None, (None, None)),
    ],
)
def test_unit_in_address(address, unit):
    assert unit_in_address(address) == unit


# ---------------------------------------------------------------------------
# 기본 요청과 견고성
# ---------------------------------------------------------------------------


def test_base_request_is_all_green():
    assert {rid: r.level for rid, r in results(base_request()).items()} == {rid: "green" for rid in RULE_NAMES}


def test_empty_request_returns_unknowns_without_error():
    report = build_report(CheckRequest(registry=RegistryExtract(), today=TODAY))
    assert sorted(r.id for r in report.results) == sorted(RULE_NAMES)
    # 을구는 원래 없을 수 있으므로 R4·R6만 🟢, 나머지는 ⚪와 이유
    assert {r.id for r in report.results if r.level == "green"} == {"R4", "R6"}
    for r in report.results:
        assert r.level in ("green", "unknown")
        if r.level == "unknown":
            assert r.unknown_reason
    assert report.counts == Counts(red=0, yellow=0, unknown=11, green=2)
    # 핵심 규칙(R1·R2·R3·R7·R8·R13)이 모두 ⚪이므로 "큰 위험 신호 없음"이 아니다
    assert report.overall.level == "yellow"
    assert report.overall.title == "확인 미완료"
    assert report.overall.message == (
        "위험 신호는 찾지 못했지만, 꼭 확인해야 할 항목 6개를 확인하지 못했어요. 빠진 내용을 채운 뒤 다시 검사하세요."
    )
    assert report.overall.unknown_note == "확인하지 못한 항목 11개"
    assert report.request_message.startswith("안녕하세요. 계약하려는 집 임대차 계약 건으로")


def test_failing_rule_only_affects_itself(monkeypatch):
    def boom(ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "RULES", [(rid, boom if rid == "R3" else fn) for rid, fn in engine.RULES])
    res = results(base_request())
    assert res["R3"].level == "unknown"
    assert res["R3"].unknown_reason
    assert all(r.level == "green" for rid, r in res.items() if rid != "R3")


def test_messy_inputs_never_hit_the_failure_fallback():
    """규칙이 예외를 삼키고 ⚪가 되는 일이 없어야 한다 (고정 시드로 무작위 입력 300개)."""
    import random

    rng = random.Random(20261114)
    purposes = [
        "소유권보존", "소유권이전", "소유권이전, 신탁", "신탁", "소유권일부이전", "2번김○○지분전부이전",
        "소유권이전청구권가등기", "가압류", "3번가압류등기말소", "근저당권설정", "1번근저당권변경",
        "1번근저당권부질권", "전세권설정", "임차권설정", "주택임차권", "", "등기명의인표시변경",
    ]
    names = ["김○○", "이○○", "○○부동산신탁(주)", "주식회사 ○○은행", "", "수탁자"]
    lines = ["철근콘크리트구조 4층 다세대주택", "3층 다세대주택", "지하3층 주차장", "3층 112.30㎡", "다가구주택", ""]
    addresses = [None, "", "경기도 용인시 수지구 죽전동 123-4", "포은대로 123번길 5", "302호", "산 12-3"]

    def any_date():
        return rng.choice([None, TODAY - dt.timedelta(days=rng.randint(-30, 4000))])

    def any_entry(i):
        return Entry(
            rank=rng.choice([str(i), f"{i}-1", ""]),
            purpose=rng.choice(purposes),
            received_at=any_date(),
            cause=rng.choice([None, "매매", "신탁", "신탁재산의귀속", "임차권등기명령", ""]),
            holders=rng.sample(names, rng.randint(0, 2)),
            amount=rng.choice([None, 0, 120_000_000]),
            is_cancelled=rng.random() < 0.2,
            page=rng.choice([None, 2]),
            source_text=rng.choice(["", "원문"]),
        )

    for _ in range(300):
        req = CheckRequest(
            registry=RegistryExtract(
                registry_type=rng.choice(["집합건물", "건물", "토지", None]),
                viewed_at=rng.choice([None, dt.datetime(2026, 11, rng.randint(1, 20), rng.randint(0, 23))]),
                address_jibun=rng.choice(addresses),
                address_road=rng.choice(addresses),
                unit=RegistryUnit(dong=rng.choice([None, "101동"]), ho=rng.choice([None, "302호", "B01"]),
                                  floor=rng.choice([None, "3층", "지하1층", "옥탑"])),
                building_use_lines=rng.sample(lines, rng.randint(0, 3)),
                gapgu=[any_entry(i) for i in range(rng.randint(0, 4))],
                eulgu=[any_entry(i) for i in range(rng.randint(0, 3))],
            ),
            contract=rng.choice([None, ContractExtract(
                landlord_names=rng.sample(names, rng.randint(0, 2)),
                address=rng.choice(addresses),
                unit=ContractUnit(ho=rng.choice([None, "302호"])),
                deposit=rng.choice([None, 0, 180_000_000]),
                contract_date=any_date(),
                special_terms=rng.sample(["반려동물 금지", "담보 설정하지 않는다", ""], rng.randint(0, 2)),
            )]),
            building=rng.choice([None, BuildingRegister(unit_use=rng.choice([None, "", "사무소"]),
                                                        is_violating=rng.choice([None, True, False]))]),
            market=rng.choice([None, MarketPrice(price=rng.choice([None, 0, -1, 200_000_000]))]),
            today=TODAY,
        )
        report = build_report(req)
        assert len(report.results) == 13
        for r in report.results:
            assert r.unknown_reason != engine.RULE_FAILED, r.id
            assert (r.unknown_reason is not None) == (r.level == "unknown")
            assert all(e.text for e in r.evidence)
        check_crosscheck(report)


COMPARISON_ORDER = [("임대인", "R1"), ("소재지·호수", "R11"), ("보증금", "R5"), ("계약일", "R8"), ("특약", "R12")]
FALLBACK_NOTES = {"확인 필요", "해당 없음"}  # 행을 만들다 실패했을 때만 쓰는 결과


def check_crosscheck(report):
    """대조표·요청서 공통 조건: 행 순서, 등급 = 규칙 등급, 값이 비어 있지 않음, R5 비율 일치, 요청서 있음."""
    levels = {r.id: r.level for r in report.results}
    rows = report.comparison
    assert [(row.item, row.rule_id) for row in rows] == COMPARISON_ORDER
    for row in rows:
        assert row.level == levels[row.rule_id], row
        assert row.registry and row.note, row
        assert row.contract is None or row.contract.strip(), row  # 값이 없으면 null (화면에는 "—")
        assert row.note not in FALLBACK_NOTES, row  # 값을 만들다 실패한 행이 없다
    r5 = {r.id: r for r in report.results}["R5"]
    if r5.level != "unknown":
        assert f"의 {rows[2].note}예요." in r5.summary
    a = report.amendment
    assert a is not None and a.text.endswith("이 요청서는 서류를 기준으로 만든 참고 자료이며 법률 자문이 아닙니다.")
    assert a.terms == report.special_terms
    assert "근저당 대출을 잔금일에 갚고 말소할 계획인지" not in a.documents  # 서류만 넣는다


def test_green_and_unknown_fields():
    req = base_request()
    req.building = None
    res = results(req)
    assert res["R9"].unknown_reason == "건축물대장 정보가 없어요"
    assert (res["R9"].title, res["R9"].summary, res["R9"].action) == ("", "", "")
    assert res["R1"].unknown_reason is None
    assert (res["R1"].title, res["R1"].summary, res["R1"].action) == ("", "", "")
    assert all(r.name == RULE_NAMES[rid] for rid, r in res.items())


# ---------------------------------------------------------------------------
# R1 임대인·소유자 불일치
# ---------------------------------------------------------------------------


def test_r1_name_comes_from_schema():
    assert rule(base_request(), "R1").name == RULE_NAMES["R1"] == "임대인·소유자 불일치"


def test_r1_red_when_landlord_is_not_owner():
    req = base_request()
    req.contract.landlord_names = ["이○○"]
    r = rule(req, "R1")
    assert r.level == "red"
    assert r.title == "계약하는 사람과 집주인이 달라요"
    assert r.summary == "등기부상 소유자는 김○○인데, 계약서의 임대인은 이○○이에요."
    assert r.action.startswith("대리 계약이라면 위임장과 인감증명서를 확인하고")
    assert [(e.doc, e.page) for e in r.evidence] == [("registry", 2), ("contract", None)]


def test_r1_compares_normalized_names():
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2020, 1, 2), "매매", ["주식회사 ○○하우징"]))
    req.contract.landlord_names = ["○○하우징(주)"]
    assert rule(req, "R1").level == "green"


def test_r1_yellow_when_jointly_owned():
    req = base_request()
    req.registry.gapgu[-1] = entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", ["김○○", "박○○"])
    r = rule(req, "R1")
    assert r.level == "yellow"
    assert r.title == "집주인이 여러 명이에요"
    assert r.summary == "이 집은 2명이 함께 소유하고 있어요."


def test_r1_partial_transfer_makes_joint_ownership():
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권일부이전", dt.date(2020, 5, 1), "매매", ["박○○"]))
    r = rule(req, "R1")
    assert r.level == "yellow"  # 김○○은 여전히 공유자다
    assert r.summary == "이 집은 2명이 함께 소유하고 있어요."
    assert len([e for e in r.evidence if e.doc == "registry"]) == 2


def test_r1_share_transfer_replaces_seller():
    req = base_request()
    req.registry.gapgu[-1] = entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", ["김○○", "박○○"])
    req.registry.gapgu.append(entry("3", "2번박○○지분전부이전", dt.date(2021, 1, 4), "매매", ["최○○"]))
    r = rule(req, "R1")
    assert r.level == "yellow"
    assert r.summary == "이 집은 2명이 함께 소유하고 있어요."
    req.contract.landlord_names = ["박○○"]  # 지분을 모두 넘긴 사람
    assert rule(req, "R1").level == "red"


def test_r1_ignores_cancelled_and_provisional_registrations():
    req = base_request()
    req.registry.gapgu += [
        entry("3", "소유권이전", dt.date(2026, 10, 1), "매매", ["이○○"], cancelled=True),
        entry("4", "소유권이전청구권가등기", dt.date(2026, 10, 2), "매매예약", ["박○○"]),
    ]
    res = results(req)
    assert res["R1"].level == "green"  # 현재 소유자는 여전히 김○○
    assert res["R8"].level == "green"  # 말소·가등기 항목은 현재 소유권 항목이 아니다
    assert res["R3"].level == "red"  # 가등기는 R3에서 잡는다


def test_r1_unknown_without_landlord():
    req = base_request()
    req.contract.landlord_names = []
    r = rule(req, "R1")
    assert r.level == "unknown"
    assert r.unknown_reason == "임대인 이름을 확인하지 못했어요"


def test_r1_uses_manual_landlord_when_no_contract():
    req = base_request()
    req.contract = None
    req.manual.landlord_name = "김○○"
    r = rule(req, "R1")
    assert r.level == "green"
    assert r.evidence[-1].doc == "manual"
    req.manual.landlord_name = "이○○"
    r = rule(req, "R1")
    assert r.level == "red"
    assert r.evidence[-1].doc == "manual"
    # 직접 입력한 이름이면 "계약서의 임대인은" 대신 "입력한 임대인은"
    assert r.summary == "등기부상 소유자는 김○○인데, 입력한 임대인은 이○○이에요."


def test_r1_manual_wording_also_when_contract_has_no_names():
    req = base_request()
    req.contract.landlord_names = []
    req.manual.landlord_name = "이○○"
    assert rule(req, "R1").summary == "등기부상 소유자는 김○○인데, 입력한 임대인은 이○○이에요."


def test_r1_never_shows_id_numbers():
    req = base_request()
    req.registry.gapgu[-1] = entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", ["김철수 850315-1234567"])
    req.contract.landlord_names = ["이민준 900101-1******"]
    r = rule(req, "R1")
    assert r.level == "red"
    assert r.summary == "등기부상 소유자는 김철수인데, 계약서의 임대인은 이민준이에요."
    req.contract.landlord_names = ["김철수 850315-1234567"]  # 같은 사람
    assert rule(req, "R1").level == "green"


def test_r1_split_trust_row_without_holders_keeps_owner():
    """"3 소유권이전 … 수탁자" 다음에 같은 순위번호의 "3 신탁"(권리자 없음)이 와도 소유자는 수탁자다."""
    req = base_request()
    req.registry.gapgu += [
        entry("3", "소유권이전", dt.date(2026, 8, 26), "신탁", ["○○부동산신탁(주)"]),
        entry("3", "신탁", dt.date(2026, 8, 26), None, []),
    ]
    res = results(req)
    assert res["R1"].level == "red"
    assert res["R1"].summary.startswith("등기부상 소유자는 ○○부동산신탁(주)인데,")
    assert "소유권이 신탁으로 바뀌었어요" in res["R8"].summary  # R8은 권리자가 있는 행을 쓴다
    assert res["R2"].level == "red"


def test_r1_holderless_transfer_with_own_rank_means_owner_unknown():
    """순위번호가 따로 있는 이전 행인데 권리자가 비어 있으면 현재 소유자를 모른다. 이전 소유자로 비교하지 않는다."""
    req = base_request()
    req.registry.gapgu = [
        entry("1", "소유권보존", dt.date(2015, 3, 10), None, ["김○○"]),
        entry("2", "소유권이전", dt.date(2019, 6, 21), "2019년5월30일 매매", []),
    ]
    report = build_report(req)
    res = {r.id: r for r in report.results}
    assert res["R1"].level == "unknown"
    assert res["R1"].unknown_reason == "등기부에서 현재 소유자 이름을 읽지 못했어요"
    assert [e.text for e in res["R1"].evidence] == ["2 소유권이전"]  # 이름을 못 읽은 행을 보여준다
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert res["R8"].level == "green"  # 날짜는 그 행(2019년)을 쓴다

    req.contract.landlord_names = ["이○○"]  # 실제로 산 사람이어도 판매자 이름으로 🔴를 내지 않는다
    assert rule(req, "R1").level == "unknown"


def test_r1_recent_holderless_transfer_still_flags_r8():
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 10, 1), "매매", []))
    res = results(req)
    assert res["R1"].level == "unknown"
    assert res["R8"].summary.startswith("2026년 10월 1일에 소유권이 매매로 바뀌었어요 (기준일 44일 전).")


def test_r1_same_rank_holderless_continuation_row_keeps_owner():
    """같은 순위번호를 나눠 적은 줄(권리자 없음)은 "신탁"이 아니어도 소유자를 바꾸지 않는다."""
    req = base_request()
    req.registry.gapgu += [
        entry("3", "소유권이전", dt.date(2026, 8, 26), "신탁", ["○○부동산신탁(주)"]),
        entry("3", "소유권이전, 신탁", dt.date(2026, 8, 26), "신탁", []),
    ]
    res = results(req)
    assert res["R1"].level == "red"
    assert res["R1"].summary.startswith("등기부상 소유자는 ○○부동산신탁(주)인데,")


def test_r1_holderless_trust_only_row_keeps_owner():
    """"신탁"만 적힌 권리자 없는 행은 순위번호가 달라도 소유자를 바꾸지 않는다 (R2가 신탁을 잡는다)."""
    req = base_request()
    req.registry.gapgu.append(entry("3", "신탁", dt.date(2026, 8, 26), None, []))
    res = results(req)
    assert res["R1"].level == "green"
    assert res["R2"].level == "red"
    assert res["R8"].level == "green"  # 현재 소유권 항목은 2019년 이전 그대로


def test_r1_owner_becomes_known_again_after_named_transfer():
    req = base_request()
    req.registry.gapgu += [
        entry("3", "소유권이전", dt.date(2020, 1, 2), "매매", []),
        entry("4", "소유권일부이전", dt.date(2021, 1, 4), "매매", ["박○○"]),  # 일부이전만으로는 아직 모른다
    ]
    assert rule(req, "R1").level == "unknown"
    req.registry.gapgu.append(entry("5", "소유권이전", dt.date(2022, 1, 3), "매매", ["김○○"]))
    assert rule(req, "R1").level == "green"


def test_r1_holderless_row_without_rank_means_owner_unknown():
    req = base_request()
    req.registry.gapgu.append(entry("", "소유권이전", dt.date(2020, 1, 2), "매매", []))
    assert rule(req, "R1").level == "unknown"


@pytest.mark.parametrize(
    "masked", ["850315-1xxxxxx", "850315-1XXXXXX", "850315-1○○○○○○", "850315-1●●●●●●", "850315-1******"]
)
def test_r1_names_with_other_mask_characters(masked):
    req = base_request()
    req.registry.gapgu[-1] = entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", [f"김철수 {masked}"])
    req.contract.landlord_names = ["김철수"]
    assert rule(req, "R1").level == "green"
    req.contract.landlord_names = ["박민수"]
    assert rule(req, "R1").summary == "등기부상 소유자는 김철수인데, 계약서의 임대인은 박민수예요."


def test_r1_contract_landlord_takes_precedence_over_manual():
    req = base_request()
    req.manual.landlord_name = "이○○"
    assert rule(req, "R1").level == "green"


def test_r1_r8_unknown_without_ownership_entry():
    req = base_request()
    req.registry.gapgu = [entry("1", "가압류", dt.date(2026, 1, 5), "가압류결정", ["○○캐피탈"])]
    res = results(req)
    assert res["R1"].level == "unknown"
    assert res["R1"].unknown_reason == "등기부에서 현재 소유자를 찾지 못했어요"
    assert res["R8"].level == "unknown"
    assert res["R3"].level == "red"


@pytest.mark.parametrize("gapgu", [[], [entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", ["김○○"], cancelled=True)]])
def test_gapgu_rules_unknown_without_valid_gapgu(gapgu):
    req = base_request()
    req.registry.gapgu = gapgu
    res = results(req)
    for rid in ("R1", "R2", "R3", "R8"):
        assert res[rid].level == "unknown"
        assert res[rid].unknown_reason == "등기부 갑구 항목을 확인하지 못했어요"


# ---------------------------------------------------------------------------
# R2 신탁등기
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "purpose, cause",
    [("소유권이전, 신탁", "신탁"), ("소유권이전", "신탁"), ("신탁", None)],
)
def test_r2_red_for_trust(purpose, cause):
    req = base_request()
    req.registry.gapgu.append(entry("3", purpose, dt.date(2026, 8, 26), cause, ["○○부동산신탁(주)"]))
    res = results(req)
    r = res["R2"]
    assert r.level == "red"
    assert r.title == "집이 신탁회사 소유예요"
    assert r.summary == (
        "등기부상 소유권이 ○○부동산신탁(주)에게 넘어가 있어요. 신탁회사 동의 없이 맺은 계약은 보호받기 어려워요."
    )
    assert [(e.doc, e.page) for e in r.evidence] == [("registry", 2)]
    assert res["R1"].level == "red"  # 신탁회사가 현재 소유자다


def test_r2_ignores_cancelled_trust():
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전, 신탁", dt.date(2024, 1, 2), "신탁", ["○○신탁(주)"], cancelled=True))
    assert rule(req, "R2").level == "green"


def test_r2_trust_termination_is_not_a_trust():
    req = base_request()
    req.registry.gapgu += [
        entry("3", "소유권이전, 신탁", dt.date(2024, 1, 2), "신탁", ["○○신탁(주)"], cancelled=True),
        entry("4", "소유권이전, 3번신탁등기말소", dt.date(2025, 1, 6), "신탁재산의귀속", ["김○○"]),
    ]
    res = results(req)
    assert res["R2"].level == "green"
    assert res["R1"].level == "green"


def test_r2_green_without_trust():
    assert rule(base_request(), "R2").level == "green"


# ---------------------------------------------------------------------------
# R3 압류·경매 등 제한
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "purpose", ["가압류", "압류", "가처분", "소유권이전청구권가등기", "임의경매개시결정", "강제경매개시결정"]
)
def test_r3_red(purpose):
    req = base_request()
    req.registry.gapgu.append(entry("3", purpose, dt.date(2026, 3, 2), None, ["○○캐피탈"]))
    r = rule(req, "R3")
    assert r.level == "red"
    assert r.title == "집에 압류·경매 같은 제한이 걸려 있어요"
    assert r.summary == f"2026년 3월 2일에 {purpose} 기록이 있어요. 집이 경매로 넘어가거나 소유자가 바뀔 수 있어요."
    assert r.evidence[0].doc == "registry"


def test_r3_lists_every_record_with_its_date():
    req = base_request()
    req.registry.gapgu += [
        entry("3", "가압류", dt.date(2026, 10, 1), None, ["○○캐피탈"]),
        entry("4", "압류", None, None, ["용인시"]),
    ]
    r = rule(req, "R3")
    assert r.summary == (
        "가압류(2026년 10월 1일), 압류(날짜 확인 안 됨) 기록이 있어요. 집이 경매로 넘어가거나 소유자가 바뀔 수 있어요."
    )
    assert len(r.evidence) == 2


def test_r3_single_record_without_date():
    req = base_request()
    req.registry.gapgu.append(entry("3", "가처분", None, None, ["홍○○"]))
    assert rule(req, "R3").summary.startswith("가처분(날짜 확인 안 됨) 기록이 있어요.")


def test_r3_ignores_cancelled_entries_and_removal_records():
    req = base_request()
    req.registry.gapgu += [
        entry("3", "가압류", dt.date(2025, 3, 2), None, ["○○캐피탈"], cancelled=True),
        entry("4", "3번가압류등기말소", dt.date(2025, 6, 2), "해제"),
    ]
    assert rule(req, "R3").level == "green"


# ---------------------------------------------------------------------------
# R4 임차권등기
# ---------------------------------------------------------------------------


def test_r4_red_for_housing_lease_registration_order():
    req = base_request()
    req.registry.eulgu = [entry("1", "주택임차권", dt.date(2025, 5, 2), "임차권등기명령", ["홍○○"], 150_000_000, page=3)]
    r = rule(req, "R4")
    assert r.level == "red"
    assert r.title == "이전 세입자가 보증금을 못 돌려받은 기록이 있어요"
    assert r.evidence[0].page == 3


def test_r4_red_when_cause_is_registration_order():
    req = base_request()
    req.registry.eulgu = [entry("1", "임차권설정", dt.date(2025, 5, 2), "임차권등기명령", ["홍○○"], 150_000_000)]
    assert rule(req, "R4").level == "red"


def test_r4_yellow_for_registered_lease():
    req = base_request()
    req.registry.eulgu = [entry("1", "임차권설정", dt.date(2024, 2, 1), "설정계약", ["홍○○"], 50_000_000, page=3)]
    r = rule(req, "R4")
    assert r.level == "yellow"
    assert r.title == "등기된 다른 임차인이 있어요"
    assert r.summary == "홍○○의 임차권(5,000만 원)이 먼저 등기돼 있어요."
    assert r.action == "이 금액이 내 보증금보다 먼저 돌려받는다는 점을 고려하세요."


def test_r4_green_when_eulgu_empty_or_cancelled():
    req = base_request()
    assert rule(req, "R4").level == "green"
    req.registry.eulgu = [entry("1", "주택임차권", dt.date(2025, 5, 2), "임차권등기명령", ["홍○○"], cancelled=True)]
    assert rule(req, "R4").level == "green"


# ---------------------------------------------------------------------------
# R5 시세 대비 보증금 비율
# ---------------------------------------------------------------------------


def test_r5_green_still_shows_ratio():
    r = rule(base_request(), "R5")
    assert r.level == "green"
    assert r.summary == "내 보증금 1,000만 원이 시세(2억 원, 같은 건물 실거래가)의 5%예요."
    assert [e.doc for e in r.evidence] == ["contract", "market"]
    assert r.evidence[1].text == "같은 건물 매매 실거래가 2건 기준 2억 원 (2025년 12월 ~ 2026년 11월)"


def test_r5_name_comes_from_schema():
    assert rule(base_request(), "R5").name == RULE_NAMES["R5"] == "시세 대비 보증금 비율"


@pytest.mark.parametrize(
    "market, text",
    [
        (
            MarketPrice(price=200_000_000, method="same_dong", deals=5, period="2025-12 ~ 2026-11"),
            "같은 동·비슷한 면적 매매 실거래가 (추정) 5건 기준 2억 원 (2025년 12월 ~ 2026년 11월)",
        ),
        (MarketPrice(price=200_000_000, method="same_building", deals=0), "같은 건물 매매 실거래가 2억 원"),
        (
            MarketPrice(price=200_000_000, method="same_building", deals=3, period="최근 12개월"),
            "같은 건물 매매 실거래가 3건 기준 2억 원 (최근 12개월)",
        ),
        (MarketPrice(price=200_000_000, method="manual"), "직접 입력한 시세 2억 원"),
    ],
)
def test_r5_market_evidence_wording(market, text):
    req = base_request()
    req.market = market
    r = rule(req, "R5")
    assert [(e.doc, e.text) for e in r.evidence if e.doc == "market"] == [("market", text)]
    assert "중앙값" not in r.evidence[-1].text


@pytest.mark.parametrize(
    "deposit, level, percent",
    [
        (180_000_000, "red", "90%"),
        (160_000_000, "red", "80%"),
        (159_999_999, "yellow", "79%"),
        (140_000_000, "yellow", "70%"),
        (139_999_999, "green", "69%"),
    ],
)
def test_r5_thresholds(deposit, level, percent):
    req = base_request()
    req.contract.deposit = deposit
    r = rule(req, "R5")
    assert r.level == level
    assert f"의 {percent}예요." in r.summary
    if level != "green":
        assert r.title == "보증금이 집값에 비해 위험한 수준이에요"
        assert r.summary.endswith("경매로 넘어가면 보증금을 다 돌려받지 못할 수 있어요.")
        assert r.action == "보증금을 낮추거나, 전세보증금 반환보증에 가입할 수 있는지 먼저 확인하세요."


def test_r5_adds_registered_claims_and_manual_prior_deposits():
    req = base_request()
    req.registry.eulgu = [mortgage(amount=60_000_000)]
    req.manual.prior_deposits = 40_000_000
    r = rule(req, "R5")
    assert r.level == "green"  # (6,000만 + 4,000만 + 1,000만) / 2억 = 55%
    assert r.summary.startswith("선순위 1억 원 + 내 보증금 1,000만 원 = 시세(2억 원, 같은 건물 실거래가)의 55%예요.")
    assert [e.doc for e in r.evidence] == ["registry", "manual", "contract", "market"]


def test_r5_counts_mortgage_jeonse_and_lease_rights():
    req = base_request()
    req.registry.eulgu = [
        mortgage("1", 50_000_000),
        entry("2", "전세권설정", dt.date(2024, 3, 1), "설정계약", ["홍○○"], 30_000_000),
        entry("3", "임차권설정", dt.date(2024, 4, 1), "설정계약", ["윤○○"], 20_000_000),
    ]
    req.contract.deposit = 60_000_000
    r = rule(req, "R5")
    assert r.level == "red"  # (1억 + 6,000만) / 2억 = 80%
    assert "선순위 1억 원 + 내 보증금 6,000만 원" in r.summary
    assert "80%" in r.summary


def test_r5_amended_mortgage_is_not_double_counted():
    req = base_request()
    req.registry.eulgu = [
        mortgage("1", 120_000_000),
        entry("1-1", "1번근저당권변경", dt.date(2025, 2, 3), "변경계약", [], 60_000_000),
        entry("1-2", "1번근저당권이전", dt.date(2025, 3, 3), "확정채권양도", ["○○캐피탈"]),
    ]
    res = results(req)
    assert res["R5"].summary.startswith("선순위 6,000만 원 + 내 보증금 1,000만 원")
    assert res["R6"].summary == "채권최고액 등 6,000만 원이 내 보증금보다 먼저 돌려받아요."


def test_r5_unknown_when_claim_amount_missing():
    req = base_request()
    req.registry.eulgu = [mortgage(amount=None)]
    r = rule(req, "R5")
    assert r.level == "unknown"
    assert r.unknown_reason == "선순위 권리 중 금액을 읽지 못한 항목이 있어요"


def test_r5_unknown_for_multi_household_building():
    req = base_request()
    req.registry.registry_type = "건물"
    req.registry.building_use_lines = ["철근콘크리트구조 (철근)콘크리트지붕 4층 다가구주택"]
    r = rule(req, "R5")
    assert r.level == "unknown"
    assert r.unknown_reason == "다가구는 시세를 추정하기 어려워요"


def test_r5_deposit_from_contract_then_manual():
    req = base_request()
    req.contract.deposit = None
    r = rule(req, "R5")
    assert r.level == "unknown"
    assert r.unknown_reason == "보증금을 확인하지 못했어요"
    req.manual.deposit = 150_000_000
    r = rule(req, "R5")
    assert r.level == "yellow"  # 75%
    assert "manual" in [e.doc for e in r.evidence]
    req.contract.deposit = 10_000_000  # 계약서 값이 먼저다
    assert rule(req, "R5").level == "green"


def test_r5_market_price_sources():
    req = base_request()
    req.market = None
    r = rule(req, "R5")
    assert r.level == "unknown"
    assert r.unknown_reason == "시세 정보가 없어요"

    req.manual.market_price = 100_000_000
    r = rule(req, "R5")
    assert r.level == "green"
    assert "시세(1억 원, 직접 입력)의 10%예요." in r.summary
    assert r.evidence[-1].doc == "manual"

    # 사용자가 직접 입력한 시세가 조회한 시세보다 먼저다
    req.market = MarketPrice(price=200_000_000, method="same_building", deals=2, period="2025-12 ~ 2026-11")
    r = rule(req, "R5")
    assert "시세(1억 원, 직접 입력)의 10%예요." in r.summary
    assert r.evidence[-1].doc == "manual"

    req.manual.market_price = None  # 직접 입력이 없으면 조회한 시세
    assert "시세(2억 원, 같은 건물 실거래가)의 5%예요." in rule(req, "R5").summary

    req.market = MarketPrice(price=200_000_000, method="same_dong", deals=5, period="2025-12 ~ 2026-11")
    r = rule(req, "R5")
    assert "시세(2억 원, 같은 동 비슷한 집 추정)" in r.summary
    assert r.evidence[-1].doc == "market"
    assert "추정" in r.evidence[-1].text

    req.market = MarketPrice(price=None, method="same_dong", deals=0)
    assert rule(req, "R5").unknown_reason == "시세 정보가 없어요"


@pytest.mark.parametrize("typed", [0, -1, -100_000_000])
def test_r5_typed_price_of_zero_or_less_counts_as_not_entered(typed):
    req = base_request()
    req.manual.market_price = typed
    r = rule(req, "R5")
    assert r.level == "green"
    assert "시세(2억 원, 같은 건물 실거래가)의 5%예요." in r.summary  # 조회한 시세를 쓴다
    assert "manual" not in [e.doc for e in r.evidence]
    req.market = None
    assert rule(req, "R5").unknown_reason == "시세 정보가 없어요"


@pytest.mark.parametrize("price", [0, -100_000_000])
def test_r5_looked_up_price_of_zero_or_less_is_unknown(price):
    req = base_request()
    req.market = MarketPrice(price=price, method="same_building", deals=1)
    r = rule(req, "R5")
    assert r.level == "unknown"
    assert r.unknown_reason == "시세 값이 올바르지 않아요"


# ---------------------------------------------------------------------------
# R6 먼저 잡힌 담보·전세권
# ---------------------------------------------------------------------------


def test_r6_yellow_for_mortgage():
    req = base_request()
    req.registry.eulgu = [mortgage(amount=120_000_000)]
    r = rule(req, "R6")
    assert r.level == "yellow"
    assert r.title == "집에 먼저 잡힌 빚(근저당 등)이 있어요"
    assert r.summary == "채권최고액 등 1억 2,000만 원이 내 보증금보다 먼저 돌려받아요."
    assert r.evidence[0].page == 3


def test_r6_yellow_for_jeonse_right_and_sums_all():
    req = base_request()
    req.registry.eulgu = [
        mortgage("1", 120_000_000),
        entry("2", "전세권설정", dt.date(2024, 3, 1), "설정계약", ["홍○○"], 30_000_000),
    ]
    assert rule(req, "R6").summary == "채권최고액 등 1억 5,000만 원이 내 보증금보다 먼저 돌려받아요."


def test_r6_missing_amount_wording():
    req = base_request()
    req.registry.eulgu = [mortgage(amount=None)]
    assert rule(req, "R6").summary == "채권최고액 등 확인되지 않은 금액이 내 보증금보다 먼저 돌려받아요."
    req.registry.eulgu.append(mortgage("2", 50_000_000))
    assert rule(req, "R6").summary == "채권최고액 등 5,000만 원 이상이 내 보증금보다 먼저 돌려받아요."


def test_r6_green_when_none_cancelled_or_removed():
    req = base_request()
    assert rule(req, "R6").level == "green"
    req.registry.eulgu = [mortgage(cancelled=True), entry("2", "1번근저당권설정등기말소", dt.date(2025, 1, 2), "해지")]
    assert rule(req, "R6").level == "green"


# ---------------------------------------------------------------------------
# R7 다가구·단독
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    ["철근콘크리트구조 (철근)콘크리트지붕 4층 다가구주택", "시멘트벽돌조 슬래브지붕 2층 단독주택", "철근콘크리트구조 5층 다중주택"],
)
def test_r7_yellow_for_single_owner_buildings(line):
    req = base_request()
    req.registry.registry_type = "건물"
    req.registry.building_use_lines = [line, "1층 120.00㎡"]
    r = rule(req, "R7")
    assert r.level == "yellow"
    assert r.title == "다른 세입자 보증금을 등기부로는 알 수 없어요"
    assert [e.text for e in r.evidence] == [line]


def test_r7_green_for_collective_building():
    assert rule(base_request(), "R7").level == "green"


def test_r7_unknown_cases():
    req = base_request()
    req.registry.registry_type = None
    assert rule(req, "R7").level == "unknown"
    req.registry.registry_type = "건물"
    req.registry.building_use_lines = ["철근콘크리트구조 3층 제2종근린생활시설"]
    r = rule(req, "R7")
    assert r.level == "unknown"
    assert r.unknown_reason


# ---------------------------------------------------------------------------
# R8 최근 소유권 변동
# ---------------------------------------------------------------------------


def test_r8_yellow_for_recent_transfer():
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 9, 15), "매매", ["김○○"]))
    r = rule(req, "R8")
    assert r.level == "yellow"
    assert r.title == "최근에 집주인이 바뀌었어요"
    assert r.summary == (
        "2026년 9월 15일에 소유권이 매매로 바뀌었어요 (기준일 60일 전). "
        "매매와 전세 계약을 동시에 진행하는 수법에서 자주 보이는 패턴이에요."
    )
    assert [(e.doc, e.page) for e in r.evidence] == [("registry", 2)]


@pytest.mark.parametrize("days, level", [(0, "yellow"), (1, "yellow"), (90, "yellow"), (91, "green")])
def test_r8_boundary(days, level):
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", TODAY - dt.timedelta(days=days), "매매", ["김○○"]))
    assert rule(req, "R8").level == level


@pytest.mark.parametrize(
    "cause",
    [
        "2026년8월20일 상속",
        "2026년 8월 20일 상속",
        "2026년8월20일자 상속",
        "[2026년8월20일] 상속",
        "(2026년 8월 20일자) 상속",
        "2026-08-20 상속",
        "2026-08-20상속",
        "2026. 8. 20. 상속",
        "2026.08.20 상속",
        "2026/08/20 상속",
        "20260820 상속",
    ],
)
def test_r8_strips_date_from_cause_in_any_format(cause):
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 10, 1), cause, ["김○○"]))
    assert "소유권이 상속으로 바뀌었어요 (기준일 44일 전)" in rule(req, "R8").summary


@pytest.mark.parametrize("cause", [None, "2026-08-20", "2026년8월20일자"])
def test_r8_without_cause(cause):
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 10, 1), cause, ["김○○"]))
    assert rule(req, "R8").summary.startswith("2026년 10월 1일에 소유권이 바뀌었어요 (기준일 44일 전).")


def test_r8_keeps_causes_that_start_with_ja():
    """날짜에 붙은 "자"만 뗀다. 띄어 쓴 다음 낱말의 첫 글자는 건드리지 않는다."""
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 10, 1), "2026년8월20일 자산양도", ["김○○"]))
    assert "소유권이 자산양도로 바뀌었어요" in rule(req, "R8").summary


def test_r8_unknown_without_received_date():
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", None, "매매", ["김○○"]))
    r = rule(req, "R8")
    assert r.level == "unknown"
    assert r.unknown_reason == "소유권 접수일을 확인하지 못했어요"


def test_r8_base_date_precedence():
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 8, 1), "매매", ["김○○"]))
    assert rule(req, "R8").level == "green"  # 계약일 2026-11-14 기준 105일
    req.contract.contract_date = None
    req.manual.contract_date = dt.date(2026, 10, 1)
    assert rule(req, "R8").level == "yellow"  # 계약 예정일 기준 61일
    req.manual.contract_date = None
    assert rule(req, "R8").level == "green"  # today 기준 105일
    req.today = dt.date(2026, 9, 1)
    assert rule(req, "R8").level == "yellow"
    req.contract.contract_date = dt.date(2026, 12, 1)
    req.manual.contract_date = dt.date(2026, 9, 1)
    assert rule(req, "R8").level == "green"  # 계약서 계약일이 가장 먼저다


# ---------------------------------------------------------------------------
# R9 위반건축물
# ---------------------------------------------------------------------------


def test_r9_levels():
    req = base_request()
    assert rule(req, "R9").level == "green"
    req.building.is_violating = True
    req.building.source_text = "위반건축물 (무단 증축)"
    r = rule(req, "R9")
    assert r.level == "red"
    assert r.title == "불법 건축물로 등록돼 있어요"
    assert [(e.doc, e.text) for e in r.evidence] == [("building", "위반건축물 (무단 증축)")]
    req.building.is_violating = None
    assert rule(req, "R9").level == "unknown"
    req.building = None
    r = rule(req, "R9")
    assert r.level == "unknown"
    assert r.unknown_reason == "건축물대장 정보가 없어요"


# ---------------------------------------------------------------------------
# R10 주거용이 아닌 용도
# ---------------------------------------------------------------------------


def test_r10_building_unit_use_comes_first():
    req = base_request()
    req.building = BuildingRegister(main_use="제2종근린생활시설", unit_use="다세대주택", is_violating=False)
    r = rule(req, "R10")
    assert r.level == "green"
    assert r.evidence[0].doc == "building"


def test_r10_yellow_from_building_register():
    req = base_request()
    req.building = BuildingRegister(main_use="제2종근린생활시설", is_violating=False)
    r = rule(req, "R10")
    assert r.level == "yellow"
    assert r.title == "주거용이 아닌 건물로 등록돼 있어요"
    assert r.summary == "이 호실의 용도는 '제2종근린생활시설'이에요. 주거용으로 쓰면 불법 용도변경일 수 있어요."
    assert r.evidence[0].doc == "building"


def test_r10_officetel_counts_as_residential():
    req = base_request()
    req.building = BuildingRegister(main_use="업무시설", unit_use="업무시설(오피스텔)", is_violating=False)
    assert rule(req, "R10").level == "green"


def test_r10_building_without_use_falls_back_to_registry():
    req = base_request()
    req.building = BuildingRegister(is_violating=False)
    r = rule(req, "R10")
    assert r.level == "green"
    assert [(e.doc, e.text) for e in r.evidence] == [("registry", "3층 다세대주택 112.30㎡")]


def test_r10_registry_picks_only_my_floor():
    req = base_request()
    req.building = None
    req.registry.building_use_lines = [
        "철근콘크리트구조 (철근)콘크리트지붕 13층 공동주택",
        "지하3층 주차장 500.00㎡",
        "3층 제2종근린생활시설(사무소) 300.00㎡",
        "13층 다세대주택 300.00㎡",
    ]
    r = rule(req, "R10")
    assert r.level == "yellow"
    assert r.summary.startswith("이 호실의 용도는 '제2종근린생활시설(사무소)'예요.")
    assert [e.text for e in r.evidence] == ["3층 제2종근린생활시설(사무소) 300.00㎡"]

    req.registry.unit = RegistryUnit(ho="1302호", floor="13층")
    r = rule(req, "R10")
    assert r.level == "green"
    assert [e.text for e in r.evidence] == ["13층 다세대주택 300.00㎡"]  # 층별 줄이 건물 전체 줄보다 먼저


def registry_r10(lines, floor="3층", ho="302호"):
    """건축물대장 없이 등기부 용도 줄로만 R10을 계산한다."""
    req = base_request()
    req.building = None
    req.registry.building_use_lines = list(lines)
    req.registry.unit = RegistryUnit(ho=ho, floor=floor)
    return rule(req, "R10")


HEADER_RES = "철근콘크리트구조 (철근)콘크리트지붕 4층 공동주택(다세대주택)"


def test_r10_floor_from_ho_when_floor_missing():
    assert registry_r10(USE_LINES, floor=None).level == "green"  # 302호 → 3층
    r = registry_r10(USE_LINES, floor=None, ho=None)  # 층을 모르면 건물 전체 줄로 판정
    assert r.level == "green"
    assert [e.text for e in r.evidence] == [HEADER_RES]


def test_r10_realistic_area_only_floor_lines_use_whole_building_line():
    """실제 표제부: 층별 줄에는 면적만 있고 용도는 건물 전체 줄에만 있다."""
    lines = [HEADER_RES, "1층 66.20㎡", "2층 112.30㎡", "3층 112.30㎡", "4층 98.10㎡"]
    r = registry_r10(lines)
    assert r.level == "green"
    assert [e.text for e in r.evidence] == [HEADER_RES]


def test_r10_split_header_layout():
    lines = ["철근콘크리트구조", "(철근)콘크리트지붕 4층", "다세대주택", "1층 66.20㎡", "2층 112.30㎡", "3층 112.30㎡", "4층 98.10㎡"]
    r = registry_r10(lines)
    assert r.level == "green"
    assert [e.text for e in r.evidence] == ["다세대주택"]


def test_r10_whole_building_line_is_never_a_floor_line():
    lines = [HEADER_RES, "1층 제2종근린생활시설"]
    assert registry_r10(lines).level == "green"
    # 4층 호실이어도 건물 전체 줄의 "4층"을 층별 줄로 보지 않는다 → 3층과 같은 판정
    assert registry_r10(lines, floor="4층", ho="402호").level == "green"


def test_r10_header_only_non_residential_is_yellow():
    r = registry_r10(["철근콘크리트구조 철근콘크리트지붕 5층 제2종근린생활시설"])
    assert r.level == "yellow"
    assert r.summary.startswith("이 호실의 용도는 '제2종근린생활시설'이에요.")


def test_r10_my_floor_line_with_use_decides_first():
    lines = [HEADER_RES, "1층 다세대주택", "3층 제2종근린생활시설"]
    r = registry_r10(lines)
    assert r.level == "yellow"
    assert [e.text for e in r.evidence] == ["3층 제2종근린생활시설"]
    lines = ["철근콘크리트구조 (철근)콘크리트지붕 4층 제2종근린생활시설", "3층 다세대주택"]
    assert registry_r10(lines).level == "green"


def test_r10_mixed_building_without_my_floor_use_is_unknown():
    lines = ["철근콘크리트구조 (철근)콘크리트지붕 5층 제2종근린생활시설 및 다세대주택", "3층 112.30㎡"]
    r = registry_r10(lines)
    assert r.level == "unknown"
    assert r.unknown_reason == "주거용과 비주거용이 섞인 건물이라 내 층의 용도를 알 수 없어요"
    lines = ["철근콘크리트구조 (철근)콘크리트지붕 5층 공동주택", "제1종근린생활시설"]  # 건물 전체 줄 + 기타 줄
    assert registry_r10(lines).level == "unknown"


def test_r10_officetel_header_is_residential():
    assert registry_r10(["철근콘크리트구조 (철근)콘크리트지붕 15층 업무시설(오피스텔)", "3층 120.00㎡"]).level == "green"


@pytest.mark.parametrize("ho", ["지하101호", "지101호", "B101호", "비101호"])
def test_r10_basement_ho_is_unknown(ho):
    lines = [HEADER_RES, "지하1층 제2종근린생활시설", "1층 다세대주택"]
    r = registry_r10(lines, floor=None, ho=ho)
    assert r.level == "unknown"
    assert r.unknown_reason == "지하 호실은 등기부 용도 줄로 층을 확인하지 못했어요"


def test_r10_basement_floor_field_matches_basement_lines():
    lines = [HEADER_RES, "지하1층 제2종근린생활시설", "1층 다세대주택"]
    assert registry_r10(lines, floor="지하1층", ho="B101호").level == "yellow"


def test_r10_unknown_when_no_use_anywhere():
    r = registry_r10(["1층 다세대주택 66.20㎡", "2층 다세대주택 112.30㎡"])  # 내 층 줄도, 건물 전체 줄도 없다
    assert r.level == "unknown"
    assert r.unknown_reason == "등기부 용도 줄에서 용도를 찾지 못했어요"
    assert registry_r10(["철근콘크리트구조 (철근)콘크리트지붕 4층", "3층 112.30㎡"]).level == "unknown"
    assert registry_r10([]).level == "unknown"


def test_r10_header_line_is_used_when_there_are_no_floor_lines():
    assert registry_r10(["철근콘크리트구조 (철근)콘크리트지붕 3층 다세대주택"]).level == "green"


def test_r10_non_collective_uses_every_line():
    req = base_request()
    req.building = None
    req.registry.registry_type = "건물"
    req.registry.building_use_lines = ["철근콘크리트구조 4층 다가구주택", "1층 제1종근린생활시설 100.00㎡"]
    assert rule(req, "R10").level == "green"
    req.registry.building_use_lines = ["철근콘크리트구조 3층 제2종근린생활시설"]
    assert rule(req, "R10").level == "yellow"


# ---------------------------------------------------------------------------
# R11 주소·호수 불일치
# ---------------------------------------------------------------------------


def test_r11_red_when_ho_differs():
    req = base_request()
    req.contract.unit.ho = "303호"
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 303호"
    r = rule(req, "R11")
    assert r.level == "red"
    assert r.title == "계약서의 호수가 등기부와 달라요"
    assert r.summary == (
        "등기부는 302호, 계약서는 303호예요. 전입신고 주소가 등기와 다르면 대항력을 인정받지 못할 수 있어요."
    )
    assert r.action == "계약서와 전입신고에 등기부 표기를 그대로 적으세요."
    assert [e.doc for e in r.evidence] == ["registry", "contract"]


def test_r11_red_when_contract_has_no_ho():
    req = base_request()
    req.contract.unit.ho = None
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라"
    r = rule(req, "R11")
    assert r.level == "red"
    assert r.summary.startswith("등기부는 302호인데, 계약서에는 호수가 없어요.")


def test_r11_reads_ho_and_dong_from_contract_address():
    req = base_request()
    req.contract.unit.ho = None
    assert rule(req, "R11").level == "green"  # 주소의 "302호"
    req.registry.unit.dong = "101동"
    assert rule(req, "R11").level == "red"  # 계약서에 동이 없다
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 101동 302호"
    assert rule(req, "R11").level == "green"


def test_r11_red_when_dong_differs():
    req = base_request()
    req.registry.unit.dong = "101동"
    req.contract.unit.dong = "102동"
    r = rule(req, "R11")
    assert r.level == "red"
    assert r.summary.startswith("등기부는 101동 302호, 계약서는 102동 302호예요.")


def test_r11_normalizes_je_ho_and_beonji():
    req = base_request()
    req.contract.unit = ContractUnit(dong=None, ho="제302호")
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4번지 제302호"
    assert rule(req, "R11").level == "green"


def r11(registry_ho="302호", contract_ho="302호", address=None, registry_dong=None, contract_dong=None):
    req = base_request()
    req.registry.unit = RegistryUnit(dong=registry_dong, ho=registry_ho, floor="3층")
    req.contract.unit = ContractUnit(dong=contract_dong, ho=contract_ho)
    if address is not None:
        req.contract.address = address
    return rule(req, "R11")


@pytest.mark.parametrize(
    "registry_ho, contract_ho",
    [("B102호", "102호"), ("지하102호", "102호"), ("비102호", "102호"), ("302호", "B302호"), ("302호", "302-1호")],
)
def test_r11_compares_whole_ho_including_basement_and_hyphen(registry_ho, contract_ho):
    assert r11(registry_ho, contract_ho).level == "red"


@pytest.mark.parametrize(
    "registry_ho, contract_ho",
    [
        ("B102호", "지하102호"),
        ("지하102호", "비102호"),
        ("b102", "B102호"),
        ("제302호", "302"),
        ("302 호", "302호"),
        ("0302호", "302호"),  # 숫자 앞의 0은 무시한다
        ("302호", "0302호"),
        ("B0102호", "지하102호"),
    ],
)
def test_r11_same_ho_in_different_spellings_is_green(registry_ho, contract_ho):
    assert r11(registry_ho, contract_ho).level == "green"


def test_r11_basement_floor_before_ho_in_address():
    address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 지하1층 102호"
    assert r11("B102호", None, address).level == "green"  # "지하1층 102호" = "B102호"
    r = r11("102호", None, address)
    assert r.level == "red"
    assert r.summary.startswith("등기부는 102호, 계약서는 지하102호예요.")


def test_r11_shows_ho_as_written():
    r = r11("302호", "302-1호")
    assert r.summary.startswith("등기부는 302호, 계약서는 302-1호예요.")
    r = r11("지하102호", "102호")
    assert r.summary.startswith("등기부는 지하102호, 계약서는 102호예요.")


A_PREFIX = "경기도 용인시 수지구 죽전동 123-4"


@pytest.mark.parametrize(
    "address, registry_dong, registry_ho",
    [
        (f"{A_PREFIX} 죽전○○빌라302호", None, "302호"),  # 띄어쓰기 없음
        (f"{A_PREFIX} ○○아파트 101동302호", "101동", "302호"),
        (f"{A_PREFIX} 죽전○○빌라 지하102호", None, "지하102호"),
        (f"{A_PREFIX} 죽전○○빌라 B102호", None, "비102호"),
        (f"{A_PREFIX} ○○빌라 가동 302호", "가동", "302호"),  # 한글 한 글자 동
        (f"{A_PREFIX} ○○빌라 A동 302호", "A동", "302호"),
    ],
)
def test_r11_reads_unit_from_address_spellings(address, registry_dong, registry_ho):
    assert r11(registry_ho, None, address, registry_dong=registry_dong).level == "green"


def test_r11_hangul_letter_dong_mismatch_names_both_dongs():
    r = r11("302호", None, f"{A_PREFIX} ○○빌라 나동 302호", registry_dong="가동")
    assert r.level == "red"
    assert r.summary.startswith("등기부는 가동 302호, 계약서는 나동 302호예요.")


def test_r11_legal_dong_is_not_a_building_dong():
    r = r11("302호", None, "경기도 용인시 수지구 죽전동 123-4 302호", registry_dong="101동")
    assert r.level == "red"  # 계약서에 건물 동이 없다 ("죽전동"은 법정동)
    assert r.summary.startswith("등기부는 101동 302호, 계약서는 302호예요.")


def test_r11_dong_compared_even_when_registry_ho_unknown():
    r = r11(None, "302호", registry_dong="101동", contract_dong="102동")
    assert r.level == "red"
    assert r.summary.startswith("등기부는 101동, 계약서는 102동 302호예요.")


def test_r11_road_address_is_enough():
    req = base_request()
    req.contract.address = "경기도 용인시 수지구 포은대로 123, 302호"
    assert rule(req, "R11").level == "green"


@pytest.mark.parametrize(
    "address",
    ["경기도 용인시 수지구 보정동 55-1 302호", "경기도 용인시 수지구 죽전동 123-45 302호"],
)
def test_r11_yellow_when_base_address_not_found(address):
    req = base_request()
    req.contract.address = address
    r = rule(req, "R11")
    assert r.level == "yellow"
    assert r.title == "계약서 주소가 등기부와 같은지 확인이 필요해요"
    assert r.summary == "계약서 주소에서 등기부의 지번이나 도로명을 찾지 못했어요."


def test_r11_non_collective_skips_unit_check():
    req = base_request()
    req.registry.registry_type = "건물"
    req.registry.unit = RegistryUnit()
    req.contract.unit.ho = "203호"
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 ○○하우스 203호"
    assert rule(req, "R11").level == "green"


def test_r11_unknown_cases():
    req = base_request()
    req.registry.unit.ho = None
    r = rule(req, "R11")
    assert r.level == "unknown"
    assert r.unknown_reason == "등기부에서 호수를 확인하지 못했어요"

    req = base_request()
    req.registry.address_jibun = None
    req.registry.address_road = None
    assert rule(req, "R11").level == "unknown"

    req = base_request()
    req.contract.address = None
    r = rule(req, "R11")
    assert r.level == "unknown"
    assert r.unknown_reason == "계약서 주소가 없어요"

    req.contract = None
    assert rule(req, "R11").level == "unknown"


# ---------------------------------------------------------------------------
# R12 보호 특약 없음
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "term",
    [
        "임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다.",
        "임대인은 잔금일까지 근저당권을 말소한다.",
        "임대인은 이 집을 담보로 제공하지 않는다.",
        "임대인은 잔금 전에 새로운 권리를 설정 하지 않는다.",
    ],
)
def test_r12_green_with_protective_term(term):
    req = base_request()
    req.contract.special_terms = ["반려동물은 키우지 않는다.", term]
    r = rule(req, "R12")
    assert r.level == "green"
    assert [e.text for e in r.evidence] == [term]


def test_r12_yellow_without_protective_term():
    req = base_request()
    req.contract.special_terms = ["반려동물은 키우지 않는다."]
    r = rule(req, "R12")
    assert r.level == "yellow"
    assert r.title == "보증금을 지키는 특약이 없어요"
    assert r.evidence[0].text == "반려동물은 키우지 않는다."
    req.contract.special_terms = []
    r = rule(req, "R12")
    assert r.level == "yellow"
    assert [(e.doc, e.text) for e in r.evidence] == [("contract", "특약 없음")]


def test_r12_unknown_without_contract():
    req = base_request()
    req.contract = None
    r = rule(req, "R12")
    assert r.level == "unknown"
    assert r.unknown_reason == "계약서가 없어 특약을 확인하지 못했어요"


# ---------------------------------------------------------------------------
# R13 오래된 등기부
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "viewed, level",
    [
        (dt.datetime(2026, 11, 14, 9, 0, tzinfo=KST), "green"),
        (dt.datetime(2026, 11, 12, 9, 0, tzinfo=KST), "green"),
        (dt.datetime(2026, 11, 11, 23, 59, tzinfo=KST), "yellow"),
        (dt.datetime(2026, 11, 11, 16, 0, tzinfo=dt.timezone.utc), "green"),  # 한국 시각 11월 12일 01:00
        (dt.datetime(2026, 11, 11, 20, 0), "yellow"),  # 시간대 없음 → 한국 시각 (UTC로 보면 12일이 된다)
    ],
)
def test_r13_levels(viewed, level):
    req = base_request()
    req.registry.viewed_at = viewed
    assert rule(req, "R13").level == level


def test_r13_copy_and_unknown():
    req = base_request()
    req.registry.viewed_at = dt.datetime(2026, 11, 9, 14, 25, tzinfo=KST)
    r = rule(req, "R13")
    assert r.title == "5일 전에 뗀 등기부예요"
    assert r.summary == "그 사이에 근저당 등이 새로 생겼을 수 있어요."
    assert r.action == "계약 당일과 잔금 당일에 등기부를 다시 떼어 보세요."
    assert r.evidence[0].text == "열람 일시 2026년 11월 9일 14:25"
    req.registry.viewed_at = None
    r = rule(req, "R13")
    assert r.level == "unknown"
    assert r.unknown_reason == "등기부 열람 일시를 확인하지 못했어요"


def test_r13_compares_with_today_not_contract_date():
    req = base_request()
    req.contract.contract_date = dt.date(2026, 11, 30)
    assert rule(req, "R13").level == "green"


# ---------------------------------------------------------------------------
# 종합 판정, 순서, 리포트
# ---------------------------------------------------------------------------


def worst_request() -> CheckRequest:
    """거의 모든 규칙이 🔴·🟡가 되는 요청."""
    req = base_request()
    req.registry.gapgu += [
        entry("3", "소유권이전, 신탁", dt.date(2026, 8, 26), "신탁", ["○○부동산신탁(주)"]),
        entry("4", "가압류", dt.date(2026, 9, 1), "가압류결정", ["○○캐피탈"]),
    ]
    req.registry.eulgu = [
        mortgage("1", 120_000_000),
        entry("2", "주택임차권", dt.date(2025, 5, 2), "임차권등기명령", ["홍○○"], 50_000_000),
    ]
    req.registry.viewed_at = dt.datetime(2026, 11, 1, 10, 0, tzinfo=KST)
    req.contract.unit.ho = "303호"
    req.contract.special_terms = []
    req.contract.lease_type = "전세"
    req.contract.deposit = 150_000_000
    req.building = BuildingRegister(main_use="제2종근린생활시설", is_violating=True)
    return req


def test_results_are_ordered_by_level_then_rule_number():
    req = worst_request()
    req.market = None
    report = build_report(req)
    assert [(r.id, r.level) for r in report.results] == [
        ("R1", "red"),
        ("R2", "red"),
        ("R3", "red"),
        ("R4", "red"),
        ("R9", "red"),
        ("R11", "red"),
        ("R6", "yellow"),
        ("R8", "yellow"),
        ("R10", "yellow"),
        ("R12", "yellow"),
        ("R13", "yellow"),
        ("R5", "unknown"),
        ("R7", "green"),
    ]
    assert report.counts == Counts(red=6, yellow=5, unknown=1, green=1)
    assert report.overall.level == "red"
    assert report.overall.title == "계약 보류 권장"
    assert report.overall.message == "보증금을 잃을 수 있는 위험 신호가 6개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요."
    assert report.overall.unknown_note == "확인하지 못한 항목 1개"


def test_red_and_yellow_cards_have_copy_and_evidence():
    variants = [worst_request()]
    req = base_request()  # R1 🟡, R4 🟡, R7 🟡, R11 🟡
    req.registry.registry_type = "건물"
    req.registry.building_use_lines = ["철근콘크리트구조 4층 다가구주택"]
    req.registry.gapgu[-1] = entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", ["김○○", "박○○"])
    req.registry.eulgu = [entry("1", "임차권설정", dt.date(2024, 2, 1), "설정계약", ["홍○○"], 50_000_000)]
    req.contract.address = "경기도 용인시 수지구 보정동 55-1 203호"
    variants.append(req)
    seen = set()
    for variant in variants:
        for r in build_report(variant).results:
            if r.level in ("red", "yellow"):
                seen.add((r.id, r.level))
                assert r.title and r.summary and r.action, r.id
                assert r.evidence, r.id
                assert all(e.text for e in r.evidence), r.id
                assert r.unknown_reason is None
    assert {("R1", "yellow"), ("R4", "yellow"), ("R7", "yellow"), ("R11", "yellow")} <= seen


def test_no_banned_phrases_in_any_copy():
    for req in (worst_request(), base_request()):
        report = build_report(req)
        texts = [report.overall.title, report.overall.message, report.request_message, report.disclaimer]
        texts += report.special_terms + [c.title for c in report.checklist]
        for r in report.results:
            texts += [r.title, r.summary, r.action, r.unknown_reason or ""] + [e.text for e in r.evidence]
        for text in texts:
            for phrase in content.BANNED_PHRASES:
                assert phrase not in text


ID_SHAPE = re.compile(r"\d{6}\s*-\s*[\d*]{7}")  # 가리지 않은 앞자리가 보이는 등록번호


def test_evidence_masks_id_numbers_and_keeps_the_rest_verbatim():
    req = base_request()
    req.registry.gapgu[-1] = Entry(
        rank="2",
        purpose="소유권이전",
        received_at=dt.date(2019, 6, 21),
        cause="매매",
        holders=["김○○"],
        page=2,
        source_text="2 소유권이전 2019년6월21일 제45678호 2019년5월30일 매매 소유자 김○○ 850315-******* 서울특별시 송파구",
    )
    req.contract.sources.landlord = "임대인 성명 김○○ 주민등록번호 850315-1234567 주소 서울특별시 송파구"
    r = rule(req, "R1")
    assert [(e.doc, e.text) for e in r.evidence] == [
        ("registry", "2 소유권이전 2019년6월21일 제45678호 2019년5월30일 매매 소유자 김○○ ******-******* 서울특별시 송파구"),
        ("contract", "임대인 성명 김○○ 주민등록번호 ******-******* 주소 서울특별시 송파구"),
    ]


def test_no_id_numbers_in_generated_text_or_evidence():
    req = worst_request()
    for e in req.registry.gapgu + req.registry.eulgu:
        e.holders = [f"{h} 850315-1234567" for h in e.holders]
        e.source_text = f"{e.source_text} 850315-1******"
    req.contract.landlord_names = ["이민준 900101-1234567"]
    req.contract.sources.landlord = "임대인 이민준 900101-1234567"
    report = build_report(req)
    texts = [report.overall.message, report.request_message] + report.special_terms
    for r in report.results:
        texts += [r.title, r.summary, r.action, r.unknown_reason or ""] + [e.text for e in r.evidence]
    assert [t for t in texts if ID_SHAPE.search(t)] == []
    assert "등기부상 소유권이 ○○부동산신탁(주)에게" in {r.id: r for r in report.results}["R2"].summary  # 이름은 남는다

    req = base_request()  # R4 🟡 문구도 권리자 이름만 쓴다
    req.registry.eulgu = [entry("1", "임차권설정", dt.date(2024, 2, 1), "설정계약", ["홍○○ 850315-1234567"], 50_000_000)]
    assert rule(req, "R4").summary == "홍○○의 임차권(5,000만 원)이 먼저 등기돼 있어요."


GREEN_MESSAGE ="확인한 범위에서는 큰 위험 신호를 찾지 못했어요. 안전을 보장하는 것은 아니니 아래 할 일은 꼭 챙기세요."


def incomplete_message(n: int) -> str:
    return f"위험 신호는 찾지 못했지만, 꼭 확인해야 할 항목 {n}개를 확인하지 못했어요. 빠진 내용을 채운 뒤 다시 검사하세요."


def levels_with(**overrides: str) -> dict[str, str]:
    """모두 🟢인 등급표에서 일부만 바꾼다."""
    return {**{rid: "green" for rid in RULE_NAMES}, **overrides}


def test_core_rules_match_prd():
    assert content.CORE_RULES == ("R1", "R2", "R3", "R7", "R8", "R13")


@pytest.mark.parametrize(
    "overrides, level, title, message, note",
    [
        (
            {"R1": "red", "R2": "red", "R6": "yellow", "R8": "unknown"},
            "red",
            "계약 보류 권장",
            "보증금을 잃을 수 있는 위험 신호가 2개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요.",
            "확인하지 못한 항목 1개",
        ),
        (
            {"R6": "yellow", "R7": "yellow", "R1": "unknown", "R5": "unknown"},  # 🟡 줄이 핵심 ⚪ 줄보다 먼저
            "yellow",
            "추가 확인 필요",
            "계약 전에 확인할 것이 2개 있어요.",
            "확인하지 못한 항목 2개",
        ),
        (
            {"R1": "unknown", "R13": "unknown", "R5": "unknown"},  # {n}은 핵심 규칙 중 ⚪ 수
            "yellow",
            "확인 미완료",
            incomplete_message(2),
            "확인하지 못한 항목 3개",
        ),
        (
            {rid: "unknown" for rid in ("R5", "R9", "R10", "R11", "R12")},  # 핵심이 아닌 ⚪만 있으면 🟢
            "green",
            "큰 위험 신호 없음",
            GREEN_MESSAGE,
            "확인하지 못한 항목 5개",
        ),
        ({}, "green", "큰 위험 신호 없음", GREEN_MESSAGE, None),
    ],
)
def test_overall(overrides, level, title, message, note):
    overall = content.build_overall(levels_with(**overrides))
    assert (overall.level, overall.title, overall.message, overall.unknown_note) == (level, title, message, note)


def _no_landlord(req):
    req.contract.landlord_names = []


def _no_gapgu(req):
    req.registry.gapgu = []


def _no_registry_type(req):
    req.registry.registry_type = None


def _no_received_date(req):
    req.registry.gapgu[-1].received_at = None


def _no_viewed_at(req):
    req.registry.viewed_at = None


def _no_market(req):
    req.market = None


def _no_building(req):
    req.building = None


def _no_use(req):
    req.building = BuildingRegister(is_violating=False)
    req.registry.building_use_lines = []


def _no_registry_ho(req):
    req.registry.unit.ho = None


def _no_contract(req):  # 임대인과 보증금은 직접 입력으로 채운다
    req.contract = None
    req.manual.landlord_name = "김○○"
    req.manual.deposit = 10_000_000


@pytest.mark.parametrize(
    "mutate, unknown_ids",
    [
        (_no_landlord, {"R1"}),
        (_no_gapgu, {"R1", "R2", "R3", "R8"}),
        (_no_registry_type, {"R7"}),
        (_no_received_date, {"R8"}),
        (_no_viewed_at, {"R13"}),
        (_no_market, {"R5"}),
        (_no_building, {"R9"}),
        (_no_use, {"R10"}),
        (_no_registry_ho, {"R11"}),
        (_no_contract, {"R11", "R12"}),
    ],
)
def test_overall_when_only_some_rules_are_unknown(mutate, unknown_ids):
    req = base_request()
    mutate(req)
    report = build_report(req)
    assert {r.id for r in report.results if r.level == "unknown"} == unknown_ids
    assert {r.level for r in report.results} <= {"green", "unknown"}
    assert report.overall.unknown_note == f"확인하지 못한 항목 {len(unknown_ids)}개"
    core = unknown_ids & set(content.CORE_RULES)
    if core:
        expected = ("yellow", "확인 미완료", incomplete_message(len(core)))
    else:
        expected = ("green", "큰 위험 신호 없음", GREEN_MESSAGE)
    assert (report.overall.level, report.overall.title, report.overall.message) == expected


def test_registry_only_upload_without_landlord_is_not_green():
    req = base_request()
    req.contract = None
    req.building = None
    req.market = None
    report = build_report(req)
    assert {r.id for r in report.results if r.level == "unknown"} == {"R1", "R5", "R9", "R11", "R12"}
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert report.overall.message == incomplete_message(1)
    assert report.overall.unknown_note == "확인하지 못한 항목 5개"

    req.manual.landlord_name = "김○○"  # 임대인 이름을 채우면 핵심 규칙이 모두 판정된다
    report = build_report(req)
    assert (report.overall.level, report.overall.title, report.overall.message) == (
        "green",
        "큰 위험 신호 없음",
        GREEN_MESSAGE,
    )
    assert report.overall.unknown_note == "확인하지 못한 항목 4개"


def test_bare_registry_json_is_not_green():
    report = build_report(CheckRequest.model_validate({"registry": {}}))
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert report.overall.message == incomplete_message(6)
    assert report.overall.unknown_note == "확인하지 못한 항목 11개"


def test_red_and_yellow_rows_come_before_incomplete_row():
    req = base_request()
    req.contract.landlord_names = []  # R1 ⚪ (핵심)
    req.registry.viewed_at = dt.datetime(2026, 11, 9, 10, 0, tzinfo=KST)  # R13 🟡
    overall = build_report(req).overall
    assert (overall.level, overall.title, overall.message) == ("yellow", "추가 확인 필요", "계약 전에 확인할 것이 1개 있어요.")
    assert overall.unknown_note == "확인하지 못한 항목 1개"
    req.registry.gapgu.append(entry("3", "가압류", dt.date(2026, 10, 1), None, ["○○캐피탈"]))  # R3 🔴
    overall = build_report(req).overall
    assert (overall.level, overall.title) == ("red", "계약 보류 권장")
    assert overall.message.startswith("보증금을 잃을 수 있는 위험 신호가 1개 있어요.")


def test_report_metadata():
    report = build_report(base_request())
    assert report.mode == "live"
    assert report.today == TODAY
    assert report.generated_at.utcoffset() == dt.timedelta(hours=9)
    assert report.disclaimer == (
        "이 결과는 올려주신 서류와 공개 데이터를 정해진 기준으로 확인한 참고 정보예요. "
        "법률 자문이 아니며 보증금의 안전을 보장하지 않아요. "
        "중요한 결정 전에는 대한법률구조공단(국번 없이 132) 등 전문가와 상의하세요."
    )
    assert "☎" not in report.disclaimer  # Pretendard에 없는 글자


def test_today_defaults_to_korean_date():
    req = base_request()
    req.today = None
    assert build_report(req).today == today_kst()


# ---------------------------------------------------------------------------
# 12장 문구: 요청 메시지, 특약, 체크리스트
# ---------------------------------------------------------------------------


def test_request_message_template_and_items():
    items = content.request_items({"R1": "red", "R2": "red", "R6": "yellow"}, has_agent=False, has_mortgage=True)
    message = content.build_request_message("경기도 용인시 수지구 죽전동 123-4 302호", items)
    assert message == (
        "안녕하세요. 경기도 용인시 수지구 죽전동 123-4 302호 임대차 계약 건으로 연락드립니다.\n"
        "계약 전에 아래 내용을 확인하고 싶습니다.\n"
        "\n"
        "1. 확정일자 부여현황\n"
        "2. 국세·지방세 납세증명서\n"
        "3. 신탁원부\n"
        "4. 신탁회사(수탁자)의 임대 동의서\n"
        "5. 위임장\n"
        "6. 인감증명서\n"
        "7. 근저당 대출을 잔금일에 갚고 말소할 계획인지\n"
        "\n"
        "확정일자 부여현황과 납세증명서는 계약할 때 임대인이 보여주도록 주택임대차보호법에 정해져 있다고 알고 있습니다.\n"
        "계약일 전에 받아볼 수 있을까요? 감사합니다."
    )
    assert content.request_items({}, has_agent=False, has_mortgage=False) == ["확정일자 부여현황", "국세·지방세 납세증명서"]


def test_request_message_never_breaks_inside_a_sentence():
    """줄바꿈은 문장 끝이나 문단 사이에서만 한다."""
    message = build_report(base_request()).request_message
    for line in message.split("\n"):
        assert line == "" or line.endswith((".", "?")) or line[0].isdigit(), line


def test_request_message_mortgage_item_needs_a_mortgage_row():
    req = base_request()
    req.registry.eulgu = [entry("1", "전세권설정", dt.date(2024, 3, 1), "설정계약", ["홍○○"], 30_000_000)]
    report = build_report(req)
    assert {r.id: r.level for r in report.results}["R6"] == "yellow"
    assert "근저당 대출을 잔금일에 갚고 말소할 계획인지" not in report.request_message  # 전세권만으로는 넣지 않는다
    req.registry.eulgu.append(mortgage("2", 50_000_000))
    assert "3. 근저당 대출을 잔금일에 갚고 말소할 계획인지" in build_report(req).request_message


@pytest.mark.parametrize("ho", ["B102호", "지하102호", "302-1호"])
def test_request_message_registry_fallback_keeps_ho_as_written(ho):
    req = base_request()
    req.contract = None
    req.registry.unit.ho = ho
    first_line = build_report(req).request_message.split("\n")[0]
    assert first_line == f"안녕하세요. 경기도 용인시 수지구 포은대로 123 {ho} 임대차 계약 건으로 연락드립니다."


def test_request_message_agent_and_address_fallback():
    req = base_request()
    req.contract.agent_name = "최○○"
    message = build_report(req).request_message
    assert "3. 위임장\n4. 인감증명서" in message
    assert message.startswith("안녕하세요. 경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호 임대차 계약 건으로")

    req.contract = None
    assert build_report(req).request_message.startswith("안녕하세요. 경기도 용인시 수지구 포은대로 123 302호 임대차")
    req.registry.address_road = None
    assert build_report(req).request_message.startswith("안녕하세요. 경기도 용인시 수지구 죽전동 123-4 302호 임대차")


def test_special_terms_follow_conditions_in_table_order():
    assert content.build_special_terms({}, "월세", None) == [content.TERM_SHOW_DOCUMENTS]
    terms = content.build_special_terms({"R12": "yellow", "R6": "yellow", "R2": "red"}, "전세", "1억 2,000만 원")
    assert terms == [
        "임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다. 위반 시 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다.",
        "임대인은 잔금일까지 등기부상 근저당권(채권최고액 1억 2,000만 원)을 말소한다.",
        "임차인이 전세보증금 반환보증에 가입할 수 없는 경우 계약은 무효로 하며, 임대인은 계약금을 즉시 반환한다.",
        "임대인은 계약 체결 시 국세·지방세 납세증명서와 확정일자 부여현황을 제시한다.",
        "임대인은 잔금일 전까지 수탁자(신탁회사)의 임대 동의서를 제출한다. 제출하지 못하면 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다.",
    ]


def test_special_terms_mortgage_amount_from_registry():
    req = base_request()
    req.registry.eulgu = [mortgage("1", 120_000_000), mortgage("2", 30_000_000)]
    assert "임대인은 잔금일까지 등기부상 근저당권(채권최고액 1억 5,000만 원)을 말소한다." in build_report(req).special_terms
    req.registry.eulgu = [mortgage("1", None)]
    assert "임대인은 잔금일까지 등기부상 근저당권(채권최고액 ○○원)을 말소한다." in build_report(req).special_terms
    req.registry.eulgu = [entry("1", "전세권설정", dt.date(2024, 3, 1), "설정계약", ["홍○○"], 30_000_000)]
    report = build_report(req)
    assert {r.id: r.level for r in report.results}["R6"] == "yellow"
    assert not any("근저당권(채권최고액" in t for t in report.special_terms)  # 근저당이 없으면 넣지 않는다


def test_checklist_one_item_per_task():
    items = build_report(base_request()).checklist
    assert [(i.when, i.date, i.title) for i in items] == [
        ("계약 전", None, "등기부 다시 떼기"),
        ("계약 전", None, "확정일자 부여현황·납세증명서 받기"),
        ("계약 전", None, "임대인 신분증과 등기부 소유자 대조"),
        ("계약일", TODAY, "특약 넣기"),
        ("계약일", TODAY, "계약금은 소유자 명의 계좌로 보내기"),
        ("잔금일", dt.date(2026, 12, 1), "잔금 보내기 전 등기부 다시 떼기 (새 근저당이 없는지)"),
        ("입주일", dt.date(2026, 12, 1), "전입신고 + 확정일자 받기 (당일)"),
        ("입주 후", None, "계약서 원본 보관"),
    ]


def test_checklist_jeonse_and_date_fallbacks():
    req = base_request()
    req.contract.lease_type = "전세"
    req.contract.move_in_date = None
    req.contract.balance_date = dt.date(2026, 12, 5)
    items = build_report(req).checklist
    assert ("입주일", dt.date(2026, 12, 5)) in [(i.when, i.date) for i in items]  # 입주일이 없으면 잔금일
    assert [i.title for i in items if i.when == "입주 후"] == ["전세보증금 반환보증 가입", "계약서 원본 보관"]

    req.contract = None
    req.manual.contract_date = dt.date(2026, 11, 20)
    items = build_report(req).checklist
    assert {(i.when, i.date) for i in items if i.when in ("계약일", "잔금일", "입주일")} == {
        ("계약일", dt.date(2026, 11, 20)),
        ("잔금일", None),
        ("입주일", None),
    }


# ---------------------------------------------------------------------------
# 계약서·등기부 대조표
# ---------------------------------------------------------------------------


def comparison(req) -> dict[str, tuple]:
    """{항목: (계약서 쪽, 등기부 쪽, 등급, 결과)}"""
    report = build_report(req)
    check_crosscheck(report)
    return {row.item: (row.contract, row.registry, row.level, row.note) for row in report.comparison}


def test_comparison_base_request_all_match():
    assert comparison(base_request()) == {
        "임대인": ("김○○", "김○○", "green", "일치"),
        "소재지·호수": (
            "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호",
            "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호",
            "green",
            "일치",
        ),
        "보증금": ("1,000만 원", "시세 2억 원 (같은 건물 실거래가)", "green", "5%"),
        "계약일": ("2026년 11월 14일", "2019년 6월 21일 소유권 이전", "green", "변경 없음"),
        "특약": ("보호 특약 있음", "—", "green", "특약 있음"),
    }


def test_comparison_landlord_row():
    req = base_request()
    req.contract.landlord_names = ["이○○ 900101-1234567"]
    assert comparison(req)["임대인"] == ("이○○", "김○○", "red", "불일치")
    req.contract.landlord_names = ["김○○"]
    req.registry.gapgu[-1] = entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", ["김○○", "박○○"])
    assert comparison(req)["임대인"] == ("김○○", "김○○, 박○○", "yellow", "공동소유")
    req.contract.landlord_names = []
    assert comparison(req)["임대인"] == ("계약서에 없음", "김○○, 박○○", "unknown", "확인 못 함")
    req.manual.landlord_name = "김○○"
    assert comparison(req)["임대인"][0] == "김○○ (직접 입력)"
    req.contract = None
    req.manual.landlord_name = None
    assert comparison(req)["임대인"][0] is None  # 계약서도 직접 입력도 없다


def test_comparison_landlord_row_when_owner_unknown():
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2020, 1, 2), "매매", []))
    assert comparison(req)["임대인"] == ("김○○", "확인 못 함", "unknown", "확인 못 함")


@pytest.mark.parametrize(
    "contract_ho, address, registry_dong, contract_dong, note",
    [
        ("303호", None, None, None, "호수 다름"),
        (None, "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라", None, None, "호수 없음"),
        ("302호", None, "101동", "102동", "동 다름"),
        ("302호", "경기도 용인시 수지구 보정동 55-1 302호", None, None, "주소 확인 필요"),
    ],
)
def test_comparison_address_row_notes(contract_ho, address, registry_dong, contract_dong, note):
    req = base_request()
    req.contract.unit = ContractUnit(dong=contract_dong, ho=contract_ho)
    req.registry.unit.dong = registry_dong
    if address is not None:
        req.contract.address = address
    row = comparison(req)["소재지·호수"]
    assert row[2:] == ("yellow" if note == "주소 확인 필요" else "red", note)


def test_comparison_address_row_values():
    req = base_request()
    req.registry.unit.dong = "101동"
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라"
    req.contract.unit = ContractUnit(dong="101동", ho="302호")
    contract, registry, level, note = comparison(req)["소재지·호수"]
    assert contract == "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 101동 302호"  # 주소에 없는 동·호 칸을 붙인다
    assert registry == "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 101동 302호"
    assert (level, note) == ("green", "일치")
    req.contract = None
    assert comparison(req)["소재지·호수"] == (None, registry, "unknown", "확인 못 함")


def test_comparison_deposit_row():
    req = base_request()
    req.registry.eulgu = [mortgage(amount=100_000_000)]
    req.contract.deposit = 80_000_000
    assert comparison(req)["보증금"] == (
        "8,000만 원",
        "시세 2억 원 (같은 건물 실거래가), 선순위 1억 원",
        "red",
        "90%",
    )
    req.contract.deposit = None
    req.manual.deposit = 10_000_000
    req.manual.market_price = 100_000_000
    assert comparison(req)["보증금"] == (
        "1,000만 원 (직접 입력)",
        "시세 1억 원 (직접 입력), 선순위 1억 원",
        "red",
        "110%",
    )
    req.registry.eulgu = [mortgage(amount=None)]
    assert comparison(req)["보증금"][1:] == ("시세 1억 원 (직접 입력), 선순위 금액 확인 못 함", "unknown", "확인 못 함")
    req.registry.eulgu.append(mortgage("2", 30_000_000))
    assert comparison(req)["보증금"][1] == "시세 1억 원 (직접 입력), 선순위 3,000만 원 이상"
    req.market = None
    req.manual.market_price = None
    req.registry.eulgu = []
    assert comparison(req)["보증금"][1:] == ("시세 정보 없음", "unknown", "확인 못 함")


@pytest.mark.parametrize(
    "received, note",
    [
        (dt.date(2026, 9, 15), "60일 전 소유자 변경"),
        (TODAY, "당일 소유자 변경"),
        (dt.date(2026, 11, 20), "6일 뒤 소유자 변경"),
        (dt.date(2020, 1, 2), "변경 없음"),
    ],
)
def test_comparison_date_row(received, note):
    req = base_request()
    req.registry.gapgu.append(entry("3", "소유권이전", received, "매매", ["김○○"]))
    contract, registry, level, got = comparison(req)["계약일"]
    assert contract == "2026년 11월 14일"
    assert registry == f"{received.year}년 {received.month}월 {received.day}일 소유권 이전"
    assert got == note
    assert level == ("green" if note == "변경 없음" else "yellow")


def test_comparison_date_row_sources():
    req = base_request()
    req.contract.contract_date = None
    req.manual.contract_date = dt.date(2026, 11, 20)
    req.registry.gapgu = [entry("1", "소유권보존", dt.date(2026, 10, 1), None, ["김○○"])]
    assert comparison(req)["계약일"] == (
        "2026년 11월 20일 (직접 입력)",
        "2026년 10월 1일 소유권 보존",
        "yellow",
        "50일 전 소유자 변경",
    )
    req.registry.gapgu[0].received_at = None
    assert comparison(req)["계약일"][1:] == ("확인 못 함", "unknown", "확인 못 함")


def test_comparison_terms_row():
    req = base_request()
    req.contract.special_terms = ["반려동물은 키우지 않는다."]
    assert comparison(req)["특약"] == ("보호 특약 없음", "—", "yellow", "특약 없음")
    req.contract = None
    assert comparison(req)["특약"] == (None, "—", "unknown", "확인 못 함")


def test_comparison_row_failure_is_isolated(monkeypatch):
    from app.rules import crosscheck

    def boom(ctx, level):
        raise RuntimeError("boom")

    monkeypatch.setattr(crosscheck, "ROWS", [(i, rid, boom if rid == "R5" else f) for i, rid, f in crosscheck.ROWS])
    rows = {row.rule_id: row for row in build_report(base_request()).comparison}
    assert len(rows) == 5
    assert (rows["R5"].level, rows["R5"].contract, rows["R5"].note) == ("green", None, "해당 없음")
    assert rows["R1"].note == "일치"


# ---------------------------------------------------------------------------
# 계약서 수정 요청서
# ---------------------------------------------------------------------------


def amendment(req):
    report = build_report(req)
    check_crosscheck(report)
    return report.amendment


def test_amendment_without_fixes_drops_the_fixes_part():
    a = amendment(base_request())
    assert (a.title, a.fixes) == ("계약서 수정 요청서", [])
    assert a.text == (
        "계약서 수정 요청서\n"
        "\n"
        "대상: 경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호\n"
        "작성일: 2026년 11월 14일\n"
        "\n"
        "1. 넣어 주실 특약\n"
        "1) 임대인은 계약 체결 시 국세·지방세 납세증명서와 확정일자 부여현황을 제시한다.\n"
        "\n"
        "2. 계약 전에 받아야 할 서류\n"
        "1) 확정일자 부여현황\n"
        "2) 국세·지방세 납세증명서\n"
        "\n"
        "위 내용을 반영해 주시면 계약을 진행하고 싶습니다. 감사합니다.\n"
        "\n"
        "이 요청서는 서류를 기준으로 만든 참고 자료이며 법률 자문이 아닙니다."
    )
    assert "고칠 곳" not in a.text


def test_amendment_without_contract_is_a_pre_contract_request():
    req = base_request()
    req.contract = None
    req.manual.landlord_name = "이○○"  # R1 🔴이어도 계약서가 없으면 고칠 곳은 없다
    a = amendment(req)
    assert (a.title, a.fixes) == ("계약 전 요청서", [])
    assert a.text.startswith("계약 전 요청서\n\n대상: 경기도 용인시 수지구 포은대로 123 302호\n")
    assert "고칠 곳" not in a.text
    assert "5) 위임장" not in a.text and "3) 위임장" in a.text  # R1 🔴 → 위임장·인감증명서


def fix_lines(req) -> list[str]:
    return [line for line in amendment(req).text.split("\n") if line.startswith("- ")]


def test_amendment_address_fixes():
    req = base_request()
    req.contract.unit.ho = "303호"
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 303호"
    assert fix_lines(req) == [
        "- 소재지: 경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 303호 → "
        "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호 (등기부와 호수 다름)"
    ]
    req.contract.unit.ho = None
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라"
    assert fix_lines(req)[0].endswith("→ 경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호 (계약서에 호수 없음)")
    req.contract.unit.ho = "302호"
    req.contract.address = "경기도 용인시 수지구 보정동 55-1 302호"
    assert fix_lines(req)[0].endswith("(등기부 주소와 다르게 적힘)")


def test_amendment_landlord_fixes():
    req = base_request()
    req.contract.landlord_names = ["이○○"]
    assert fix_lines(req) == ["- 임대인: 이○○ → 김○○ 명의로 변경 (대리 계약이면 위임장·인감증명서 첨부) (등기부상 소유자와 다름)"]
    req.contract.agent_name = "최○○"
    assert fix_lines(req) == ["- 임대인: 이○○ → 소유자 김○○의 위임장·인감증명서 첨부 (대리 계약)"]
    req.contract.agent_name = None
    req.registry.gapgu.append(entry("3", "소유권이전, 신탁", dt.date(2020, 1, 2), "신탁", ["○○신탁(주)"]))
    assert fix_lines(req) == [
        "- 임대인: 이○○ → ○○신탁(주) 명의로 계약하거나 ○○신탁(주)의 임대 동의서 첨부 (등기부상 소유자는 신탁회사)"
    ]


def test_amendment_co_owner_fix_and_no_fix_when_owner_unknown():
    req = base_request()
    req.registry.gapgu[-1] = entry("2", "소유권이전", dt.date(2019, 6, 21), "매매", ["김○○", "박○○"])
    assert fix_lines(req) == ["- 임대인: 김○○ → 공동 소유자(김○○, 박○○) 모두의 동의서 첨부 (공동소유)"]
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2020, 1, 2), "매매", []))  # R1 ⚪
    assert fix_lines(req) == []


def test_amendment_both_fixes_keep_order_and_numbering():
    req = base_request()
    req.contract.unit.ho = "303호"
    req.contract.landlord_names = ["이○○"]
    a = amendment(req)
    assert [f.item for f in a.fixes] == ["소재지", "임대인"]
    headings = [line for line in a.text.split("\n") if line[:2] in ("1.", "2.", "3.")]
    assert headings == ["1. 계약서에서 고칠 곳", "2. 넣어 주실 특약", "3. 계약 전에 받아야 할 서류"]


def test_amendment_and_comparison_never_show_id_numbers_or_banned_phrases():
    req = worst_request()
    for e in req.registry.gapgu + req.registry.eulgu:
        e.holders = [f"{h} 850315-1234567" for h in e.holders]
    req.contract.landlord_names = ["이민준 900101-1xxxxxx"]
    req.contract.address = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 303호 (임대인 900101-1234567)"
    report = build_report(req)
    texts = [report.amendment.text, *report.amendment.terms, *report.amendment.documents]
    for f in report.amendment.fixes:
        texts += [f.item, f.current or "", f.proposed, f.reason]
    for row in report.comparison:
        texts += [row.item, row.contract or "", row.registry or "", row.note]
    assert [t for t in texts if ID_SHAPE.search(t)] == []
    for text in texts:
        for phrase in content.BANNED_PHRASES:
            assert phrase not in text


@pytest.mark.parametrize("word, iga", [("1,000만 원", "이"), ("5,678원", "이"), ("사과", "가"), ("서울", "이"), ("이○○", "이")])
def test_josa_iga(word, iga):
    assert josa_iga(word) == iga


@pytest.mark.parametrize(
    "deposit, level, percent",
    [(10_000_000, "green", "5%"), (140_000_000, "yellow", "70%"), (180_000_000, "red", "90%")],
)
def test_r5_without_senior_claims_drops_the_zero_term(deposit, level, percent):
    req = base_request()
    req.contract.deposit = deposit
    req.manual.prior_deposits = 0  # 직접 입력한 0도 선순위가 없는 것과 같다
    r = rule(req, "R5")
    assert r.level == level
    money = fmt_money(deposit)
    assert r.summary.startswith(f"내 보증금 {money}이 시세(2억 원, 같은 건물 실거래가)의 {percent}예요.")
    assert "선순위" not in r.summary


def test_r5_with_senior_claims_keeps_the_sum_form():
    req = base_request()
    req.manual.prior_deposits = 20_000_000
    assert rule(req, "R5").summary == (
        "선순위 2,000만 원 + 내 보증금 1,000만 원 = 시세(2억 원, 같은 건물 실거래가)의 15%예요."
    )


def test_comparison_without_contract_or_typed_values_leaves_contract_cells_empty():
    req = base_request()
    req.contract = None
    report = build_report(req)
    check_crosscheck(report)
    assert [row.contract for row in report.comparison] == [None, None, None, None, None]
    req.manual.landlord_name = "김○○"
    req.manual.deposit = 10_000_000
    req.manual.contract_date = dt.date(2026, 11, 20)
    contracts = [row.contract for row in build_report(req).comparison]
    assert contracts == ["김○○ (직접 입력)", None, "1,000만 원 (직접 입력)", "2026년 11월 20일 (직접 입력)", None]


def test_comparison_contract_without_value_says_not_in_contract():
    req = base_request()
    req.contract.landlord_names = []
    req.contract.deposit = None
    req.contract.contract_date = None
    req.contract.address = None
    req.contract.unit = ContractUnit()
    contracts = {row.item: row.contract for row in build_report(req).comparison}
    assert contracts == {
        "임대인": "계약서에 없음",
        "소재지·호수": "계약서에 없음",
        "보증금": "계약서에 없음",
        "계약일": "계약서에 없음",
        "특약": "보호 특약 있음",
    }
