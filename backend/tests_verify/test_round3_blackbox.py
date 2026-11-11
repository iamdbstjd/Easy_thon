"""Round 3: black-box checks for the detailed rules (address/unit parsing, R10 order, masking, content).

Tests whose name ends in `_interp` encode the verifier's reading of a rule left open.
"""

from __future__ import annotations

import pytest

from app.schemas import RULE_NAMES
from verify_helpers import (
    MI_ALWAYS,
    MI_R6,
    R1_NAME,
    R10_ACTION,
    R10_SUMMARY_TAIL,
    R10_TITLE,
    R3_ACTION,
    R3_TITLE,
    R8_SUMMARY_TAIL,
    RRN_MASK,
    RRN_RE,
    E,
    demo,
    lv,
    mask_rrn,
    parse_items,
    res,
    run,
)

G, Y, R, U = "green", "yellow", "red", "unknown"


# =============================================================================
# R1 name
# =============================================================================
def test_r1_name_renamed():
    assert RULE_NAMES["R1"] == R1_NAME
    assert res(run(demo("C")), "R1").name == R1_NAME


# =============================================================================
# R10 decision order
# =============================================================================
H_RES = "철근콘크리트구조 철근콘크리트지붕 4층 공동주택(다세대주택)"
H_NONRES = "철근콘크리트구조 철근콘크리트지붕 5층 제2종근린생활시설"
H_MIXED = "철근콘크리트구조 철근콘크리트지붕 5층 제2종근린생활시설 및 다세대주택"
H_PLAIN = "철근콘크리트구조 철근콘크리트지붕 4층"


def r10(lines, floor="3층", ho="302호", rtype="집합건물"):
    d = demo("A")
    d["building"] = None
    d["registry"]["registry_type"] = rtype
    d["registry"]["building_use_lines"] = lines
    d["registry"]["unit"]["floor"] = floor
    d["registry"]["unit"]["ho"] = ho
    return d


def r10_yellow_summary(use, josa="이에요"):
    return f"이 호실의 용도는 '{use}'{josa}. {R10_SUMMARY_TAIL}"


