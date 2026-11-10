"""Round 2: edge cases found by black-box probing after the first run.

Tests marked "ambiguous" encode the verifier's reading of an ambiguous rule.
"""

from __future__ import annotations

import pytest

from verify_helpers import R10_ACTION, R10_TITLE, E, demo, lv, res, run

G, Y, R, U = "green", "yellow", "red", "unknown"
A_ADDR = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 302호"


def r11_req(addr=A_ADDR, c_dong=None, c_ho="302호", r_dong=None, r_ho="302호"):
    d = demo("A")
    d["contract"]["address"] = addr
    d["contract"]["unit"] = {"dong": c_dong, "ho": c_ho}
    d["registry"]["unit"]["dong"] = r_dong
    d["registry"]["unit"]["ho"] = r_ho
    return d


# ---------------------------------------------------------------------------
# R11 — 7.2: "비교 전에 공백, "번지", "제", "호" 표기를 정리한다" /
#        "집합건물인데 계약서의 동·호수가 등기부와 다르면 🔴"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "r_ho,c_ho",
    [("B102호", "102호"), ("지하102호", "102호"), ("비102호", "102호"), ("302호", "B302호")],
)
def test_r11_basement_prefix_is_part_of_ho(r_ho, c_ho):
    """Basement unit vs above-ground unit are different 호수; only 공백/번지/제/호 may be normalized."""
    assert lv(r11_req(r_ho=r_ho, c_ho=c_ho), "R11") == R


def test_r11_hyphenated_ho_is_shown_as_written():
    r = res(run(r11_req(c_ho="302-1호")), "R11")
    assert r.level == R
    assert "302-1호" in r.summary, r.summary


def test_r11_ho_glued_to_building_name_in_address():
    """7.4: 계약서 동·호는 contract.unit이 비어 있는 칸만 계약서 주소에서 읽는다 (공백 표기 차이는 정리 대상)."""
    assert lv(r11_req(addr="경기도 용인시 수지구 죽전동 123-4 죽전○○빌라302호", c_ho=None), "R11") == G


def test_r11_dong_and_ho_glued_in_address():
    addr = "경기도 용인시 수지구 죽전동 123-4 ○○아파트 101동302호"
    assert lv(r11_req(addr=addr, r_dong="101동", c_ho=None), "R11") == G


def test_r11_basement_ho_read_from_address():
    addr = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라 지하102호"
    assert lv(r11_req(addr=addr, r_ho="지하102호", c_ho=None), "R11") == G


def test_r11_hangul_letter_dong_read_from_address():
    addr = "경기도 용인시 수지구 죽전동 123-4 ○○빌라 가동 302호"
    assert lv(r11_req(addr=addr, r_dong="가동", c_ho=None), "R11") == G


def test_r11_hangul_letter_dong_mismatch_names_contract_dong():
    addr = "경기도 용인시 수지구 죽전동 123-4 ○○빌라 나동 302호"
    r = res(run(r11_req(addr=addr, r_dong="가동", c_ho=None)), "R11")
    assert r.level == R
    assert "나동" in r.summary, r.summary


# ---------------------------------------------------------------------------
# 12.1 / 7.4: 서류 요청 메시지 주소 = 계약서 주소 → 등기부 주소 + 동·호
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ho", ["B102호", "지하102호", "302-1호"])
def test_12_1_registry_fallback_keeps_ho_as_written(ho):
    d = demo("A")
    d["contract"] = None
    d["manual"]["landlord_name"] = "김○○"
    d["registry"]["unit"]["ho"] = ho
    first = run(d).request_message.split("\n")[0]
    assert ho in first, first


# ---------------------------------------------------------------------------
# R10 — 7.4: "등기부에서는 내 층이 나온 층별 줄을 먼저 쓰고, 없을 때만
#        건물 전체 줄("구조"나 "지붕"이 있는 줄)을 쓴다."
# ---------------------------------------------------------------------------
HDR_RES_4F = "철근콘크리트구조 철근콘크리트지붕 4층 공동주택(다세대주택)"


def r10_req(lines, floor="3층", ho="302호"):
    d = demo("A")
    d["building"] = None
    d["registry"]["building_use_lines"] = lines
    d["registry"]["unit"]["floor"] = floor
    d["registry"]["unit"]["ho"] = ho
    return d


def test_r10_header_fallback_residential():
    """No '3층' line -> use the header line (residential) -> 🟢."""
    assert lv(r10_req([HDR_RES_4F, "1층 제2종근린생활시설"]), "R10") == G


