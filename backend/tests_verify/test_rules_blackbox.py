"""Per-rule black-box tests (PRD 7.1, 7.2, 7.4). Written from PRD.md only."""

from __future__ import annotations

import re

import pytest

from verify_helpers import (
    R1_RED_ACTION,
    R1_RED_TITLE,
    R1_Y_ACTION,
    R1_Y_SUMMARY,
    R1_Y_TITLE,
    R2_ACTION,
    R2_SUMMARY,
    R2_TITLE,
    R3_ACTION,
    R3_SUMMARY_TAIL,
    R3_TITLE,
    R4_RED_ACTION,
    R4_RED_SUMMARY,
    R4_RED_TITLE,
    R4_Y_ACTION,
    R4_Y_SUMMARY,
    R4_Y_TITLE,
    R5_ACTION,
    R5_DAGAGU_REASON,
    R5_SUMMARY_TAIL,
    R5_TITLE,
    R6_ACTION,
    R6_SUMMARY,
    R6_TITLE,
    R7_ACTION,
    R7_SUMMARY,
    R7_TITLE,
    R8_ACTION,
    R8_SUMMARY_TAIL,
    R8_TITLE,
    R9_ACTION,
    R9_SUMMARY,
    R9_TITLE,
    R10_ACTION,
    R10_SUMMARY_TAIL,
    R10_TITLE,
    R11_RED_ACTION,
    R11_RED_TAIL,
    R11_RED_TITLE,
    R11_Y_ACTION,
    R11_Y_SUMMARY,
    R11_Y_TITLE,
    R12_ACTION,
    R12_SUMMARY,
    R12_TITLE,
    R13_ACTION,
    R13_SUMMARY,
    R13_TITLE,
    E,
    demo,
    dre,
    lv,
    res,
    run,
    won,
)

G, Y, R, U = "green", "yellow", "red", "unknown"


def bojon(owner="김철수", date="2010-01-05"):
    return E("1", "소유권보존", date, None, [owner], page=1)


def owner_req(rows, landlords=("김철수",), manual_landlord=None, contract=True):
    d = demo("A")
    d["registry"]["gapgu"] = rows
    d["manual"]["landlord_name"] = manual_landlord
    if contract:
        d["contract"]["landlord_names"] = list(landlords)
    else:
        d["contract"] = None
    return d


# =============================================================================
# R1
# =============================================================================
class TestR1:
    def test_red_texts_josa_vowel(self):
        r = res(run(owner_req([bojon("박영희")], ["김철수"])), "R1")
        assert r.level == R
        assert r.title == R1_RED_TITLE
        assert r.summary == "등기부상 소유자는 박영희인데, 계약서의 임대인은 김철수예요."
        assert r.action == R1_RED_ACTION

    def test_red_josa_consonant(self):
        r = res(run(owner_req([bojon("박영희")], ["이민준"])), "R1")
        assert r.summary == "등기부상 소유자는 박영희인데, 계약서의 임대인은 이민준이에요."

    def test_red_scenario_c_exact(self):
        """4.3 wireframe / 7.4: 앞 글자가 한글·숫자가 아니면(이○○) 7.2 조사를 그대로."""
        r = res(run(demo("C")), "R1")
        assert r.summary == "등기부상 소유자는 ○○부동산신탁(주)인데, 계약서의 임대인은 이○○이에요."

    def test_red_evidence(self):
        # v0.3: evidence quotes mask 주민등록번호 형태 as "******-*******", rest verbatim (PRD.md line 464)
        from verify_helpers import mask_rrn

        d = demo("C")
        r = res(run(d), "R1")
        reg = [e for e in r.evidence if e.doc == "registry"]
        con = [e for e in r.evidence if e.doc == "contract"]
        assert any(e.text == mask_rrn(d["registry"]["gapgu"][2]["source_text"]) and e.page == 2 for e in reg), r.evidence
        assert any(mask_rrn(d["contract"]["sources"]["landlord"]) in e.text for e in con), r.evidence

    def test_unknown_no_landlord(self):
        r = res(run(owner_req([bojon()], [])), "R1")
        assert r.level == U and r.unknown_reason

    def test_unknown_no_ownership_entry(self):
        rows = [E("1", "가압류", "2026-10-01", "가압류결정", ["국민은행"])]
        r = res(run(owner_req(rows)), "R1")
        assert r.level == U and r.unknown_reason

    def test_manual_landlord_when_no_contract(self):
        assert lv(owner_req([bojon("김철수")], contract=False, manual_landlord="김철수"), "R1") == G
        assert lv(owner_req([bojon("김철수")], contract=False, manual_landlord="박민수"), "R1") == R

    def test_manual_landlord_when_contract_has_no_names(self):
        assert lv(owner_req([bojon("김철수")], [], manual_landlord="김철수"), "R1") == G
        assert lv(owner_req([bojon("김철수")], [], manual_landlord="박민수"), "R1") == R

    def test_contract_landlord_preferred_over_manual(self):
        """Ambiguous PRD: 7.1 기준일 order is 계약서 → 직접 입력; assumed same for 임대인."""
        assert lv(owner_req([bojon("김철수")], ["김철수"], manual_landlord="박민수"), "R1") == G

    @pytest.mark.parametrize(
        "owner,landlord",
        [
            ("김철수", "김 철수"),
            ("○○부동산신탁(주)", "○○부동산신탁주식회사"),
            ("㈜한빛", "주식회사 한빛"),
            ("（주）한빛", "한빛"),
            ("(유)한빛", "유한회사 한빛"),
            ("（유）한빛", "한빛"),
            ("소유자 김철수", "김철수"),
            ("김철수", "임대인 김철수"),
            ("수탁자 한빛신탁", "한빛신탁"),
            ("김철수 850315-*******", "김철수"),
            ("김철수 850315-1******", "김철수"),
            ("김철수", "김철수 850315-1234567"),
        ],
    )
    def test_name_normalization_equal(self, owner, landlord):
        assert lv(owner_req([bojon(owner)], [landlord]), "R1") == G

    @pytest.mark.parametrize("owner,landlord", [("김철수", "김철"), ("한빛", "한빛건설"), ("김철수", "박철수")])
    def test_name_normalization_not_equal(self, owner, landlord):
        assert lv(owner_req([bojon(owner)], [landlord]), "R1") == R

    def test_coowned_two_holders(self):
        rows = [E("1", "소유권보존", "2010-01-05", None, ["김철수", "이영희"])]
        r = res(run(owner_req(rows, ["김철수"])), "R1")
        assert r.level == Y
        assert r.title == R1_Y_TITLE
        assert r.summary == R1_Y_SUMMARY.format(n=2)
        assert r.action == R1_Y_ACTION
        assert r.evidence

    @pytest.mark.parametrize("landlord", ["김철수", "이영희"])
    def test_coowned_partial_transfer(self, landlord):
        rows = [bojon("김철수"), E("2", "소유권일부이전", "2012-03-01", "2012년2월1일 매매", ["이영희"])]
        r = res(run(owner_req(rows, [landlord])), "R1")
        assert r.level == Y
        assert r.summary == R1_Y_SUMMARY.format(n=2)

    @pytest.mark.parametrize("landlord,level", [("이영희", R), ("박민수", Y), ("김철수", Y)])
    def test_share_full_transfer_removes_seller(self, landlord, level):
        rows = [
            bojon("김철수"),
            E("2", "소유권일부이전", "2012-03-01", "2012년2월1일 매매", ["이영희"]),
            E("3", "2번이영희지분전부이전", "2014-05-01", "2014년4월1일 매매", ["박민수"]),
        ]
        r = res(run(owner_req(rows, [landlord])), "R1")
        assert r.level == level
        if level == Y:
            assert r.summary == R1_Y_SUMMARY.format(n=2)

    def test_share_partial_transfer_adds_buyer(self):
        rows = [
            E("1", "소유권보존", "2010-01-05", None, ["김철수", "이영희"]),
            E("2", "1번이영희지분일부이전", "2014-05-01", "2014년4월1일 매매", ["박민수"]),
        ]
        r = res(run(owner_req(rows, ["박민수"])), "R1")
        assert r.level == Y
        assert r.summary == R1_Y_SUMMARY.format(n=3)

    @pytest.mark.parametrize("landlord,level", [("박민수", G), ("김철수", R)])
    def test_all_coowners_transfer_replaces(self, landlord, level):
        rows = [
            bojon("김철수"),
            E("2", "소유권일부이전", "2012-03-01", "2012년2월1일 매매", ["이영희"]),
            E("3", "공유자전원지분전부이전", "2014-05-01", "2014년4월1일 매매", ["박민수"]),
        ]
        assert lv(owner_req(rows, [landlord]), "R1") == level

    def test_trust_only_purpose_is_ownership_transfer(self):
        rows = [bojon("김철수"), E("2", "신탁", "2020-01-01", None, ["한빛신탁"])]
        assert lv(owner_req(rows, ["김철수"]), "R1") == R
        assert lv(owner_req(rows, ["한빛신탁"]), "R1") == G

    @pytest.mark.parametrize("purpose", ["소유권이전청구권가등기", "소유권이전담보가등기"])
    def test_provisional_registration_not_owner(self, purpose):
        rows = [bojon("김철수"), E("2", purpose, "2020-01-01", "2019년12월1일 매매예약", ["박민수"])]
        assert lv(owner_req(rows, ["김철수"]), "R1") == G
        assert lv(owner_req(rows, ["박민수"]), "R1") == R

    def test_cancelled_transfer_ignored(self):
        rows = [bojon("김철수"), E("2", "소유권이전", "2020-01-01", "매매", ["박민수"], cancelled=True)]
        assert lv(owner_req(rows, ["김철수"]), "R1") == G

    def test_cancellation_record_row_ignored(self):
        rows = [
            bojon("김철수"),
            E("2", "소유권이전", "2026-10-01", "2026년9월1일 매매", ["박민수"], cancelled=True),
            E("3", "2번소유권이전등기말소", "2026-11-01", "2026년10월30일 해제", []),
        ]
        rep = run(owner_req(rows, ["김철수"]))
        assert lv(rep, "R1") == G
        assert lv(rep, "R8") == G  # current ownership row is the 2010 보존

    def test_multiple_landlords_one_not_owner_is_red(self):
        rows = [E("1", "소유권보존", "2010-01-05", None, ["김철수", "이영희"])]
        assert lv(owner_req(rows, ["김철수", "박민수"]), "R1") == R

    def test_multiple_landlords_all_owners_is_yellow(self):
        rows = [E("1", "소유권보존", "2010-01-05", None, ["김철수", "이영희"])]
        r = res(run(owner_req(rows, ["김철수", "이영희"])), "R1")
        assert r.level == Y and r.summary == R1_Y_SUMMARY.format(n=2)

    def test_red_lists_all_owners(self):
        rows = [E("1", "소유권보존", "2010-01-05", None, ["김철수", "이영희"])]
        r = res(run(owner_req(rows, ["박민수"])), "R1")
        assert r.level == R
        assert "김철수" in r.summary and "이영희" in r.summary and "박민수" in r.summary