class TestR10Order:
    # step 1: my floor's 층별 줄 with a use word decides
    def test_step1_floor_line_residential_beats_nonres_header(self):
        assert lv(r10([H_NONRES, "3층 다세대주택 112.30㎡"]), "R10") == G

    def test_step1_floor_line_nonresidential(self):
        line = "3층 제2종근린생활시설 112.30㎡"
        r = res(run(r10([H_RES, line])), "R10")
        assert r.level == Y
        assert (r.title, r.action) == (R10_TITLE, R10_ACTION)
        assert r.summary == r10_yellow_summary("제2종근린생활시설"), r.summary
        assert any(e.doc == "registry" and e.text == line for e in r.evidence), r.evidence

    def test_step1_floor_line_with_both_words_is_green(self):
        assert lv(r10([H_NONRES, "3층 다세대주택 및 제2종근린생활시설"]), "R10") == G

    # step 2: floor line has only an area
    def test_step2_area_only_floor_lines_residential_header(self):
        lines = [H_RES, "1층 66.20㎡", "2층 112.30㎡", "3층 112.30㎡", "4층 98.10㎡"]
        r = res(run(r10(lines)), "R10")
        assert r.level == G
        assert any(e.text == H_RES for e in r.evidence), r.evidence

    def test_step2_area_only_nonresidential_header(self):
        r = res(run(r10([H_NONRES, "3층 112.30㎡"])), "R10")
        assert r.level == Y
        assert r.summary == r10_yellow_summary("제2종근린생활시설"), r.summary
        assert any(e.text == H_NONRES for e in r.evidence), r.evidence

    def test_step2_mixed_header_is_unknown(self):
        r = res(run(r10([H_MIXED, "3층 112.30㎡"])), "R10")
        assert r.level == U and r.unknown_reason

    def test_step2_header_without_use_word_is_unknown(self):
        r = res(run(r10([H_PLAIN, "3층 112.30㎡"])), "R10")
        assert r.level == U and r.unknown_reason

    # step 2: my floor's line missing; other floors' 층별 줄 are not used
    def test_step2_missing_floor_line_uses_header_not_other_floors(self):
        assert lv(r10([H_RES, "1층 제2종근린생활시설"]), "R10") == G
        assert lv(r10(["철근콘크리트구조 철근콘크리트지붕 2층 제2종근린생활시설", "1층 다세대주택"]), "R10") == Y

    # header is never a 층별 줄 even if it names my floor
    @pytest.mark.parametrize("floor,ho", [("4층", "402호"), ("3층", "302호")])
    def test_header_floor_count_is_not_a_floor_line(self, floor, ho):
        lines = ["철근콘크리트구조 철근콘크리트지붕 4층 제2종근린생활시설", "1층 다세대주택"]
        assert lv(r10(lines, floor=floor, ho=ho), "R10") == Y

    def test_floor_line_beats_header_on_same_floor_number(self):
        assert lv(r10([H_RES, "4층 제2종근린생활시설"], floor="4층", ho="402호"), "R10") == Y
        assert lv(r10([H_RES, "4층 98.10㎡"], floor="4층", ho="402호"), "R10") == G

    # split header layouts: the use word sits on its own 기타 줄
    def test_split_header_use_on_other_line_residential(self):
        lines = ["철근콘크리트구조 (철근)콘크리트지붕 4층", "공동주택(다세대주택)", "1층 66.20㎡", "3층 112.30㎡"]
        assert lv(r10(lines), "R10") == G

    def test_split_header_use_on_other_line_nonresidential(self):
        r = res(run(r10(["철근콘크리트구조 철근콘크리트지붕 5층", "제2종근린생활시설", "3층 112.30㎡"])), "R10")
        assert r.level == Y
        assert "제2종근린생활시설" in r.summary

    def test_split_header_mixed_other_lines_unknown(self):
        lines = ["철근콘크리트구조 철근콘크리트지붕 5층", "제2종근린생활시설", "공동주택(다세대주택)", "3층 112.30㎡"]
        assert lv(r10(lines), "R10") == U

    def test_split_header_both_parts_are_header_lines(self):
        assert lv(r10(["철근콘크리트구조", "철근콘크리트지붕 4층 공동주택(다세대주택)", "3층 112.30㎡"]), "R10") == G

    def test_single_combined_header_line(self):
        line = "철근콘크리트구조 (철근)콘크리트지붕 4층 공동주택(다세대주택) 1층 66.20㎡ 2층 112.30㎡ 3층 112.30㎡ 4층 98.10㎡"
        assert lv(r10([line]), "R10") == G

    def test_header_plus_nonresidential_other_line_is_mixed(self):
        assert lv(r10([H_RES, "부속건물 창고 20.00㎡"]), "R10") == U

    # floor unknown -> step 2
    def test_floor_unknown_two_digit_ho_uses_header(self):
        assert lv(r10([H_RES, "1층 제2종근린생활시설"], floor=None, ho="12호"), "R10") == G

    def test_floor_and_ho_unknown_uses_header(self):
        assert lv(r10([H_NONRES], floor=None, ho=None), "R10") == Y

    # basement ho (지하·지·B·비) -> ⚪
    @pytest.mark.parametrize("ho", ["지하102호", "지102호", "B102호", "비102호"])
    def test_basement_ho_unknown(self, ho):
        r = res(run(r10([H_RES, "지하1층 다세대주택", "1층 다세대주택"], floor=None, ho=ho)), "R10")
        assert r.level == U and r.unknown_reason

    # 건물 등기부
    @pytest.mark.parametrize(
        "lines,level",
        [
            (["철근콘크리트구조 철근콘크리트지붕 4층 다가구주택", "1층 132.50㎡"], G),
            (["철근콘크리트구조 철근콘크리트지붕 3층 제2종근린생활시설", "2층 사무소"], Y),
            (["1층 132.50㎡", "2층 140.20㎡"], U),
            (["철근콘크리트구조 철근콘크리트지붕 3층 제2종근린생활시설 및 다가구주택"], G),
        ],
    )
    def test_non_collective_all_lines(self, lines, level):
        assert lv(r10(lines, floor=None, ho=None, rtype="건물"), "R10") == level


