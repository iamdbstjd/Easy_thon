"""Black-box verification helpers written from PRD.md only (not from app/rules).

Every expected string below is copied from PRD 7.2 / 7.3 / 12.x.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from pathlib import Path

from app.rules import build_report
from app.schemas import CheckRequest, Report

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"
TODAY = dt.date(2026, 11, 14)
RULE_IDS = [f"R{i}" for i in range(1, 14)]
CORE = ("R1", "R2", "R3", "R7", "R8", "R13")  # PRD 7.3

# ---------------------------------------------------------------------------
# PRD 7.2 copy
# ---------------------------------------------------------------------------
R1_RED_TITLE = "계약하는 사람과 집주인이 달라요"
R1_RED_ACTION = "대리 계약이라면 위임장과 인감증명서를 확인하고 소유자와 직접 통화하세요. 보증금은 소유자 명의 계좌로만 보내세요."
R1_Y_TITLE = "집주인이 여러 명이에요"
R1_Y_SUMMARY = "이 집은 {n}명이 함께 소유하고 있어요."
R1_Y_ACTION = "다른 소유자들도 이 계약에 동의했는지 확인하세요. 가능하면 소유자 모두와 계약하세요."

R2_TITLE = "집이 신탁회사 소유예요"
R2_SUMMARY = "등기부상 소유권이 {t}에게 넘어가 있어요. 신탁회사 동의 없이 맺은 계약은 보호받기 어려워요."
R2_ACTION = "신탁원부와 신탁회사의 임대 동의서를 요구하세요. 받기 전에는 계약을 미루세요."

R3_TITLE = "집에 압류·경매 같은 제한이 걸려 있어요"
R3_SUMMARY_TAIL = "기록이 있어요. 집이 경매로 넘어가거나 소유자가 바뀔 수 있어요."
R3_ACTION = "이 기록이 말소되기 전에는 계약을 미루세요. 보증보험 가입도 어려울 수 있어요."

R4_RED_TITLE = "이전 세입자가 보증금을 못 돌려받은 기록이 있어요"
R4_RED_SUMMARY = "임차권등기명령은 계약이 끝났는데 보증금을 돌려받지 못한 세입자가 하는 등기예요."
R4_RED_ACTION = "집주인이 보증금을 돌려줄 능력이 있는지 의심해야 해요. 계약을 미루는 걸 권해요."
R4_Y_TITLE = "등기된 다른 임차인이 있어요"
R4_Y_SUMMARY = "{h}의 임차권({a})이 먼저 등기돼 있어요."
R4_Y_ACTION = "이 금액이 내 보증금보다 먼저 돌려받는다는 점을 고려하세요."

R5_TITLE = "보증금이 집값에 비해 위험한 수준이에요"
R5_SUMMARY_TAIL = "경매로 넘어가면 보증금을 다 돌려받지 못할 수 있어요."
R5_ACTION = "보증금을 낮추거나, 전세보증금 반환보증에 가입할 수 있는지 먼저 확인하세요."
R5_DAGAGU_REASON = "다가구는 시세를 추정하기 어려워요"

R6_TITLE = "집에 먼저 잡힌 빚(근저당 등)이 있어요"
R6_SUMMARY = "채권최고액 등 {s}이 내 보증금보다 먼저 돌려받아요."
R6_ACTION = "잔금일에 대출을 갚고 근저당을 말소하는 조건을 특약에 넣거나, 집값에서 이 금액을 빼고도 보증금이 충분히 남는지 확인하세요."

R7_TITLE = "다른 세입자 보증금을 등기부로는 알 수 없어요"
R7_SUMMARY = "이 건물은 한 사람이 통째로 소유해서, 먼저 들어온 세입자들의 보증금이 등기부에 나오지 않아요."
R7_ACTION = "집주인에게 확정일자 부여현황을 요구해 먼저 들어온 보증금 합계를 확인하세요."

R8_TITLE = "최근에 집주인이 바뀌었어요"
R8_SUMMARY_TAIL = "매매와 전세 계약을 동시에 진행하는 수법에서 자주 보이는 패턴이에요."
R8_ACTION = "새 집주인이 이 집을 산 경위와 가격을 확인하세요. 내 보증금으로 집값을 치르는 구조라면 피하세요."

R9_TITLE = "불법 건축물로 등록돼 있어요"
R9_SUMMARY = "건축물대장에 위반건축물 표시가 있어요."
R9_ACTION = "전세대출이나 보증보험이 거절될 수 있어요. 위반 내용과 시정 계획을 확인하세요."

R10_TITLE = "주거용이 아닌 건물로 등록돼 있어요"
R10_SUMMARY_TAIL = "주거용으로 쓰면 불법 용도변경일 수 있어요."
R10_ACTION = "전세대출과 보증보험이 가능한지 먼저 확인하세요."

R11_RED_TITLE = "계약서의 호수가 등기부와 달라요"
R11_RED_TAIL = "전입신고 주소가 등기와 다르면 대항력을 인정받지 못할 수 있어요."
R11_RED_ACTION = "계약서와 전입신고에 등기부 표기를 그대로 적으세요."
R11_Y_TITLE = "계약서 주소가 등기부와 같은지 확인이 필요해요"
R11_Y_SUMMARY = "계약서 주소에서 등기부의 지번이나 도로명을 찾지 못했어요."
R11_Y_ACTION = "계약서 주소를 등기부 주소와 한 글자씩 맞춰 보세요."

R12_TITLE = "보증금을 지키는 특약이 없어요"
R12_SUMMARY = "잔금 전후에 집주인이 새로 대출을 받지 못하게 막는 조항이 계약서에 없어요."
R12_ACTION = "아래 추천 특약을 계약서에 넣어 달라고 요청하세요."

R13_TITLE = "{n}일 전에 뗀 등기부예요"
R13_SUMMARY = "그 사이에 근저당 등이 새로 생겼을 수 있어요."
R13_ACTION = "계약 당일과 잔금 당일에 등기부를 다시 떼어 보세요."

EXCEPTION_REASON = "이 항목을 계산하는 중 문제가 생겼어요"

# PRD 7.3
OV_RED = ("red", "계약 보류 권장", "보증금을 잃을 수 있는 위험 신호가 {n}개 있어요. 해결되기 전에는 계약을 미루는 걸 권해요.")
OV_YELLOW = ("yellow", "추가 확인 필요", "계약 전에 확인할 것이 {n}개 있어요.")
OV_INCOMPLETE = (
    "yellow",
    "확인 미완료",  # PRD v0.5 §7.3
    "위험 신호는 찾지 못했지만, 꼭 확인해야 할 항목 {n}개를 확인하지 못했어요. 빠진 내용을 채운 뒤 다시 검사하세요.",
)
OV_GREEN = (
    "green",
    "큰 위험 신호 없음",
    "확인한 범위에서는 큰 위험 신호를 찾지 못했어요. 안전을 보장하는 것은 아니니 아래 할 일은 꼭 챙기세요.",
)
UNKNOWN_NOTE = "확인하지 못한 항목 {n}개"

# PRD 12.4 (v0.3 changed "☎132" -> "국번 없이 132": PRD.md line 770)
DISCLAIMER = (
    "이 결과는 올려주신 서류와 공개 데이터를 정해진 기준으로 확인한 참고 정보예요. "
    "법률 자문이 아니며 보증금의 안전을 보장하지 않아요. "
    "중요한 결정 전에는 대한법률구조공단(국번 없이 132) 등 전문가와 상의하세요."
)

# PRD 12.2
ST_R12 = "임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다. 위반 시 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다."
ST_R6 = "임대인은 잔금일까지 등기부상 근저당권(채권최고액 {a})을 말소한다."
ST_JEONSE = "임차인이 전세보증금 반환보증에 가입할 수 없는 경우 계약은 무효로 하며, 임대인은 계약금을 즉시 반환한다."
ST_ALWAYS = "임대인은 계약 체결 시 국세·지방세 납세증명서와 확정일자 부여현황을 제시한다."
ST_R2 = "임대인은 잔금일 전까지 수탁자(신탁회사)의 임대 동의서를 제출한다. 제출하지 못하면 임차인은 계약을 해제할 수 있고, 임대인은 받은 금액 전부를 즉시 반환한다."
ST_NOTE = "실제로 쓰기 전에 공인중개사나 대한법률구조공단에 확인하세요."

# PRD 12.1
MSG_HEAD = "안녕하세요. {addr} 임대차 계약 건으로 연락드립니다.\n계약 전에 아래 내용을 확인하고 싶습니다.\n\n"
# v0.3: the long sentence is now one line (PRD.md line 742)
MSG_TAIL = (
    "\n\n확정일자 부여현황과 납세증명서는 계약할 때 임대인이 보여주도록 주택임대차보호법에 정해져 있다고 알고 있습니다.\n"
    "계약일 전에 받아볼 수 있을까요? 감사합니다."
)
MI_ALWAYS = ["확정일자 부여현황", "국세·지방세 납세증명서"]
MI_R2 = ["신탁원부", "신탁회사(수탁자)의 임대 동의서"]
MI_R1 = ["위임장", "인감증명서"]
MI_R6 = ["근저당 대출을 잔금일에 갚고 말소할 계획인지"]

BANNED = ["사기입니다", "안전합니다", "안전한 집", "보장합니다"]  # PRD 10
# v0.3: the disclaimer no longer contains "☎" (PRD.md line 770), so U+260E is no longer exempt.
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⭕]")
# PRD 7.4 공통 (line 464): 주민등록번호 형태 (가려진 것 포함), and the required mask in evidence quotes
RRN_RE = re.compile(r"[0-9*]{6}-[0-9*]{7}")
RRN_MASK = "******-*******"
R1_NAME = "임대인·소유자 불일치"  # v0.3 rename: PRD.md lines 328, 621, 696


def mask_rrn(text: str) -> str:
    """Expected evidence quote per PRD 7.4 공통 (line 464)."""
    return RRN_RE.sub(RRN_MASK, text)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------
def demo(name: str) -> dict:
    return json.loads((DEMO_DIR / f"{name}.json").read_text(encoding="utf-8"))


def p0(d: dict) -> dict:
    """P0-only variant: building/market removed (PRD 11.2 note)."""
    d = copy.deepcopy(d)
    d["building"] = None
    d["market"] = None
    return d


# Every report built by the suite is kept here so test_zz_invariants.py can sweep them.
COLLECTED: list = []


def run(d) -> Report:
    if isinstance(d, CheckRequest):
        req = d
    else:
        req = CheckRequest.model_validate(copy.deepcopy(d))
    rep = build_report(req)
    COLLECTED.append((req, rep))
    return rep


def res(rep: Report, rid: str):
    m = [x for x in rep.results if x.id == rid]
    assert len(m) == 1, f"{rid} appears {len(m)} times in results"
    return m[0]


def lv(d, rid: str) -> str:
    rep = d if isinstance(d, Report) else run(d)
    return res(rep, rid).level


def E(rank, purpose, received_at=None, cause=None, holders=(), amount=None, cancelled=False, page=1, src=None):
    if src is None:
        src = " ".join(x for x in [rank, purpose, received_at or "", cause or "", " ".join(holders)] if x).strip()
    return {
        "rank": rank,
        "purpose": purpose,
        "received_at": received_at,
        "cause": cause,
        "holders": list(holders),
        "amount": amount,
        "is_cancelled": cancelled,
        "page": page,
        "source_text": src,
    }


def won(n: int) -> str:
    """PRD 7.1 금액 표시: 120000000 -> '1억 2,000만 원' (only for multiples of 10,000)."""
    if n == 0:
        return "0원"
    eok, rest = divmod(n, 100_000_000)
    man, rem = divmod(rest, 10_000)
    assert rem == 0, "helper only formats multiples of 10,000"
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    return " ".join(parts) + " 원"


def dre(d) -> str:
    """Regex accepting common Korean renderings of a date (format is not fixed by the PRD)."""
    if isinstance(d, str):
        d = dt.date.fromisoformat(d)
    y, m, dd = d.year, d.month, d.day
    return (
        rf"(?:{y}-{m:02d}-{dd:02d}|{y}\.\s?0?{m}\.\s?0?{dd}\.?|{y}년\s?0?{m}월\s?0?{dd}일|{y}/{m:02d}/{dd:02d})"
    )


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def all_texts(rep: Report) -> list[str]:
    out = [rep.overall.title, rep.overall.message, rep.overall.unknown_note or "", rep.disclaimer]
    for r in rep.results:
        out += [r.name, r.title, r.summary, r.action, r.unknown_reason or ""]
    out.append(rep.request_message or "")
    out += list(rep.special_terms)
    out += [c.title for c in rep.checklist]
    return out


def expected_overall(results) -> tuple[str, str, str, str | None]:
    reds = sum(r.level == "red" for r in results)
    yellows = sum(r.level == "yellow" for r in results)
    core_unknown = sum(r.level == "unknown" and r.id in CORE for r in results)
    unknown = sum(r.level == "unknown" for r in results)
    if reds:
        lvl, t, m = OV_RED
        m = m.format(n=reds)
    elif yellows:
        lvl, t, m = OV_YELLOW
        m = m.format(n=yellows)
    elif core_unknown:
        lvl, t, m = OV_INCOMPLETE
        m = m.format(n=core_unknown)
    else:
        lvl, t, m = OV_GREEN
    note = UNKNOWN_NOTE.format(n=unknown) if unknown else None
    return lvl, t, m, note


def parse_items(msg: str) -> list[tuple[int, str]]:
    items = []
    for ln in (msg or "").split("\n"):
        m = re.match(r"^\s*(\d+)\s*[.)]\s*(.+?)\s*$", ln)
        if m:
            items.append((int(m.group(1)), m.group(2)))
    return items