# =============================================================================
# R2
# =============================================================================
class TestR2:
    def test_red_cause_trust_texts_and_evidence(self):
        src = "2 소유권이전 2020년1월1일 제1호 2020년1월1일 신탁 수탁자 한빛신탁주식회사"
        rows = [bojon(), E("2", "소유권이전", "2020-01-01", "신탁", ["한빛신탁(주)"], page=3, src=src)]
        r = res(run(owner_req(rows, ["김철수"])), "R2")
        assert r.level == R
        assert r.title == R2_TITLE
        assert r.summary == R2_SUMMARY.format(t="한빛신탁(주)")
        assert r.action == R2_ACTION
        assert any(e.doc == "registry" and e.text == src and e.page == 3 for e in r.evidence), r.evidence

    def test_red_scenario_c_exact(self):
        r = res(run(demo("C")), "R2")
        assert r.summary == R2_SUMMARY.format(t="○○부동산신탁(주)")

    def test_red_purpose_trust_only(self):
        rows = [bojon(), E("2", "신탁", "2020-01-01", None, ["한빛신탁"])]
        assert lv(owner_req(rows, ["한빛신탁"]), "R2") == R

    @pytest.mark.parametrize(
        "cause", ["신탁재산의귀속", "2020년1월1일 신탁재산의귀속", "신탁계약해지", "2020년1월1일 신탁해지", "신탁종료"]
    )
    def test_trust_ending_cause_alone_is_not_trust(self, cause):
        rows = [bojon(), E("2", "소유권이전", "2020-01-01", cause, ["김철수"])]
        assert lv(owner_req(rows, ["김철수"]), "R2") == G

    def test_purpose_with_cancelled_trust_piece_is_not_trust(self):
        rows = [
            bojon("박민수"),
            E("2", "소유권이전", "2015-01-01", "신탁", ["한빛신탁"], cancelled=True),
            E("3", "소유권이전, 2번신탁등기말소", "2020-01-01", "신탁재산의귀속", ["박민수"]),
        ]
        rep = run(owner_req(rows, ["박민수"]))
        assert lv(rep, "R2") == G
        assert lv(rep, "R1") == G

    def test_trust_cancellation_record_alone(self):
        rows = [
            bojon("김철수"),
            E("2", "소유권이전", "2015-01-01", "신탁", ["한빛신탁"], cancelled=True),
            E("3", "2번신탁등기말소", "2020-01-01", "신탁재산의귀속", []),
        ]
        rep = run(owner_req(rows, ["김철수"]))
        assert lv(rep, "R2") == G
        assert lv(rep, "R1") == G

    def test_purpose_trust_regardless_of_cause(self):
        rows = [bojon(), E("2", "소유권이전, 신탁", "2020-01-01", "신탁재산의귀속", ["한빛신탁"])]
        assert lv(owner_req(rows, ["한빛신탁"]), "R2") == R

    def test_cancelled_trust_row_ignored(self):
        rows = [bojon(), E("2", "소유권이전", "2015-01-01", "신탁", ["한빛신탁"], cancelled=True)]
        assert lv(owner_req(rows, ["김철수"]), "R2") == G