# =============================================================================
# R11 호 normalization + address reading
# =============================================================================
A_ADDR = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호"


def r11(addr=A_ADDR, c_dong=None, c_ho="302호", r_dong=None, r_ho="302호",
        jibun="경기도 용인시 수지구 죽전동 123-4", road="경기도 용인시 수지구 포은대로 123"):
    d = demo("A")
    d["contract"]["address"] = addr
    d["contract"]["unit"] = {"dong": c_dong, "ho": c_ho}
    d["registry"]["unit"]["dong"] = r_dong
    d["registry"]["unit"]["ho"] = r_ho
    d["registry"]["address_jibun"] = jibun
    d["registry"]["address_road"] = road
    return d


class TestR11V03:
    @pytest.mark.parametrize(
        "r_ho,c_ho",
        [("지하102호", "B102호"), ("비102호", "지하102호"), ("지102호", "B102호"), ("B102호", "B102호"),
         ("302 호", "302호"), ("제302호", "302"), ("302-1호", "302-1호")],
    )
    def test_ho_equal_after_normalization(self, r_ho, c_ho):
        assert lv(r11(r_ho=r_ho, c_ho=c_ho), "R11") == G

    @pytest.mark.parametrize(
        "r_ho,c_ho",
        [("B302호", "302호"), ("302호", "B302호"), ("302-1호", "302호"), ("302호", "302-1호"), ("A302호", "302호"), ("302호", "303호")],
    )
    def test_ho_different_after_normalization(self, r_ho, c_ho):
        assert lv(r11(r_ho=r_ho, c_ho=c_ho), "R11") == R

    def test_red_summary_shows_basement_marker(self):
        r = res(run(r11(r_ho="B102호", c_ho="102호")), "R11")
        assert r.summary.startswith("등기부는 B102호, 계약서는 102호예요.") or r.summary.startswith(
            "등기부는 지하102호, 계약서는 102호예요."
        ), r.summary

    @pytest.mark.parametrize(
        "addr,r_dong,r_ho",
        [
            ("경기도 용인시 수지구 죽전동 123-4 죽전○○빌라302호", None, "302호"),
            ("경기도 용인시 수지구 죽전동 123-4 ○○아파트 101동302호", "101동", "302호"),
            ("경기도 용인시 수지구 죽전동 123-4 ○○빌라 가동 302호", "가동", "302호"),
            ("경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 지하102호", None, "지하102호"),
            ("경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 지하102호", None, "B102호"),
            ("경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 비102호", None, "B102호"),
            ("경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302-1호", None, "302-1호"),
            ("경기도 용인시 수지구 죽전동 123-4 죽전빌리지 302호", None, "302호"),
        ],
    )
    def test_address_reading_matches(self, addr, r_dong, r_ho):
        assert lv(r11(addr=addr, c_ho=None, r_dong=r_dong, r_ho=r_ho), "R11") == G

    @pytest.mark.parametrize(
        "addr,r_dong,r_ho,shown",
        [
            ("경기도 용인시 수지구 죽전동 123-4 ○○빌라 나동 302호", "가동", "302호", "나동"),
            ("경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 지하102호", None, "102호", "102호"),
            ("경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302-1호", None, "302호", "302-1호"),
        ],
    )
    def test_address_reading_mismatches(self, addr, r_dong, r_ho, shown):
        r = res(run(r11(addr=addr, c_ho=None, r_dong=r_dong, r_ho=r_ho)), "R11")
        assert r.level == R
        assert shown in r.summary.split("계약서는")[-1], r.summary

    @pytest.mark.parametrize("r_dong,label", [("가동", "가동"), ("101동", "101동")])
    def test_legal_dong_is_never_building_dong(self, r_dong, label):
        r = res(run(r11(addr=A_ADDR, c_ho=None, r_dong=r_dong)), "R11")
        assert r.level == R
        assert r.summary.startswith(f"등기부는 {label} 302호, 계약서는 302호예요."), r.summary

    def test_one_letter_legal_dong_not_building_dong(self):
        jibun = "경기도 부천시 원미구 중동 1150"
        ok = r11(addr="경기도 부천시 원미구 중동 1150 ○○빌라 가동 302호", c_ho=None, r_dong="가동", jibun=jibun, road=None)
        assert lv(ok, "R11") == G
        bad = r11(addr="경기도 부천시 원미구 중동 1150 ○○빌라 302호", c_ho=None, r_dong="가동", jibun=jibun, road=None)
        r = res(run(bad), "R11")
        assert r.level == R
        assert "계약서는 302호예요" in r.summary, r.summary

    def test_legal_dong_with_dong_inside_name(self):
        jibun = "경기도 용인시 수지구 동천동 123-4"
        d = r11(addr="경기도 용인시 수지구 동천동 123-4 ○○빌라 가동 302호", c_ho=None, r_dong="가동", jibun=jibun, road=None)
        assert lv(d, "R11") == G

    def test_empty_dong_field_read_from_address_while_ho_field_filled(self):
        d = r11(addr="경기도 용인시 수지구 죽전동 123-4 ○○아파트 101동 302호", c_ho="302호", r_dong="101동")
        assert lv(d, "R11") == G

    def test_glued_villa_name_ending_in_ji_interp(self):
        """'죽전빌리지302호': the 지 belongs to the building name, not a basement marker."""
        d = r11(addr="경기도 용인시 수지구 죽전동 123-4 죽전빌리지302호", c_ho=None, r_ho="302호")
        assert lv(d, "R11") == G


