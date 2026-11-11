"""계약 후 재확인 (잔금 전·잔금 당일·입주 후) 테스트."""

from __future__ import annotations

import datetime as dt
import json
import random
import re
from pathlib import Path

import pytest

from app.rules import build_recheck, recheck
from app.rules.content import BANNED_PHRASES
from app.schemas import CheckRequest, ContractExtract, Entry, RecheckReport, RecheckRequest

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"
ID_SHAPE = re.compile(r"\d{6}\s*-\s*[\d*]{7}")
KST = dt.timezone(dt.timedelta(hours=9))
PROHIBITION = "임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다. 위반 시 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다."
REMOVAL = "임대인은 잔금일까지 등기부상 근저당권을 말소한다."


def fixture() -> RecheckRequest:
    return RecheckRequest.model_validate_json((DEMO_DIR / "recheck-A.json").read_bytes())


def original_a(today=dt.date(2026, 11, 29)) -> RecheckRequest:
    """예시 A의 등기부 내용과 계약서로 다시 확인하는 요청. 등기부는 오늘 다시 뗀 것으로 둔다."""
    a = CheckRequest.model_validate_json((DEMO_DIR / "A.json").read_bytes())
    a.registry.viewed_at = dt.datetime(today.year, today.month, today.day, 10, 0, tzinfo=KST)
    return RecheckRequest(registry=a.registry, contract=a.contract, today=today, mode="demo")


def a_as_uploaded(today=dt.date(2026, 11, 29)) -> RecheckRequest:
    """예시 A의 원래 등기부(계약일 2026-11-14 아침에 뗀 것)를 그대로 다시 올린 요청."""
    a = CheckRequest.model_validate_json((DEMO_DIR / "A.json").read_bytes())
    return RecheckRequest(registry=a.registry, contract=a.contract, today=today, mode="demo")


def entry(rank, purpose, received_at, holders=("○○은행",), amount=None, cancelled=False, cause=None):
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


def mortgage(received_at, rank="1", amount=120_000_000, cancelled=False):
    return entry(rank, "근저당권설정", received_at, amount=amount, cancelled=cancelled)


def texts(report: RecheckReport) -> list[str]:
    out = [report.overall.title, report.overall.message, report.overall.unknown_note or "", report.address or ""]
    out += report.actions + [report.disclaimer]
    for c in report.changes:
        out += [c.purpose, c.note, c.source_text, *c.holders]
    for t in report.term_checks:
        out += [t.term, t.note]
    return out


# ---------------------------------------------------------------------------
# 발표용 예시 (recheck-A.json)
# ---------------------------------------------------------------------------


def test_fixture_is_a_valid_demo_request():
    raw = json.loads((DEMO_DIR / "recheck-A.json").read_text(encoding="utf-8"))
    assert (raw["mode"], raw["today"]) == ("demo", "2026-11-29")
    req = RecheckRequest.model_validate(raw)
    a = CheckRequest.model_validate_json((DEMO_DIR / "A.json").read_bytes())
    assert req.contract == a.contract
    assert req.registry.gapgu == a.registry.gapgu
    assert req.registry.viewed_at == dt.datetime(2026, 11, 29, 10, 12, tzinfo=dt.timezone(dt.timedelta(hours=9)))
    (new,) = req.registry.eulgu
    assert (new.rank, new.purpose, new.received_at, new.amount, new.holders) == (
        "1",
        "근저당권설정",
        dt.date(2026, 11, 27),
        120_000_000,
        ["○○은행"],
    )
    assert "채권최고액 금120,000,000원" in new.source_text and "근저당권자" in new.source_text