# =============================================================================
# R3
# =============================================================================
def gapgu_plus(*rows):
    d = demo("A")
    d["registry"]["gapgu"].extend(rows)
    return d


class TestR3:
    @pytest.mark.parametrize(
        "purpose", ["가압류", "압류", "가처분", "소유권이전청구권가등기", "임의경매개시결정", "강제경매개시결정"]
    )
    def test_red(self, purpose):
        r = res(run(gapgu_plus(E("3", purpose, "2026-10-01", "2026년9월30일 결정", ["국민은행"]))), "R3")
        assert r.level == R
        assert r.title == R3_TITLE
        assert r.action == R3_ACTION
        assert re.fullmatch(rf"{dre('2026-10-01')}에 {re.escape(purpose)} {re.escape(R3_SUMMARY_TAIL)}", r.summary), r.summary
        assert r.evidence

    def test_cancelled_ignored(self):
        assert lv(gapgu_plus(E("3", "가압류", "2026-10-01", None, ["국민은행"], cancelled=True)), "R3") == G

    def test_cancellation_record_ignored(self):
        d = gapgu_plus(
            E("3", "가압류", "2026-09-01", None, ["국민은행"], cancelled=True),
            E("4", "3번가압류등기말소", "2026-10-15", "2026년10월14일 해제", []),
        )
        assert lv(d, "R3") == G

    @pytest.mark.parametrize(
        "purpose",
        [
            "3번가압류등기말소, 4번압류등기말소",
            "3번가압류등기말소 및 4번압류등기말소",
            "3번가압류등기말소/4번압류등기말소",
            "3번가압류등기말소·4번압류등기말소",
            "3번가압류등기말소4번압류등기말소",
        ],
    )
    def test_multi_piece_cancellation_record_ignored(self, purpose):
        d = gapgu_plus(
            E("3", "가압류", "2026-09-01", None, ["국민은행"], cancelled=True),
            E("4", "압류", "2026-09-02", None, ["용인시"], cancelled=True),
            E("5", purpose, "2026-10-15", "2026년10월14일 해제", []),
        )
        assert lv(d, "R3") == G

    def test_cancellation_restoration_is_not_cancellation(self):
        d = gapgu_plus(
            E("3", "가압류", "2026-09-01", None, ["국민은행"], cancelled=True),
            E("4", "3번가압류등기말소", "2026-10-01", None, [], cancelled=True),
            E("5", "3번가압류등기말소회복", "2026-10-20", "2026년10월19일 결정", []),
        )
        assert lv(d, "R3") == R


# =============================================================================
# R4
# =============================================================================
def eulgu_req(rows):
    d = demo("A")
    d["registry"]["eulgu"] = rows
    return d


class TestR4:
    def test_red_housing_lease_order(self):
        rows = [E("1", "주택임차권", "2026-01-05", "2026년1월5일 수원지방법원의 임차권등기명령(2026카임123)", ["박세입"], 50_000_000)]
        r = res(run(eulgu_req(rows)), "R4")
        assert r.level == R
        assert (r.title, r.summary, r.action) == (R4_RED_TITLE, R4_RED_SUMMARY, R4_RED_ACTION)
        assert r.evidence

    def test_red_by_cause_only(self):
        rows = [E("1", "임차권설정", "2026-01-05", "임차권등기명령", ["박세입"], 50_000_000)]
        assert lv(eulgu_req(rows), "R4") == R

    def test_red_by_purpose_only(self):
        rows = [E("1", "주택임차권", "2026-01-05", None, ["박세입"], 50_000_000)]
        assert lv(eulgu_req(rows), "R4") == R

    def test_yellow_lease_registration(self):
        rows = [E("1", "임차권설정", "2025-01-05", "설정계약", ["박세입"], 50_000_000)]
        r = res(run(eulgu_req(rows)), "R4")
        assert r.level == Y
        assert r.title == R4_Y_TITLE
        assert r.summary == R4_Y_SUMMARY.format(h="박세입", a="5,000만 원")
        assert r.action == R4_Y_ACTION

    @pytest.mark.parametrize(
        "rows",
        [
            [],
            [E("1", "근저당권설정", "2020-01-01", "설정계약", ["국민은행"], 100_000_000)],
            [E("1", "전세권설정", "2020-01-01", "설정계약", ["홍길동"], 100_000_000)],
            [E("1", "주택임차권", "2026-01-05", "임차권등기명령", ["박세입"], 50_000_000, cancelled=True)],
            [
                E("1", "주택임차권", "2026-01-05", "임차권등기명령", ["박세입"], 50_000_000, cancelled=True),
                E("2", "1번주택임차권등기말소", "2026-06-01", "2026년5월30일 해제", []),
            ],
        ],
    )
    def test_green(self, rows):
        assert lv(eulgu_req(rows), "R4") == G


# =============================================================================
# R5
# =============================================================================
def r5_req(deposit, market=100_000_000, eulgu=(), prior=None, manual_market=None, method="same_building"):
    d = demo("A")
    d["contract"]["deposit"] = deposit
    d["registry"]["eulgu"] = list(eulgu)
    d["manual"]["prior_deposits"] = prior
    d["manual"]["market_price"] = manual_market
    d["market"] = None if market is None else {"price": market, "method": method, "deals": 2, "period": "2025-12 ~ 2026-11"}
    return d