# =============================================================================
# R8 date formats
# =============================================================================
def r8(cause, received="2026-10-01"):
    d = demo("A")
    d["registry"]["gapgu"] = [
        E("1", "소유권보존", "2010-01-01", None, ["김○○"]),
        E("2", "소유권이전", received, cause, ["김○○"]),
    ]
    return d


@pytest.mark.parametrize(
    "cause",
    ["2026년8월20일 매매", "2026년 8월 20일 매매", "2026년 08월 20일 매매", "2026-08-20 매매", "2026-08-20매매",
     "2026. 8. 20. 매매", "2026.8.20 매매", "2026.08.20. 매매", "2026/08/20 매매"],
)
def test_r8_date_prefix_removed_any_format(cause):
    r = res(run(r8(cause)), "R8")
    assert r.summary == f"2026년 10월 1일에 소유권이 매매로 바뀌었어요 (기준일 44일 전). {R8_SUMMARY_TAIL}", r.summary


def test_r8_date_prefix_removed_keeps_josa():
    assert "소유권이 신탁으로 바뀌었어요" in res(run(r8("2026-08-26 신탁")), "R8").summary


@pytest.mark.parametrize("cause", ["2026-08-20", "2026년8월20일"])
def test_r8_cause_that_is_only_a_date(cause):
    s = res(run(r8(cause)), "R8").summary
    assert s.startswith("2026년 10월 1일에 소유권이 바뀌었어요 (기준일 44일 전)."), s


# =============================================================================
# R3 multi-record wording
# =============================================================================
TAIL3 = "기록이 있어요. 집이 경매로 넘어가거나 소유자가 바뀔 수 있어요."


def r3(*rows):
    d = demo("A")
    d["registry"]["gapgu"].extend(rows)
    return d


def test_r3_multi_record_each_with_date():
    d = r3(E("3", "가압류", "2026-10-01", "결정", ["국민은행"]), E("4", "압류", "2026-10-02", "압류", ["용인시"]))
    r = res(run(d), "R3")
    assert r.level == R and r.title == R3_TITLE and r.action == R3_ACTION
    assert r.summary == f"가압류(2026년 10월 1일), 압류(2026년 10월 2일) {TAIL3}", r.summary