def test_r10_header_fallback_nonresidential():
    """No '3층' line -> use the header line (non-residential) -> 🟡, not ⚪."""
    r = res(run(r10_req(["철근콘크리트구조 철근콘크리트지붕 2층 제2종근린생활시설", "1층 다세대주택"])), "R10")
    assert r.level == Y
    assert r.title == R10_TITLE and r.action == R10_ACTION
    assert "제2종근린생활시설" in r.summary


def test_r10_header_fallback_header_only():
    assert lv(r10_req([HDR_RES_4F]), "R10") == G


def test_r10_header_fallback_does_not_depend_on_total_floor_count():
    """Same building, same lines: a 3rd-floor and a 4th-floor unit must be judged the same way."""
    lines = [HDR_RES_4F, "1층 제2종근린생활시설"]
    assert lv(r10_req(lines, floor="3층", ho="302호"), "R10") == lv(r10_req(lines, floor="4층", ho="402호"), "R10")


def test_r10_bi_prefix_is_basement_ho():
    """7.4: 지하 호수면 ⚪ ("비102호" is the common Korean spelling of B102호)."""
    lines = [HDR_RES_4F, "지하1층 제2종근린생활시설", "1층 다세대주택"]
    r = res(run(r10_req(lines, floor=None, ho="비102호")), "R10")
    assert r.level == U


# ---------------------------------------------------------------------------
# R8 — 7.4: "등기원인 앞의 날짜는 떼고 쓴다"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cause", ["2026-08-20 매매", "2026. 8. 20. 매매"])
def test_r8_other_date_formats_stripped(cause):
    d = demo("A")
    d["registry"]["gapgu"] = [
        E("1", "소유권보존", "2010-01-01", None, ["김○○"]),
        E("2", "소유권이전", "2026-10-01", cause, ["김○○"]),
    ]
    r = res(run(d), "R8")
    assert "소유권이 매매로 바뀌었어요" in r.summary, r.summary


# ---------------------------------------------------------------------------
# 7.4 조사 — "앞 글자가 한글이나 숫자가 아니면(예: "이○○") 7.2의 조사를 그대로 쓴다" (ambiguous)
# ---------------------------------------------------------------------------
def test_josa_skips_closing_bracket():
    # "닫는 괄호·따옴표는 건너뛰고 그 앞 글자를 본다 ("한빛(주)예요")"
    d = demo("A")
    d["registry"]["gapgu"] = [E("1", "소유권보존", "2010-01-01", None, ["박영희"])]
    d["contract"]["landlord_names"] = ["한빛(주)"]
    r = res(run(d), "R1")
    assert r.summary.endswith("계약서의 임대인은 한빛(주)예요."), r.summary


# ---------------------------------------------------------------------------
# Banner impact (7.3) of the discrepancies above, on an otherwise all-green scenario A
# ---------------------------------------------------------------------------
def test_impact_basement_ho_mismatch_turns_banner_red():
    """Registry 'B302호' vs contract '302호' (scenario A otherwise unchanged): R11 🔴 -> 계약 보류 권장."""
    d = demo("A")
    d["registry"]["unit"]["ho"] = "B302호"
    rep = run(d)
    assert rep.overall.title == "계약 보류 권장", (rep.overall.title, res(rep, "R11").level)


def test_impact_glued_ho_in_address_keeps_banner_green():
    """Contract unit.ho empty, address '…죽전○○빌라302호' (same unit): must stay 큰 위험 신호 없음."""
    d = demo("A")
    d["contract"]["unit"] = {"dong": None, "ho": None}
    d["contract"]["address"] = "경기도 용인시 수지구 죽전동 123-4 죽전○○빌라302호"
    rep = run(d)
    assert rep.overall.title == "큰 위험 신호 없음", (rep.overall.title, res(rep, "R11").summary)


def test_impact_r10_header_only_nonresidential_turns_banner_yellow():
    """P0 mode, 집합건물 표제부 extracted as one header line of a 근린생활시설 building, unit on 3층."""
    d = demo("A")
    d["building"] = None
    d["registry"]["building_use_lines"] = ["철근콘크리트구조 철근콘크리트지붕 5층 제2종근린생활시설"]
    rep = run(d)
    assert res(rep, "R10").level == Y
    assert rep.overall.title == "추가 확인 필요", (rep.overall.title, rep.overall.unknown_note)