class TestR5:
    @pytest.mark.parametrize(
        "deposit,level,pct",
        [
            (80_000_000, R, 80),  # exactly 0.8
            (79_999_999, Y, 79),  # 79.99..% -> "79%" (floor), judged unfloored
            (70_000_000, Y, 70),  # exactly 0.7
            (69_999_999, G, 69),
            (29_000_000, G, 29),  # float trap: 0.29*100 = 28.999...
            (57_000_000, G, 57),  # float trap: 0.57*100 = 56.999...
            (100_000_000, R, 100),
        ],
    )
    def test_thresholds_and_floor(self, deposit, level, pct):
        r = res(run(r5_req(deposit)), "R5")
        assert r.level == level
        assert re.search(rf"(?<!\d){pct}%", r.summary), r.summary

    def test_red_texts(self):
        r = res(run(r5_req(80_000_000)), "R5")
        assert r.title == R5_TITLE and r.action == R5_ACTION
        assert r.summary.startswith("선순위 0원 + 내 보증금 8,000만 원 = 시세(1억 원"), r.summary
        assert r.summary.endswith(f")의 80%예요. {R5_SUMMARY_TAIL}"), r.summary

    def test_yellow_texts(self):
        r = res(run(r5_req(70_000_000)), "R5")
        assert r.title == R5_TITLE and r.action == R5_ACTION
        assert r.summary.endswith(f")의 70%예요. {R5_SUMMARY_TAIL}"), r.summary

    def test_scenario_c_text(self):
        """4.3 wireframe: 선순위 0원 + 내 보증금 1억 8,000만 원 = 시세(2억 원)의 90%예요."""
        r = res(run(demo("C")), "R5")
        assert r.summary.startswith("선순위 0원 + 내 보증금 1억 8,000만 원 = 시세(2억 원"), r.summary
        assert ")의 90%예요." in r.summary

    def test_green_still_shows_ratio(self):
        r = res(run(r5_req(10_000_000)), "R5")
        assert r.level == G and "10%" in r.summary

    def test_senior_sum_components(self):
        eulgu = [
            E("1", "근저당권설정", "2020-01-01", "설정계약", ["국민은행"], 100_000_000),
            E("1-1", "1번근저당권변경", "2021-01-01", "변경계약", ["국민은행"], 150_000_000),
            E("2", "전세권설정", "2021-02-01", "설정계약", ["홍길동"], 50_000_000),
            E("3", "임차권설정", "2021-03-01", "설정계약", ["박세입"], 30_000_000),
        ]
        r = res(run(r5_req(50_000_000, 400_000_000, eulgu, prior=20_000_000)), "R5")
        assert r.level == Y
        assert r.summary.startswith("선순위 2억 5,000만 원 + 내 보증금 5,000만 원 = 시세(4억 원"), r.summary
        assert ")의 75%예요." in r.summary

    @pytest.mark.parametrize(
        "eulgu,level,pct",
        [
            # 부기 with no amount does not erase 1's amount
            ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
              E("1-1", "1번근저당권이전", "2021-01-01", "확정채권양도", ["B은행"], None)], G, 65),
            # 부기 amount replaces (not added)
            ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
              E("1-1", "1번근저당권변경", "2021-01-01", "변경계약", ["A은행"], 150_000_000)], R, 90),
            # 질권 amount neither added nor used
            ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
              E("1-1", "1번근저당권부질권", "2021-01-01", "설정계약", ["C캐피탈"], 50_000_000)], G, 65),
            # separate groups add: (60+50+30)/200 = 70% -> yellow
            ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 60_000_000),
              E("2", "근저당권설정", "2021-01-01", "설정계약", ["B은행"], 50_000_000)], Y, 70),
        ],
    )
    def test_bugi_grouping(self, eulgu, level, pct):
        # deposit 30M, market 200M  -> (senior + 30M) / 200M
        r = res(run(r5_req(30_000_000, 200_000_000, eulgu)), "R5")
        assert r.level == level, r.summary
        assert re.search(rf"(?<!\d){pct}%", r.summary), r.summary

    def test_rows_without_rank_not_grouped(self):
        eulgu = [
            E("", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 30_000_000),
            E("", "근저당권설정", "2021-01-01", "설정계약", ["B은행"], 20_000_000),
        ]
        r = res(run(r5_req(30_000_000, 100_000_000, eulgu)), "R5")
        assert r.level == R and "80%" in r.summary, r.summary

    @pytest.mark.parametrize(
        "row",
        [
            E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], None),
            E("1", "전세권설정", "2020-01-01", "설정계약", ["홍길동"], None),
            E("1", "임차권설정", "2020-01-01", "설정계약", ["박세입"], None),
        ],
    )
    def test_unknown_senior_amount(self, row):
        r = res(run(r5_req(30_000_000, 200_000_000, [row])), "R5")
        assert r.level == U and r.unknown_reason

    def test_cancelled_unknown_amount_ignored(self):
        row = E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], None, cancelled=True)
        assert lv(r5_req(80_000_000, 100_000_000, [row]), "R5") == R

    def test_manual_prior_deposits_added(self):
        r = res(run(r5_req(30_000_000, 100_000_000, prior=50_000_000)), "R5")
        assert r.level == R
        assert r.summary.startswith("선순위 5,000만 원 + 내 보증금 3,000만 원 = 시세(1억 원"), r.summary

    def test_manual_market_used_when_no_market(self):
        r = res(run(r5_req(80_000_000, market=None, manual_market=100_000_000)), "R5")
        assert r.level == R and "80%" in r.summary

    def test_manual_market_used_when_market_price_null(self):
        d = r5_req(80_000_000, market=None, manual_market=100_000_000)
        d["market"] = {"price": None, "method": "same_dong", "deals": 0, "period": "2025-12 ~ 2026-11"}
        r = res(run(d), "R5")
        assert r.level == R and "80%" in r.summary

    def test_manual_market_preferred_over_market_price(self):
        # v0.3 reversed the order: typed manual.market_price wins (PRD.md line 483; F8 line 247)
        r = res(run(r5_req(80_000_000, 100_000_000, manual_market=1_000_000_000)), "R5")
        assert r.level == G and "의 8%" in r.summary, r.summary
        assert "시세(10억 원" in r.summary, r.summary

    @pytest.mark.parametrize("price", [0, -100_000_000])
    def test_nonpositive_market_unknown(self, price):
        r = res(run(r5_req(80_000_000, market=price)), "R5")
        assert r.level == U and r.unknown_reason

    def test_no_market_unknown(self):
        r = res(run(r5_req(80_000_000, market=None)), "R5")
        assert r.level == U and r.unknown_reason

    def test_no_deposit_unknown(self):
        d = r5_req(None)
        d["manual"]["deposit"] = None
        r = res(run(d), "R5")
        assert r.level == U and r.unknown_reason

    def test_manual_deposit_when_no_contract(self):
        d = r5_req(None)
        d["contract"] = None
        d["manual"]["deposit"] = 80_000_000
        assert lv(d, "R5") == R

    def test_manual_deposit_when_contract_deposit_null(self):
        d = r5_req(None)
        d["manual"]["deposit"] = 80_000_000
        assert lv(d, "R5") == R

    def test_contract_deposit_preferred_over_manual(self):
        """Ambiguous PRD: assumed 계약서 → 직접 입력 order (as 7.1 기준일)."""
        d = r5_req(10_000_000)
        d["manual"]["deposit"] = 80_000_000
        assert lv(d, "R5") == G

    @pytest.mark.parametrize("word", ["다가구주택", "단독주택", "다중주택"])
    def test_r7_condition_unknown(self, word):
        d = r5_req(80_000_000)
        d["registry"]["registry_type"] = "건물"
        d["registry"]["building_use_lines"] = [f"철근콘크리트구조 철근콘크리트지붕 4층 {word}"]
        r = res(run(d), "R5")
        assert r.level == U
        assert r.unknown_reason and R5_DAGAGU_REASON in r.unknown_reason, r.unknown_reason

    def test_building_without_r7_words_is_computed(self):
        d = r5_req(80_000_000)
        d["registry"]["registry_type"] = "건물"
        d["registry"]["building_use_lines"] = ["철근콘크리트구조 철근콘크리트지붕 4층 제2종근린생활시설"]
        assert lv(d, "R5") == R

    def test_market_evidence(self):
        r = res(run(demo("C")), "R5")
        mk = [e for e in r.evidence if e.doc == "market"]
        assert mk, r.evidence
        # PRD v0.5: 시세 근거의 기간은 "YYYY년 M월 ~ YYYY년 M월"로 표기
        assert any("2025년 12월 ~ 2026년 11월" in e.text and "2" in e.text for e in mk), mk

    def test_manual_market_evidence_doc(self):
        r = res(run(r5_req(80_000_000, market=None, manual_market=100_000_000)), "R5")
        assert any(e.doc == "manual" for e in r.evidence), r.evidence

    def test_same_dong_marked_estimate(self):
        """F8: same_dong는 화면에 "추정" 표시."""
        r = res(run(r5_req(80_000_000, method="same_dong")), "R5")
        assert "추정" in r.summary, r.summary