def test_fixture_result():
    report = build_recheck(fixture())
    assert (report.phase, report.baseline_date, report.balance_date, report.move_in_date) == (
        "before_balance",
        dt.date(2026, 11, 14),
        dt.date(2026, 12, 1),
        dt.date(2026, 12, 1),
    )
    assert report.address == "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호"
    assert (report.overall.level, report.overall.title) == ("red", "잔금 보류 권장")
    assert report.overall.message == (
        "계약 후 새로 생긴 권리 1건, 지켜지지 않은 특약 1건이 있어요. 해결되기 전에는 잔금을 미루는 걸 권해요."
    )
    assert [(c.section, c.rank, c.level, c.note, c.amount) for c in report.changes] == [
        ("eulgu", "1", "red", "계약 후 새로 생김", 120_000_000)
    ]
    assert [(t.term, t.status, t.level) for t in report.term_checks] == [(PROHIBITION, "위반", "red")]
    assert report.term_checks[0].note == "계약 후 2026년 11월 27일에 근저당권(채권최고액 1억 2,000만 원)이 새로 설정됐어요."
    assert report.actions == [
        "잔금을 보내기 전에 임대인에게 말소를 요구하고, 해결되기 전에는 잔금을 미루세요.",
        "계약서 특약(담보 설정 금지)에 어긋나요. 공인중개사·대한법률구조공단(국번 없이 132)과 상의해 대응하세요.",
    ]


def test_fresh_registry_of_a_has_nothing_new():
    report = build_recheck(original_a())
    assert (report.overall.level, report.overall.title) == ("green", "새로 생긴 권리 없음")
    assert report.overall.unknown_note is None
    assert report.changes == []
    assert [(t.status, t.level) for t in report.term_checks] == [("이행", "green")]
    assert report.actions == ["잔금 보내기 직전에 한 번 더 떼어 보고, 입주 당일 전입신고와 확정일자를 받으세요."]


def test_original_registry_of_a_cannot_show_changes_after_the_contract():
    """계약일 아침에 뗀 등기부로는 계약 후 변화를 볼 수 없다 → "없음"이 아니라 "확인 미완료"."""
    report = build_recheck(a_as_uploaded())
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert report.overall.message == (
        "올린 등기부는 2026년 11월 14일에 뗀 것이라 계약일(2026년 11월 14일) 뒤의 변화가 나오지 않아요. "
        "잔금을 보내기 전에 오늘 날짜로 등기부를 다시 떼어 올려 확인하세요."
    )
    assert report.overall.unknown_note == "확인하지 못한 항목 2개"  # 등기부 1 + 특약 1
    assert report.changes == []
    assert [(t.status, t.level, t.note) for t in report.term_checks] == [
        ("확인 필요", "unknown", "올린 등기부로는 계약 후 변화를 확인할 수 없어 이행 여부를 판단하지 못했어요.")
    ]
    assert report.actions == ["잔금을 보내기 전에 오늘 날짜로 등기부를 다시 떼어 올려 확인하세요."]


@pytest.mark.parametrize(
    "viewed, title",
    [
        (None, "확인 미완료"),  # 열람 일시를 모른다
        (dt.datetime(2026, 11, 13, 18, 0, tzinfo=KST), "확인 미완료"),  # 계약 전날
        (dt.datetime(2026, 11, 14, 23, 0, tzinfo=KST), "확인 미완료"),  # 계약 당일
        (dt.datetime(2026, 11, 14, 15, 30, tzinfo=dt.timezone.utc), "새로 생긴 권리 없음"),  # 한국 시각 11-15 00:30
        (dt.datetime(2026, 11, 15, 9, 0, tzinfo=KST), "새로 생긴 권리 없음"),
    ],
)
def test_registry_must_be_viewed_after_the_contract_day(viewed, title):
    req = original_a()
    req.registry.viewed_at = viewed
    report = build_recheck(req)
    assert report.overall.title == title
    if title == "확인 미완료":
        assert report.overall.level == "yellow"
        assert "등기부를 다시 떼어 올려" in report.overall.message


def test_stale_registry_still_shows_red_findings():
    req = fixture()
    req.registry.viewed_at = dt.datetime(2026, 11, 14, 9, 0, tzinfo=KST)  # 앞뒤가 안 맞아도 적힌 권리는 그대로 알린다
    report = build_recheck(req)
    assert (report.overall.level, report.overall.title) == ("red", "잔금 보류 권장")
    assert "잔금을 보내기 전에 오늘 날짜로 등기부를 다시 떼어 올려 확인하세요." in report.actions