def test_r3_multi_record_missing_date():
    d = r3(E("3", "가압류", "2026-10-01", "결정", ["국민은행"]), E("4", "압류", None, "압류", ["용인시"]))
    assert res(run(d), "R3").summary == f"가압류(2026년 10월 1일), 압류(날짜 확인 안 됨) {TAIL3}"


def test_r3_three_records():
    d = r3(
        E("3", "가압류", "2026-10-01", "결정", ["국민은행"]),
        E("4", "가처분", "2026-10-05", "결정", ["박민수"]),
        E("5", "임의경매개시결정", "2026-11-01", "결정", ["국민은행"]),
    )
    expected = f"가압류(2026년 10월 1일), 가처분(2026년 10월 5일), 임의경매개시결정(2026년 11월 1일) {TAIL3}"
    assert res(run(d), "R3").summary == expected


def test_r3_single_record_keeps_7_2_template():
    d = r3(E("3", "가압류", "2026-10-01", "결정", ["국민은행"]))
    assert res(run(d), "R3").summary == f"2026년 10월 1일에 가압류 {TAIL3}"


# =============================================================================
# Holderless same-rank 신탁 rows
# =============================================================================
TRUST_SRC = "3 소유권이전 2026년8월26일 제98766호 2026년8월26일 신탁 수탁자 ○○부동산신탁주식회사"


def split_trust(order="normal"):
    d = demo("C")
    rows = d["registry"]["gapgu"][:2]
    transfer = E("3", "소유권이전", "2026-08-26", "신탁", ["○○부동산신탁(주)"], page=2, src=TRUST_SRC)
    trust = E("3", "신탁", "2026-08-26", None, [], page=2, src="3 신탁 신탁원부 제2026-5678호")
    d["registry"]["gapgu"] = rows + ([transfer, trust] if order == "normal" else [trust, transfer])
    return d


@pytest.mark.parametrize("order", ["normal", "reversed"])
def test_holderless_trust_row_does_not_change_owner(order):
    rep = run(split_trust(order))
    r1 = res(rep, "R1")
    assert r1.level == R
    assert r1.summary == "등기부상 소유자는 ○○부동산신탁(주)인데, 계약서의 임대인은 이○○이에요.", r1.summary
    r2 = res(rep, "R2")
    assert r2.level == R and "○○부동산신탁(주)에게" in r2.summary
    assert res(rep, "R8").level == Y
    assert rep.overall.title == "계약 보류 권장"
    assert rep.counts.red == 3


@pytest.mark.parametrize("order", ["normal", "reversed"])
def test_holderless_trust_row_r8_cause_interp(order):
    """Reading: the holderless row is not the transfer that set the owner, so R8 names the 신탁 cause."""
    s = res(run(split_trust(order)), "R8").summary
    assert "소유권이 신탁으로 바뀌었어요 (기준일 80일 전)" in s, s


def test_holderless_trust_only_row_keeps_previous_owner():
    """Line 474 literally: a holderless '신탁' row does not change the owners (R2 still flags the trust)."""
    d = demo("C")
    d["registry"]["gapgu"] = d["registry"]["gapgu"][:2] + [E("3", "신탁", "2026-08-26", None, [], page=2)]
    rep = run(d)
    assert lv(rep, "R1") == G
    assert lv(rep, "R2") == R