# =============================================================================
# R6
# =============================================================================
class TestR6:
    def test_scenario_b_text(self):
        r = res(run(demo("B")), "R6")
        assert r.level == Y
        assert r.title == R6_TITLE and r.action == R6_ACTION
        assert r.summary == R6_SUMMARY.format(s="1억 2,000만 원")
        assert r.evidence

    @pytest.mark.parametrize(
        "rows,s",
        [
            ([E("1", "저당권설정", "2020-01-01", "설정계약", ["A"], 100_000_000)], "1억 원"),
            ([E("1", "전세권설정", "2020-01-01", "설정계약", ["홍길동"], 100_000_000)], "1억 원"),
            ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
              E("2", "근저당권설정", "2021-01-01", "설정계약", ["B은행"], 50_000_000)], "1억 5,000만 원"),
            ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
              E("1-1", "1번근저당권변경", "2021-01-01", "변경계약", ["A은행"], 150_000_000)], "1억 5,000만 원"),
            ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
              E("1-1", "1번근저당권이전", "2021-01-01", "확정채권양도", ["B은행"], None)], "1억 원"),
            ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
              E("1-1", "1번근저당권부질권", "2021-01-01", "설정계약", ["C캐피탈"], 50_000_000)], "1억 원"),
            ([E("", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 30_000_000),
              E("", "근저당권설정", "2021-01-01", "설정계약", ["B은행"], 20_000_000)], "5,000만 원"),
        ],
    )
    def test_yellow_sum(self, rows, s):
        r = res(run(eulgu_req(rows)), "R6")
        assert r.level == Y
        assert r.summary == R6_SUMMARY.format(s=s)

    def test_partly_unknown_amount(self):
        rows = [
            E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
            E("2", "근저당권설정", "2021-01-01", "설정계약", ["B은행"], None),
        ]
        r = res(run(eulgu_req(rows)), "R6")
        assert r.summary == "채권최고액 등 1억 원 이상이 내 보증금보다 먼저 돌려받아요."

    def test_all_unknown_amount(self):
        rows = [E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], None)]
        r = res(run(eulgu_req(rows)), "R6")
        assert r.level == Y
        assert r.summary == "채권최고액 등 확인되지 않은 금액이 내 보증금보다 먼저 돌려받아요."

    @pytest.mark.parametrize(
        "rows",
        [
            [],
            [E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000, cancelled=True)],
            [E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000, cancelled=True),
             E("2", "1번근저당권설정등기말소", "2021-01-01", "2021년1월1일 해지", [])],
            [E("1", "임차권설정", "2020-01-01", "설정계약", ["박세입"], 30_000_000)],
        ],
    )
    def test_green(self, rows):
        assert lv(eulgu_req(rows), "R6") == G


# =============================================================================
# R7
# =============================================================================
def r7_req(rtype, lines):
    d = demo("A")
    d["registry"]["registry_type"] = rtype
    d["registry"]["building_use_lines"] = lines
    return d


class TestR7:
    @pytest.mark.parametrize("word", ["다가구주택", "단독주택", "다중주택"])
    def test_yellow(self, word):
        line = f"철근콘크리트구조 철근콘크리트지붕 3층 {word}"
        r = res(run(r7_req("건물", [line, "1층 100㎡"])), "R7")
        assert r.level == Y
        assert (r.title, r.summary, r.action) == (R7_TITLE, R7_SUMMARY, R7_ACTION)
        assert any(word in e.text for e in r.evidence), r.evidence

    def test_collective_green_even_with_word(self):
        assert lv(r7_req("집합건물", ["철근콘크리트구조 4층 다가구주택"]), "R7") == G

    @pytest.mark.parametrize(
        "rtype,lines",
        [("건물", ["철근콘크리트구조 철근콘크리트지붕 3층 제2종근린생활시설"]), ("건물", []), (None, ["3층 다가구주택"])],
    )
    def test_unknown(self, rtype, lines):
        r = res(run(r7_req(rtype, lines)), "R7")
        assert r.level == U and r.unknown_reason


# =============================================================================
# R8
# =============================================================================
def r8_req(received, cause="2026년8월1일 매매", contract_date="2026-11-14", manual_date=None, contract=True):
    d = demo("A")
    d["registry"]["gapgu"] = [bojon("김철수"), E("2", "소유권이전", received, cause, ["박민수"], page=2)]
    d["manual"]["contract_date"] = manual_date
    if contract:
        d["contract"]["landlord_names"] = ["박민수"]
        d["contract"]["contract_date"] = contract_date
    else:
        d["contract"] = None
        d["manual"]["landlord_name"] = "박민수"
    return d


def r8_summary_re(received, cause_part, when):
    return rf"{dre(received)}에 소유권이 {cause_part}바뀌었어요 \(기준일 {when}\)\. {re.escape(R8_SUMMARY_TAIL)}"