# ---------------------------------------------------------------------------
# 기준일·단계
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "today, phase, title",
    [
        (dt.date(2026, 11, 29), "before_balance", "잔금 보류 권장"),
        (dt.date(2026, 12, 1), "balance_day", "잔금 보류 권장"),
        (dt.date(2026, 12, 2), "after_move_in", "보증금 보호 확인 필요"),
    ],
)
def test_phases(today, phase, title):
    req = fixture()
    req.today = today
    report = build_recheck(req)
    assert (report.phase, report.overall.title) == (phase, title)
    if phase == "after_move_in":
        assert "전입신고·확정일자를 받았는지 확인하고, 대한법률구조공단이나 전세피해지원센터에 상담하세요." in report.actions
        assert not any(a.startswith("잔금을 보내기 전에") for a in report.actions)


def test_phase_date_fallbacks():
    assert recheck.phase_of(dt.date(2026, 12, 5), None) == "before_balance"  # 잔금일을 모르면 가장 조심스럽게
    req = original_a(today=dt.date(2026, 12, 1))
    req.contract.balance_date = None  # 잔금일이 없으면 입주일을 쓴다
    report = build_recheck(req)
    assert (report.phase, report.balance_date, report.move_in_date) == ("balance_day", None, dt.date(2026, 12, 1))
    req.contract.move_in_date = None
    req.contract.balance_date = dt.date(2026, 12, 1)  # 입주일이 없으면 잔금일을 입주일로 본다
    assert build_recheck(req).move_in_date == dt.date(2026, 12, 1)


@pytest.mark.parametrize(
    "viewed, baseline",
    [
        (None, dt.date(2026, 11, 14)),
        (dt.datetime(2026, 11, 12, 9, 0), dt.date(2026, 11, 12)),  # 계약 때 본 등기부가 더 이르면 그날
        (dt.datetime(2026, 11, 16, 9, 0), dt.date(2026, 11, 14)),
        (dt.datetime(2026, 11, 12, 16, 0, tzinfo=dt.timezone.utc), dt.date(2026, 11, 13)),  # 한국 날짜로 바꾼다
    ],
)
def test_baseline_date(viewed, baseline):
    req = original_a()
    req.baseline_viewed_at = viewed
    assert build_recheck(req).baseline_date == baseline


def test_without_contract_date_nothing_is_called_new():
    req = fixture()
    req.contract.contract_date = None
    report = build_recheck(req)
    assert report.baseline_date is None
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")
    assert report.overall.message.startswith("계약일을 확인하지 못해 계약 후 새로 생긴 권리를 가려내지 못했어요.")
    assert report.changes == [] and report.term_checks == []
    assert report.actions == ["계약서의 계약일을 확인한 뒤 다시 확인하세요."]


# ---------------------------------------------------------------------------
# 새로 생긴 권리
# ---------------------------------------------------------------------------


def test_same_day_entry_is_yellow():
    req = original_a()
    req.registry.eulgu = [mortgage(dt.date(2026, 11, 14))]
    report = build_recheck(req)
    assert [(c.level, c.note) for c in report.changes] == [("yellow", "계약 당일 접수: 계약 때 본 등기부에 있었는지 확인하세요")]
    assert [(t.status, t.level) for t in report.term_checks] == [("확인 필요", "unknown")]
    assert (report.overall.level, report.overall.title) == ("yellow", "추가 확인 필요")
    assert report.overall.message == "계약 전후로 확인할 것이 1건 있어요."
    assert report.overall.unknown_note == "확인하지 못한 항목 1개"
    assert report.actions[0].startswith("잔금을 보내기 전에")


def test_unknown_received_date_is_unknown():
    req = original_a()
    req.registry.eulgu = [mortgage(None)]
    report = build_recheck(req)
    assert [(c.level, c.note) for c in report.changes] == [("unknown", "접수일을 읽지 못해 계약 후에 생긴 것인지 알 수 없어요")]
    assert report.overall.unknown_note == "확인하지 못한 항목 2개"  # 새 권리 1 + 특약 1
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")  # "없음"이라고 하지 않는다
    assert report.overall.message == (
        "새로 생긴 권리는 찾지 못했지만, 접수일을 읽지 못한 항목 1건을 확인하지 못했어요. 등기부 원문에서 날짜를 확인하세요."
    )
    assert "접수일을 읽지 못한 항목은 등기부 원문에서 날짜를 직접 확인하세요." in report.actions