# =============================================================================
# 주민등록번호 masking
# =============================================================================
class TestRrnMasking:
    def test_names_in_r1_summary(self):
        d = demo("A")
        d["registry"]["gapgu"] = [E("1", "소유권보존", "2010-01-01", None, ["김철수 850315-1234567"])]
        d["contract"]["landlord_names"] = ["박민수 900101-1******"]
        r = res(run(d), "R1")
        assert r.summary == "등기부상 소유자는 김철수인데, 계약서의 임대인은 박민수예요.", r.summary

    def test_name_in_r2_summary(self):
        d = demo("A")
        d["registry"]["gapgu"].append(E("3", "소유권이전", "2020-01-01", "신탁", ["한빛신탁(주) 110111-1234567"]))
        r = res(run(d), "R2")
        assert r.summary.startswith("등기부상 소유권이 한빛신탁(주)에게 넘어가 있어요."), r.summary

    def test_name_in_r4_summary(self):
        d = demo("A")
        d["registry"]["eulgu"] = [E("1", "임차권설정", "2025-01-05", "설정계약", ["박세입 900101-2******"], 50_000_000)]
        assert res(run(d), "R4").summary == "박세입의 임차권(5,000만 원)이 먼저 등기돼 있어요."

    def test_manual_landlord_name(self):
        d = demo("A")
        d["contract"] = None
        d["manual"]["landlord_name"] = "박민수 900101-1234567"
        r = res(run(d), "R1")
        assert r.summary == "등기부상 소유자는 김○○인데, 입력한 임대인은 박민수예요.", r.summary

    @pytest.mark.parametrize(
        "src",
        [
            "2 소유권이전 2019년6월21일 제45678호 2019년5월30일 매매 소유자 박민수 850315-1234567 서울특별시 송파구 ○○로 45",
            "2 소유권이전 2019년6월21일 제45678호 2019년5월30일 매매 소유자 박민수 850315-1****** 서울특별시 송파구 ○○로 45",
        ],
    )
    def test_evidence_quote_masked_rest_verbatim(self, src):
        d = demo("A")
        d["registry"]["gapgu"][1]["source_text"] = src
        d["registry"]["gapgu"][1]["holders"] = ["박민수"]
        r = res(run(d), "R1")
        assert r.level == R
        assert any(e.doc == "registry" and e.text == mask_rrn(src) for e in r.evidence), r.evidence
        assert RRN_MASK in mask_rrn(src)

    def test_contract_evidence_masked(self):
        r = res(run(demo("C")), "R1")
        con = [e.text for e in r.evidence if e.doc == "contract"]
        assert con == ["임대인 성명 이○○ 주민등록번호 ******-******* 주소 경기도 용인시 수지구 ○○로 78"], con

    def test_special_terms_evidence_masked(self):
        d = demo("A")
        d["contract"]["special_terms"] = ["임대인 김철수(850315-1234567)은 반려동물을 허용한다."]
        d["contract"]["sources"]["special_terms"] = None
        r = res(run(d), "R12")
        assert r.level == Y
        assert [e.text for e in r.evidence] == ["임대인 김철수(******-*******)은 반려동물을 허용한다."], r.evidence

    def test_no_rrn_anywhere_on_screen(self):
        d = demo("A")
        d["registry"]["gapgu"] = [E("1", "소유권보존", "2010-01-01", None, ["김철수 850315-1234567"], src="1 소유권보존 김철수 850315-1234567")]
        d["contract"]["landlord_names"] = ["박민수 900101-1234567"]
        d["contract"]["sources"]["landlord"] = "임대인 박민수 900101-1234567"
        rep = run(d)
        for r in rep.results:
            for t in (r.title, r.summary, r.action, r.unknown_reason or ""):
                assert not RRN_RE.search(t), t
            for e in r.evidence:
                assert all(m == RRN_MASK for m in RRN_RE.findall(e.text)), e.text


# =============================================================================
# R1 manual wording
# =============================================================================
@pytest.mark.parametrize("with_contract", [False, True])
def test_r1_manual_landlord_wording(with_contract):
    d = demo("A")
    if with_contract:
        d["contract"]["landlord_names"] = []
    else:
        d["contract"] = None
    d["manual"]["landlord_name"] = "박민수"
    r = res(run(d), "R1")
    assert r.summary == "등기부상 소유자는 김○○인데, 입력한 임대인은 박민수예요.", r.summary