class TestR8:
    def test_90_days_yellow_texts(self):
        r = res(run(r8_req("2026-08-16")), "R8")
        assert r.level == Y
        assert r.title == R8_TITLE and r.action == R8_ACTION
        assert re.fullmatch(r8_summary_re("2026-08-16", "매매로 ", "90일 전"), r.summary), r.summary
        assert r.evidence

    def test_91_days_green(self):
        assert lv(r8_req("2026-08-15"), "R8") == G

    def test_same_day(self):
        r = res(run(r8_req("2026-11-14")), "R8")
        assert r.level == Y
        assert re.fullmatch(r8_summary_re("2026-11-14", "매매로 ", "당일"), r.summary), r.summary

    def test_after_reference_date(self):
        r = res(run(r8_req("2026-11-20")), "R8")
        assert r.level == Y
        assert re.fullmatch(r8_summary_re("2026-11-20", "매매로 ", "6일 후"), r.summary), r.summary

    @pytest.mark.parametrize(
        "cause,expect",
        [
            ("2026년10월1일 매매", "매매로 "),
            ("신탁", "신탁으로 "),
            ("2026년10월1일 증여", "증여로 "),
            ("2026년10월1일 상속", "상속으로 "),
            ("2026년10월1일 확정판결", "확정판결로 "),  # ㄹ받침 + 로
            (None, ""),  # 등기원인이 없으면 "소유권이 바뀌었어요"
        ],
    )
    def test_cause_text_and_josa(self, cause, expect):
        r = res(run(r8_req("2026-10-01", cause=cause)), "R8")
        assert r.level == Y
        assert re.fullmatch(r8_summary_re("2026-10-01", expect, "44일 전"), r.summary), r.summary

    def test_no_received_date_unknown(self):
        r = res(run(r8_req(None)), "R8")
        assert r.level == U and r.unknown_reason

    def test_reference_is_contract_date_not_today(self):
        assert lv(r8_req("2026-10-01", contract_date="2026-12-31"), "R8") == G  # 91 days
        r = res(run(r8_req("2026-10-02", contract_date="2026-12-31")), "R8")
        assert r.level == Y and "90일 전" in r.summary

    def test_reference_manual_date_when_contract_has_none(self):
        assert lv(r8_req("2026-10-01", contract_date=None, manual_date="2026-12-31"), "R8") == G

    def test_reference_manual_date_without_contract(self):
        assert lv(r8_req("2026-10-01", contract=False, manual_date="2026-12-31"), "R8") == G

    def test_reference_today_fallback(self):
        r = res(run(r8_req("2026-10-01", contract_date=None)), "R8")
        assert r.level == Y and "44일 전" in r.summary

    def test_contract_date_precedes_manual_date(self):
        assert lv(r8_req("2026-10-01", contract_date="2026-12-31", manual_date="2026-11-14"), "R8") == G

    def test_only_last_valid_ownership_row(self):
        d = r8_req("2026-10-01")
        d["registry"]["gapgu"][1]["is_cancelled"] = True
        d["contract"]["landlord_names"] = ["김철수"]
        assert lv(d, "R8") == G

    def test_provisional_registration_not_ownership(self):
        d = demo("A")
        d["registry"]["gapgu"].append(E("3", "소유권이전청구권가등기", "2026-11-01", "2026년10월30일 매매예약", ["박민수"]))
        assert lv(d, "R8") == G

    def test_partial_transfer_is_ownership_row(self):
        d = demo("A")
        d["registry"]["gapgu"].append(E("3", "소유권일부이전", "2026-10-01", "2026년9월1일 매매", ["박민수"]))
        assert lv(d, "R8") == Y

    def test_scenario_b_and_c_text(self):
        b = res(run(demo("B")), "R8")
        assert re.fullmatch(r8_summary_re("2026-09-15", "매매로 ", "60일 전"), b.summary), b.summary
        c = res(run(demo("C")), "R8")
        assert re.fullmatch(r8_summary_re("2026-08-26", "신탁으로 ", "80일 전"), c.summary), c.summary


# =============================================================================
# R9
# =============================================================================
class TestR9:
    def test_red(self):
        d = demo("A")
        d["building"]["is_violating"] = True
        r = res(run(d), "R9")
        assert r.level == R
        assert (r.title, r.summary, r.action) == (R9_TITLE, R9_SUMMARY, R9_ACTION)
        assert any(e.doc == "building" for e in r.evidence), r.evidence

    def test_green(self):
        assert lv(demo("A"), "R9") == G

    def test_unknown_null(self):
        d = demo("A")
        d["building"]["is_violating"] = None
        r = res(run(d), "R9")
        assert r.level == U and r.unknown_reason

    def test_unknown_no_building(self):
        d = demo("A")
        d["building"] = None
        r = res(run(d), "R9")
        assert r.level == U and r.unknown_reason


# =============================================================================
# R10
# =============================================================================
BLDG_LINE = "철근콘크리트구조 철근콘크리트지붕 4층 공동주택(다세대주택)"


def r10_req(lines, floor="3층", ho="302호", rtype="집합건물", building=None):
    d = demo("A")
    d["registry"]["registry_type"] = rtype
    d["registry"]["building_use_lines"] = lines
    d["registry"]["unit"]["floor"] = floor
    d["registry"]["unit"]["ho"] = ho
    d["building"] = building
    return d


def bldg(unit_use=None, main_use=None):
    return {"main_use": main_use, "unit_use": unit_use, "is_violating": False, "source": "pdf", "source_text": "건축물대장 원문"}