def test_after_move_in_entry_on_move_in_day_is_red():
    req = original_a(today=dt.date(2026, 12, 5))
    req.registry.gapgu.append(entry("3", "가압류", dt.date(2026, 12, 1), holders=["○○캐피탈"]))
    report = build_recheck(req)
    assert report.phase == "after_move_in"
    assert [(c.section, c.level, c.note) for c in report.changes] == [
        ("gapgu", "red", "전입신고와 같은 날 등기돼 세입자보다 앞서요")
    ]
    assert report.overall.title == "보증금 보호 확인 필요"
    assert report.actions == ["전입신고·확정일자를 받았는지 확인하고, 대한법률구조공단이나 전세피해지원센터에 상담하세요."]


def test_after_move_in_without_changes():
    report = build_recheck(original_a(today=dt.date(2026, 12, 5)))
    assert report.overall.title == "새로 생긴 권리 없음"
    assert report.actions == ["전입신고 다음 날에도 한 번 더 확인하세요."]


def test_owner_change_after_contract_is_red():
    req = original_a()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 11, 20), holders=["박○○ 780412-1234567"], cause="매매"))
    report = build_recheck(req)
    assert [(c.level, c.note, c.holders) for c in report.changes] == [("red", "계약 후 집주인이 바뀌었어요", ["박○○"])]
    assert report.overall.title == "잔금 보류 권장"
    same_owner = original_a()
    same_owner.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 11, 20), holders=["김○○"], cause="매매"))
    assert [c.note for c in build_recheck(same_owner).changes] == ["계약 후 새로 생김"]


def test_owner_change_on_contract_day_is_red_too():
    req = original_a()
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 11, 14), holders=["박○○"], cause="매매"))
    assert [(c.level, c.note) for c in build_recheck(req).changes] == [("red", "계약 후 집주인이 바뀌었어요")]


def test_registry_parsing_reuses_row_rules():
    req = original_a()
    req.registry.gapgu += [
        entry("3", "가압류", dt.date(2026, 11, 20), cancelled=True),  # 말소 표시 → 판단에서 뺀다
        entry("4", "2번가압류등기말소", dt.date(2026, 11, 21), holders=[]),  # 말소 기록 행
        entry("5", "소유권이전", dt.date(2026, 11, 22), holders=["김○○"]),
        entry("5", "신탁", dt.date(2026, 11, 22), holders=[]),  # 같은 순위번호를 나눠 적은 줄
    ]
    req.registry.eulgu = [
        mortgage(dt.date(2024, 1, 2), amount=100_000_000),
        entry("1-1", "1번근저당권변경", dt.date(2026, 11, 25), holders=[], amount=150_000_000),  # 부기: 새 변경은 보여 준다
    ]
    notes = [(c.section, c.rank, c.level, c.note) for c in build_recheck(req).changes]
    assert notes == [
        ("gapgu", "5", "red", "계약 후 새로 생김"),
        ("eulgu", "1-1", "red", "기존 근저당의 채권최고액이 늘었어요"),
    ]


# ---------------------------------------------------------------------------
# 특약 점검
# ---------------------------------------------------------------------------


def removal_request(today):
    req = original_a(today=today)
    req.contract.special_terms = [REMOVAL]
    req.registry.eulgu = [mortgage(dt.date(2024, 1, 2), amount=100_000_000)]
    return req


@pytest.mark.parametrize(
    "today, level, note",
    [
        (dt.date(2026, 11, 29), "yellow", "잔금일까지 말소해야 해요. 계약 전부터 있던 근저당권(채권최고액 1억 원)이 아직 남아 있어요."),
        (dt.date(2026, 12, 1), "red", "잔금일인데 계약 전부터 있던 근저당권(채권최고액 1억 원)이 아직 말소되지 않았어요."),
        (dt.date(2026, 12, 3), "red", "잔금일이 지났는데 계약 전부터 있던 근저당권(채권최고액 1억 원)이 아직 말소되지 않았어요."),
    ],
)
def test_removal_promise_not_kept(today, level, note):
    report = build_recheck(removal_request(today))
    assert [(t.status, t.level, t.note) for t in report.term_checks] == [("미이행", level, note)]
    assert report.changes == []  # 계약 전부터 있던 근저당은 새 권리가 아니다