# =============================================================================
# R5 typed market price first
# =============================================================================
def test_r5_manual_market_label_and_evidence():
    d = demo("A")
    d["contract"]["deposit"] = 80_000_000
    d["manual"]["market_price"] = 100_000_000  # market.price stays 2억
    r = res(run(d), "R5")
    assert r.level == R
    assert r.summary.startswith("내 보증금 8,000만 원이 시세(1억 원"), r.summary
    assert ")의 80%예요." in r.summary, r.summary
    assert any(e.doc == "manual" for e in r.evidence), r.evidence


# =============================================================================
# 근저당 item only with 저당 rows
# =============================================================================
@pytest.mark.parametrize(
    "rows,expected",
    [
        ([E("1", "전세권설정", "2020-01-01", "설정계약", ["홍길동"], 100_000_000)], MI_ALWAYS),
        ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000),
          E("2", "전세권설정", "2020-01-01", "설정계약", ["홍길동"], 50_000_000)], MI_ALWAYS + MI_R6),
        ([E("1", "저당권설정", "2020-01-01", "설정계약", ["A"], 100_000_000)], MI_ALWAYS + MI_R6),
        ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], None)], MI_ALWAYS + MI_R6),
        ([E("1", "근저당권설정", "2020-01-01", "설정계약", ["A은행"], 100_000_000, cancelled=True)], MI_ALWAYS),
    ],
)
def test_12_1_mortgage_item_needs_mortgage_row(rows, expected):
    d = demo("A")
    d["registry"]["eulgu"] = rows
    items = [t for _, t in parse_items(run(d).request_message)]
    assert items == expected, items


# =============================================================================
# 조사 after closing brackets
# =============================================================================
@pytest.mark.parametrize(
    "landlord,ending",
    [("한빛(주)", "한빛(주)예요."), ("한빛(유)", "한빛(유)예요."), ("'한빛'", "'한빛'이에요."),
     ("한빛(A)", "한빛(A)이에요."), ("이○○", "이○○이에요.")],
)
def test_josa_brackets(landlord, ending):
    d = demo("A")
    d["registry"]["gapgu"] = [E("1", "소유권보존", "2010-01-01", None, ["박영희"])]
    d["contract"]["landlord_names"] = [landlord]
    s = res(run(d), "R1").summary
    assert s.endswith(ending), s


# =============================================================================
# Found in round-3 probing
# =============================================================================
@pytest.mark.parametrize("masked", ["850315-1xxxxxx", "850315-1○○○○○○", "850315-1●●●●●●"])
def test_rrn_with_other_mask_chars_in_names(masked):
    """이름 비교 때 주민등록번호 형식(가려진 것 포함)을 지우고, 화면 문구에 넣지 않는다.

    The engine's own evidence masker already treats x/○/● as mask characters; names do not.
    """
    d = demo("A")
    d["registry"]["gapgu"] = [E("1", "소유권보존", "2010-01-01", None, [f"김철수 {masked}"])]
    d["contract"]["landlord_names"] = ["김철수"]
    assert lv(d, "R1") == G
    d["contract"]["landlord_names"] = ["박민수"]
    r = res(run(d), "R1")
    assert r.summary == "등기부상 소유자는 김철수인데, 계약서의 임대인은 박민수예요.", r.summary


def test_holderless_transfer_with_own_rank_is_not_green_interp():
    """Reading of the holderless-row rule + the principle ("모르면 모른다고 한다"): only the split same-rank row
    (e.g. "3 신탁") is exempt. A full 소유권이전 with its own rank and unreadable holders means the
    current owner is unknown, so R1 must not compare the landlord with the previous owner."""
    d = demo("A")
    d["registry"]["gapgu"] = [
        E("1", "소유권보존", "2015-03-10", None, ["김○○"], page=2),
        E("2", "소유권이전", "2019-06-21", "2019년5월30일 매매", [], page=2),
    ]
    rep = run(d)
    assert lv(rep, "R1") == U, res(rep, "R1")
    assert rep.overall.title != "큰 위험 신호 없음"