class TestR10:
    @pytest.mark.parametrize(
        "unit_use,main_use,josa",
        [
            ("제2종근린생활시설", "공동주택", "이에요"),
            ("사무소", "공동주택", "예요"),
            (None, "업무시설", "이에요"),
            ("", "제1종근린생활시설", "이에요"),
            ("기타", None, "예요"),
        ],
    )
    def test_building_register_yellow(self, unit_use, main_use, josa):
        use = unit_use or main_use
        r = res(run(r10_req([BLDG_LINE, "3층 다세대주택"], building=bldg(unit_use, main_use))), "R10")
        assert r.level == Y
        assert r.title == R10_TITLE and r.action == R10_ACTION
        assert r.summary == f"이 호실의 용도는 '{use}'{josa}. {R10_SUMMARY_TAIL}"
        assert any(e.doc == "building" for e in r.evidence), r.evidence

    @pytest.mark.parametrize("use", ["다세대주택", "오피스텔", "아파트", "공동주택(아파트)"])
    def test_building_register_green(self, use):
        assert lv(r10_req(["3층 사무소"], building=bldg(use)), "R10") == G

    def test_building_register_empty_falls_back_to_registry(self):
        assert lv(r10_req([BLDG_LINE, "3층 사무소"], building=bldg(None, None)), "R10") == Y
        assert lv(r10_req([BLDG_LINE, "3층 다세대주택"], building=bldg("", "")), "R10") == G

    def test_registry_scenario_a_green(self):
        d = demo("A")
        d["building"] = None
        assert lv(d, "R10") == G

    def test_floor_3_not_13(self):
        lines = ["철근콘크리트구조 철근콘크리트지붕 15층 공동주택(아파트)", "13층 공동주택(아파트)", "3층 제2종근린생활시설"]
        r = res(run(r10_req(lines)), "R10")
        assert r.level == Y
        assert "제2종근린생활시설" in r.summary and r.title == R10_TITLE and r.action == R10_ACTION

    def test_floor_3_not_13_first_match(self):
        lines = ["철근콘크리트구조 철근콘크리트지붕 15층 업무시설", "13층 업무시설", "3층 공동주택(아파트)"]
        assert lv(r10_req(lines), "R10") == G

    def test_floor_3_not_basement_3(self):
        lines = [BLDG_LINE, "지하3층 공동주택", "3층 사무소"]
        assert lv(r10_req(lines), "R10") == Y

    def test_floor_3_not_basement_3_first_match(self):
        lines = [BLDG_LINE, "지하3층 주차장", "3층 다세대주택"]
        assert lv(r10_req(lines), "R10") == G

    def test_floor_line_preferred_over_structure_line(self):
        lines = [BLDG_LINE, "1층 다세대주택", "4층 제2종근린생활시설"]
        assert lv(r10_req(lines, floor="4층", ho="401호"), "R10") == Y

    def test_structure_line_used_when_no_floor_line(self):
        assert lv(r10_req([BLDG_LINE, "1층 제2종근린생활시설"]), "R10") == G
        lines = ["철근콘크리트구조 철근콘크리트지붕 2층 제2종근린생활시설", "1층 다세대주택"]
        assert lv(r10_req(lines), "R10") == Y

    def test_no_floor_line_no_structure_line_unknown(self):
        r = res(run(r10_req(["1층 다세대주택", "2층 다세대주택"])), "R10")
        assert r.level == U and r.unknown_reason

    def test_floor_from_3_digit_ho(self):
        assert lv(r10_req([BLDG_LINE, "3층 제2종근린생활시설"], floor=None, ho="302호"), "R10") == Y

    def test_floor_from_4_digit_ho(self):
        lines = ["철근콘크리트구조 철근콘크리트지붕 15층 공동주택(아파트)", "12층 업무시설"]
        assert lv(r10_req(lines, floor=None, ho="1203호"), "R10") == Y

    @pytest.mark.parametrize("ho", ["지하101호", "B101호"])
    def test_basement_ho_unknown(self, ho):
        lines = [BLDG_LINE, "지하1층 제2종근린생활시설", "1층 다세대주택"]
        r = res(run(r10_req(lines, floor=None, ho=ho)), "R10")
        assert r.level == U and r.unknown_reason

    @pytest.mark.parametrize(
        "word",
        ["시설", "사무소", "사무실", "점포", "상가", "주차장", "창고", "공장", "음식점", "소매점", "학원", "고시원", "의원", "숙박", "업무", "판매", "위락"],
    )
    def test_registry_nonresidential_words_yellow(self, word):
        assert lv(r10_req([f"3층 {word} 100.00㎡"]), "R10") == Y

    def test_registry_unrecognized_use_unknown(self):
        r = res(run(r10_req(["3층 기타 100.00㎡"])), "R10")
        assert r.level == U and r.unknown_reason

    @pytest.mark.parametrize("use", ["아파트", "오피스텔", "다세대주택"])
    def test_registry_residential_green(self, use):
        assert lv(r10_req([f"3층 {use} 100.00㎡"]), "R10") == G

    def test_non_collective_uses_all_lines(self):
        d = demo("B")
        d["building"] = None
        assert lv(d, "R10") == G
        lines = ["철근콘크리트구조 철근콘크리트지붕 3층 제2종근린생활시설", "1층 제2종근린생활시설", "2층 사무소"]
        assert lv(r10_req(lines, rtype="건물", floor=None, ho=None), "R10") == Y

    def test_no_lines_no_building_unknown(self):
        r = res(run(r10_req([])), "R10")
        assert r.level == U and r.unknown_reason


# =============================================================================
# R11
# =============================================================================
A_ADDR = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호"


def r11_req(addr=A_ADDR, c_dong=None, c_ho="302호", r_dong=None, r_ho="302호",
            jibun="경기도 용인시 수지구 죽전동 123-4", road="경기도 용인시 수지구 포은대로 123", rtype="집합건물"):
    d = demo("A")
    d["contract"]["address"] = addr
    d["contract"]["unit"] = {"dong": c_dong, "ho": c_ho}
    d["registry"]["unit"]["dong"] = r_dong
    d["registry"]["unit"]["ho"] = r_ho
    d["registry"]["address_jibun"] = jibun
    d["registry"]["address_road"] = road
    d["registry"]["registry_type"] = rtype
    return d