def test_removal_promise_kept_and_unclear():
    req = removal_request(dt.date(2026, 12, 1))
    req.registry.eulgu[0].is_cancelled = True
    assert [(t.status, t.level) for t in build_recheck(req).term_checks] == [("이행", "green")]
    req.registry.eulgu = [mortgage(None)]
    assert [(t.status, t.level) for t in build_recheck(req).term_checks] == [("확인 필요", "unknown")]


def test_term_with_both_promises_reports_the_worse_one():
    req = removal_request(dt.date(2026, 11, 29))
    req.contract.special_terms = ["임대인은 잔금일까지 근저당권을 말소하고, 잔금일 다음 날까지 담보권을 설정하지 않는다."]
    req.registry.eulgu.append(mortgage(dt.date(2026, 11, 27), rank="2", amount=50_000_000))
    (check,) = build_recheck(req).term_checks
    assert (check.status, check.level) == ("위반", "red")
    assert "새로 설정됐어요" in check.note and "잔금일까지 말소해야 해요" in check.note


def test_only_protective_terms_are_checked():
    req = original_a()
    req.contract.special_terms = ["반려동물은 키우지 않는다.", PROHIBITION]
    assert [t.term for t in build_recheck(req).term_checks] == [PROHIBITION]


# ---------------------------------------------------------------------------
# 화면 문구·결정성·견고성
# ---------------------------------------------------------------------------


def test_no_id_numbers_or_banned_phrases():
    req = fixture()
    req.contract.special_terms = [PROHIBITION + " (임대인 850315-1234567)"]
    req.contract.address = req.contract.address + " 900101-1xxxxxx"
    req.registry.eulgu[0].holders = ["○○은행 110111-1234567"]
    req.registry.gapgu.append(entry("3", "소유권이전", dt.date(2026, 11, 20), holders=["박○○ 780412-1234567"]))
    report = build_recheck(req)
    for text in texts(report):
        assert not ID_SHAPE.search(text), text
        for phrase in BANNED_PHRASES:
            assert phrase not in text
    assert "******-*******" in report.changes[0].source_text or "******-*******" in report.changes[1].source_text


def test_deterministic_and_round_trip():
    first = build_recheck(fixture())
    second = build_recheck(fixture())
    assert first.model_dump(exclude={"generated_at"}) == second.model_dump(exclude={"generated_at"})
    assert RecheckReport.model_validate_json(first.model_dump_json()) == first
    assert first.generated_at.utcoffset() == dt.timedelta(hours=9)


def test_today_defaults_to_korean_date():
    req = fixture()
    req.today = None
    from app.rules.common import today_kst

    assert build_recheck(req).today == today_kst()


def test_messy_inputs_never_raise_or_hit_the_failure_fallback():
    rng = random.Random(20261129)
    purposes = ["소유권이전", "소유권이전, 신탁", "신탁", "가압류", "근저당권설정", "1번근저당권변경", "전세권설정",
                "3번가압류등기말소", "", "주택임차권", "소유권일부이전"]
    terms = [PROHIBITION, REMOVAL, "반려동물 금지", "", "근저당 말소하고 담보 설정하지 않는다"]

    def any_date():
        return rng.choice([None, dt.date(2026, 11, 14) + dt.timedelta(days=rng.randint(-400, 40))])

    def any_entry(i):
        return Entry(rank=rng.choice([str(i), f"{i}-1", "", "1"]), purpose=rng.choice(purposes), received_at=any_date(),
                     holders=rng.sample(["김○○", "박○○", "", "○○은행 110111-1234567"], rng.randint(0, 2)),
                     amount=rng.choice([None, 50_000_000]), is_cancelled=rng.random() < 0.2,
                     source_text=rng.choice(["", "원문 850315-1234567"]))

    base = original_a()
    for _ in range(300):
        req = RecheckRequest(
            registry=base.registry.model_copy(update={
                "gapgu": [any_entry(i) for i in range(rng.randint(0, 4))],
                "eulgu": [any_entry(i) for i in range(rng.randint(0, 3))],
            }),
            contract=ContractExtract(
                landlord_names=rng.sample(["김○○", "박○○"], rng.randint(0, 1)),
                contract_date=rng.choice([None, dt.date(2026, 11, 14)]),
                balance_date=rng.choice([None, dt.date(2026, 12, 1)]),
                move_in_date=rng.choice([None, dt.date(2026, 12, 1), dt.date(2026, 12, 3)]),
                special_terms=rng.sample(terms, rng.randint(0, 2)),
            ),
            baseline_viewed_at=rng.choice([None, dt.datetime(2026, 11, 10, 9, 0)]),
            today=dt.date(2026, 11, 14) + dt.timedelta(days=rng.randint(-5, 30)),
        )
        report = build_recheck(req)
        RecheckReport.model_validate_json(report.model_dump_json())
        assert all(c.note != recheck.NOTE_FAILED for c in report.changes)
        assert all(t.note != recheck.NOTE_FAILED for t in report.term_checks)
        assert report.actions
        for text in texts(report):
            assert not ID_SHAPE.search(text), text


def test_red_still_wins_over_unread_dates():
    req = fixture()
    req.registry.gapgu.append(entry("3", "가압류", None, holders=["○○캐피탈"]))
    report = build_recheck(req)
    assert report.overall.title == "잔금 보류 권장"
    assert report.overall.unknown_note == "확인하지 못한 항목 1개"


def test_unknown_term_check_alone_is_incomplete(monkeypatch):
    def boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(recheck, "_check_prohibition", boom)
    report = build_recheck(original_a())
    assert [(t.status, t.level) for t in report.term_checks] == [("확인 필요", "unknown")]
    assert (report.overall.level, report.overall.title) == ("yellow", "확인 미완료")


BROKEN = "계약서 특약({kind})에 어긋나요. 공인중개사·대한법률구조공단(국번 없이 132)과 상의해 대응하세요."


def test_fixture_texts_do_not_repeat_purpose_or_clause():
    report = build_recheck(fixture())
    assert all(c.purpose not in c.note for c in report.changes)
    assert all(t.term not in action for t in report.term_checks for action in report.actions)


@pytest.mark.parametrize(
    "today, expected",
    [
        (dt.date(2026, 11, 29), []),  # 잔금 전 미이행은 아직 어긴 것이 아니다 (말소 요구만 안내)
        (dt.date(2026, 12, 1), [BROKEN.format(kind="근저당 말소")]),
        (dt.date(2026, 12, 3), [BROKEN.format(kind="근저당 말소")]),
    ],
)
def test_removal_breach_action_names_the_kind(today, expected):
    actions = build_recheck(removal_request(today)).actions
    assert [a for a in actions if a.startswith("계약서 특약(")] == expected


def test_both_kinds_listed_when_one_clause_breaks_both():
    req = removal_request(dt.date(2026, 12, 1))
    req.contract.special_terms = ["임대인은 잔금일까지 근저당권을 말소하고, 잔금일 다음 날까지 담보권을 설정하지 않는다."]
    req.registry.eulgu.append(mortgage(dt.date(2026, 11, 27), rank="2", amount=50_000_000))
    actions = build_recheck(req).actions
    assert [a for a in actions if a.startswith("계약서 특약(")] == [BROKEN.format(kind="담보 설정 금지, 근저당 말소")]


def test_same_breach_action_is_not_repeated():
    req = fixture()
    req.contract.special_terms = [PROHIBITION, "임대인은 계약 기간 중 이 집에 근저당을 설정하지 않는다."]
    report = build_recheck(req)
    assert [t.status for t in report.term_checks] == ["위반", "위반"]
    assert [a for a in report.actions if a.startswith("계약서 특약(")] == [BROKEN.format(kind="담보 설정 금지")]