class TestR11:
    def test_unknown_no_contract(self):
        d = demo("A")
        d["contract"] = None
        r = res(run(d), "R11")
        assert r.level == U and r.unknown_reason

    def test_unknown_no_address_beats_ho_mismatch(self):
        r = res(run(r11_req(addr=None, c_ho="303호")), "R11")
        assert r.level == U and r.unknown_reason

    def test_red_ho_mismatch_texts(self):
        r = res(run(r11_req(c_ho="303호")), "R11")
        assert r.level == R
        assert r.title == R11_RED_TITLE and r.action == R11_RED_ACTION
        assert r.summary == f"등기부는 302호, 계약서는 303호예요. {R11_RED_TAIL}"
        assert r.evidence

    def test_red_ho_missing_text(self):
        r = res(run(r11_req(addr="경기도 용인시 수지구 죽전동 123-4 죽전○○빌라", c_ho=None)), "R11")
        assert r.level == R
        assert r.summary.startswith("등기부는 302호인데, 계약서에는 호수가 없어요."), r.summary

    def test_ho_read_from_address_when_unit_empty(self):
        assert lv(r11_req(c_ho=None), "R11") == G
        assert lv(r11_req(addr="경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 303호", c_ho=None), "R11") == R

    def test_unit_ho_wins_over_address(self):
        assert lv(r11_req(addr="경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 303호", c_ho="302호"), "R11") == G

    @pytest.mark.parametrize("r_ho,c_ho", [("제302호", "302호"), ("302호", "302"), ("302호", "제302호")])
    def test_ho_normalization(self, r_ho, c_ho):
        assert lv(r11_req(r_ho=r_ho, c_ho=c_ho), "R11") == G

    def test_ho_with_je_in_address(self):
        assert lv(r11_req(addr="경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 제302호", c_ho=None), "R11") == G

    def test_dong_compared_when_registry_has_dong(self):
        assert lv(r11_req(r_dong="101동", c_dong="101동"), "R11") == G
        r = res(run(r11_req(r_dong="101동", c_dong="102동")), "R11")
        assert r.level == R and "101동" in r.summary and "102동" in r.summary, r.summary
        assert lv(r11_req(r_dong="101동", c_dong=None), "R11") == R

    def test_dong_read_from_address_not_legal_dong(self):
        addr = "경기도 용인시 수지구 죽전동 123-4 ○○아파트 101동 302호"
        assert lv(r11_req(addr=addr, r_dong="101동", c_dong=None, c_ho=None), "R11") == G

    def test_dong_ignored_when_registry_has_none(self):
        assert lv(r11_req(r_dong=None, c_dong="101동"), "R11") == G

    @pytest.mark.parametrize(
        "addr",
        [
            "용인시 수지구 죽전동 123-4 죽전○○빌라 302호",
            "경기도 용인시 수지구 포은대로 123, 302호",
            "경기도 용인시 수지구 죽전동 123-4번지 죽전○○빌라 302호",
            "경기도 용인시 수지구 죽전동123-4 죽전○○빌라302호",
        ],
    )
    def test_address_green(self, addr):
        assert lv(r11_req(addr=addr), "R11") == G

    def test_yellow_texts(self):
        r = res(run(r11_req(addr="경기도 용인시 수지구 죽전동 123-5 죽전○○빌라 302호")), "R11")
        assert r.level == Y
        assert (r.title, r.summary, r.action) == (R11_Y_TITLE, R11_Y_SUMMARY, R11_Y_ACTION)
        assert r.evidence

    def test_road_only_registry(self):
        assert lv(r11_req(addr="용인시 포은대로 123 302호", jibun=None), "R11") == G

    def test_unknown_no_registry_address(self):
        r = res(run(r11_req(jibun=None, road=None)), "R11")
        assert r.level == U and r.unknown_reason

    def test_red_before_unknown_registry_address(self):
        assert lv(r11_req(c_ho="303호", jibun=None, road=None), "R11") == R

    def test_red_before_yellow(self):
        assert lv(r11_req(addr="경기도 용인시 수지구 죽전동 123-5 302호", c_ho="303호"), "R11") == R

    def test_unknown_registry_ho(self):
        r = res(run(r11_req(r_ho=None)), "R11")
        assert r.level == U and r.unknown_reason

    def test_non_collective_ignores_ho(self):
        assert lv(r11_req(addr="경기도 용인시 수지구 죽전동 123-4", c_ho=None, rtype="건물"), "R11") == G
        assert lv(r11_req(addr="경기도 용인시 수지구 죽전동 999-9", c_ho=None, rtype="건물"), "R11") == Y

    def test_jibun_extracted_from_full_registry_address(self):
        """Real 집합건물 표제부 often has building name / 층 / 호 after the 지번."""
        jibun = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 제3층 제302호"
        assert lv(r11_req(jibun=jibun, road=None), "R11") == G

    @pytest.mark.parametrize(
        "addr",
        ["경기도 용인시 수지구 죽전동 123-45 죽전○○빌라 302호", "경기도 용인시 수지구 포은대로 1234, 302호"],
    )
    def test_lot_number_prefix_is_not_a_match(self, addr):
        """Ambiguous (literal 'contains' would say green): 123-45 is a different lot than 123-4."""
        assert lv(r11_req(addr=addr), "R11") == Y


# =============================================================================
# R12
# =============================================================================
class TestR12:
    def test_unknown_no_contract(self):
        d = demo("A")
        d["contract"] = None
        r = res(run(d), "R12")
        assert r.level == U and r.unknown_reason

    def test_yellow_no_terms(self):
        r = res(run(demo("C")), "R12")
        assert r.level == Y
        assert (r.title, r.summary, r.action) == (R12_TITLE, R12_SUMMARY, R12_ACTION)
        assert any(e.doc == "contract" and e.text == "특약 없음" for e in r.evidence), r.evidence

    def test_yellow_unrelated_terms(self):
        r = res(run(demo("B")), "R12")
        assert r.level == Y
        assert any("반려동물" in e.text for e in r.evidence), r.evidence

    @pytest.mark.parametrize(
        "term",
        [
            "잔금일까지 담보 제공을 하지 않는다.",
            "임대인은 저당을 잡히지 않는다.",
            "잔금일에 기존 대출을 말소한다.",
            "임대인은 어떤 권리도 설정하지 않는다.",
            "임대인은 어떤 권리도 설정 하지 않는다.",
            "잔금일까지 담 보 제공 금지.",
        ],
    )
    def test_green_keywords(self, term):
        d = demo("A")
        d["contract"]["special_terms"] = ["반려동물은 키우지 않는다.", term]
        assert lv(d, "R12") == G


# =============================================================================
# R13
# =============================================================================
def r13_req(viewed, today="2026-11-14", contract_date="2026-11-14"):
    d = demo("A")
    d["registry"]["viewed_at"] = viewed
    d["today"] = today
    d["contract"]["contract_date"] = contract_date
    return d


class TestR13:
    def test_unknown(self):
        r = res(run(r13_req(None)), "R13")
        assert r.level == U and r.unknown_reason

    @pytest.mark.parametrize(
        "viewed,level",
        [
            ("2026-11-12T10:00:00+09:00", G),  # 2 days
            ("2026-11-11T10:00:00+09:00", Y),  # 3 days
            ("2026-11-14T23:59:00+09:00", G),  # same day
            ("2026-11-15T09:00:00+09:00", G),  # future
            ("2026-11-11T16:00:00+00:00", G),  # = 11-12 01:00 KST -> 2 days
            ("2026-11-11T14:59:59+00:00", Y),  # = 11-11 23:59 KST -> 3 days
            ("2026-11-11T23:30:00", Y),  # naive = KST -> 3 days
            ("2026-11-12T00:30:00", G),  # naive = KST -> 2 days
        ],
    )
    def test_boundaries_and_timezone(self, viewed, level):
        assert lv(r13_req(viewed), "R13") == level

    def test_yellow_texts(self):
        r = res(run(r13_req("2026-11-11T10:00:00+09:00")), "R13")
        assert r.title == R13_TITLE.format(n=3)
        assert r.summary == R13_SUMMARY and r.action == R13_ACTION
        assert r.evidence and any(e.doc == "registry" for e in r.evidence)

    def test_scenario_b_title(self):
        assert res(run(demo("B")), "R13").title == "5일 전에 뗀 등기부예요"

    def test_uses_today_not_contract_date(self):
        assert lv(r13_req("2026-11-14T09:00:00+09:00", contract_date="2026-11-20"), "R13") == G
        assert lv(r13_req("2026-11-10T09:00:00+09:00", contract_date="2026-11-01"), "R13") == Y
