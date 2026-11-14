"""건축물대장으로 건물·호실 용도 찾기 (app/building.py, POST /api/building).

네트워크는 쓰지 않는다. httpx.MockTransport로 주소 API(JSON)와 건축물대장 API(XML)를 흉내 낸다.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app import building, main, market
from app.schemas import CheckRequest

DEMO_C = Path(__file__).resolve().parent.parent / "demo" / "C.json"
JUKJEON = {"admCd": "4146510200", "siNm": "경기도", "sggNm": "용인시 수지구", "emdNm": "죽전동", "liNm": ""}

TIMEOUT_05 = (
    '<?xml version="1.0" encoding="UTF-8"?><OpenAPI_ServiceResponse><cmmMsgHeader>'
    "<errMsg>SERVICETIMEOUT_ERROR</errMsg><returnAuthMsg>서비스 연결실패 에러</returnAuthMsg>"
    "<returnReasonCode>05</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
)
NOT_REGISTERED = TIMEOUT_05.replace("SERVICETIMEOUT_ERROR", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR").replace(
    "<returnReasonCode>05", "<returnReasonCode>30"
)


def c_request(**registry_update) -> CheckRequest:
    """예시 C(죽전동 789-1 다세대 302호)를 실제 분석처럼: 건축물대장 없음, live."""
    req = CheckRequest.model_validate_json(DEMO_C.read_bytes())
    registry = req.registry.model_copy(update=registry_update)
    return req.model_copy(update={"registry": registry, "building": None, "market": None, "mode": "live"})


def xml(items: list[dict], total: int | None = None) -> str:
    body = "".join("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in it.items()) + "</item>" for it in items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode>'
        f"<resultMsg>NORMAL SERVICE</resultMsg></header><body><items>{body}</items>"
        f"<numOfRows>100</numOfRows><pageNo>1</pageNo><totalCount>{len(items) if total is None else total}</totalCount>"
        "</body></response>"
    )


TITLE_RH = {"bldNm": "○○파크빌", "mainAtchGbCdNm": "주건축물", "mainPurpsCdNm": "공동주택", "etcPurps": "다세대주택",
            "hhldCnt": "8", "fmlyCnt": "0", "hoCnt": "8", "useAprDay": "20150320"}


def unit(ho, use="공동주택", etc="다세대주택", kind="전유", dong=""):
    return {"dongNm": dong, "hoNm": ho, "exposPubuseGbCdNm": kind, "mainPurpsCdNm": use, "etcPurps": etc}


class FakeBld:
    """op 이름 → 쪽 번호 → 응답 XML. fail_first: op마다 처음 몇 번은 시간 초과(05)."""

    def __init__(self, pages=None, fail_first=0, denied=False):
        self.pages = pages or {}
        self.fail_first = fail_first
        self.denied = denied
        self.requests: list[httpx.Request] = []
        self.calls: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "business.juso.go.kr":
            return httpx.Response(200, json={"results": {"common": {"errorCode": "0"}, "juso": [JUKJEON]}})
        op = request.url.path.rsplit("/", 1)[-1]
        self.calls[op] = self.calls.get(op, 0) + 1
        if self.denied:
            return httpx.Response(403, text=NOT_REGISTERED)
        if self.calls[op] <= self.fail_first:
            return httpx.Response(503, text=TIMEOUT_05)
        page = int(parse_qs(urlsplit(str(request.url)).query).get("pageNo", ["1"])[0])
        return httpx.Response(200, text=self.pages.get(op, {}).get(page, xml([])))

    def bld(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == "apis.data.go.kr"]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "test-data-key")
    monkeypatch.setenv("JUSO_API_KEY", "test-juso-key")
    monkeypatch.setattr(market, "_region_cache", {})
    monkeypatch.setattr(building, "RETRY_WAIT", 0)
    apis = FakeBld()
    monkeypatch.setattr(market, "_transport", httpx.MockTransport(apis))
    return apis


def run(coro):
    return asyncio.run(coro)


def test_parse_lot_and_ho():
    assert building.parse_lot("789-1") == building.Lot("0", 789, 1)
    assert building.parse_lot("789") == building.Lot("0", 789, 0)
    assert building.parse_lot("산12-3") == building.Lot("1", 12, 3)
    assert building.parse_lot(None) is None and building.parse_lot("7**") is None
    assert building._ho_number("제302호") == "302" and building._ho_number("0302") == "302"
    assert building._use_text({"mainPurpsCdNm": "업무시설", "etcPurps": "오피스텔"}) == "업무시설(오피스텔)"
    assert building._use_text({"mainPurpsCdNm": "오피스텔", "etcPurps": "오피스텔"}) == "오피스텔"


def test_unit_use_from_exclusive_part(fake):
    fake.pages = {
        "getBrTitleInfo": {1: xml([TITLE_RH])},
        "getBrExposPubuseAreaInfo": {1: xml([
            unit("301"), unit("302", "제2종근린생활시설", "사무소"), unit("302", kind="공용", etc="계단실"),
        ])},
    }
    insight = run(building.lookup(c_request()))
    assert insight.status == "ok" and insight.name == "○○파크빌"
    b = insight.building
    assert (b.main_use, b.unit_use, b.is_violating, b.source) == (
        "공동주택(다세대주택)", "제2종근린생활시설(사무소)", None, "api"
    )
    assert "302호 전유부 용도: 제2종근린생활시설(사무소)" in b.source_text
    assert (insight.households, insight.units, insight.use_approval_date) == (8, 8, dt.date(2015, 3, 20))
    assert building.NOTE_NO_VIOLATION in insight.notes

    # 검사 입력에 넣으면 R10은 호실 용도로 '주의', R9는 확인 방법을 알려 주는 '확인 못 함'
    client = TestClient(main.app)
    req = c_request()
    report = client.post("/api/check", json={**req.model_dump(mode="json"), "building": b.model_dump(mode="json")}).json()
    rules = {r["id"]: r for r in report["results"]}
    assert rules["R10"]["level"] == "yellow" and "제2종근린생활시설(사무소)" in rules["R10"]["summary"]
    assert rules["R9"]["level"] == "unknown" and "세움터" in rules["R9"]["unknown_reason"]


def test_only_lot_codes_leave_the_server(fake):
    fake.pages = {"getBrTitleInfo": {1: xml([TITLE_RH])}, "getBrExposPubuseAreaInfo": {1: xml([unit("302")])}}
    run(building.lookup(c_request()))
    for request in fake.bld():
        params = parse_qs(urlsplit(str(request.url)).query)
        assert set(params) == {"serviceKey", "sigunguCd", "bjdongCd", "platGbCd", "bun", "ji", "numOfRows", "pageNo"}
        assert (params["sigunguCd"], params["bjdongCd"], params["bun"], params["ji"]) == (
            ["41465"], ["10200"], ["0789"], ["0001"]
        )  # 호수는 보내지 않는다
    (juso,) = [r for r in fake.requests if r.url.host == "business.juso.go.kr"]
    assert parse_qs(urlsplit(str(juso.url)).query)["keyword"] == ["경기도 용인시 수지구 죽전동"]


def test_reads_more_pages_to_find_the_unit(fake):
    filler = [unit(str(100 + i)) for i in range(100)]
    fake.pages = {
        "getBrTitleInfo": {1: xml([TITLE_RH])},
        "getBrExposPubuseAreaInfo": {1: xml(filler, total=250), 2: xml(filler, total=250), 3: xml([unit("302", "업무시설", "오피스텔")], total=250)},
    }
    insight = run(building.lookup(c_request()))
    assert insight.building.unit_use == "업무시설(오피스텔)"
    assert fake.calls["getBrExposPubuseAreaInfo"] == 3


def test_unit_not_found_falls_back_to_main_use(fake):
    fake.pages = {"getBrTitleInfo": {1: xml([TITLE_RH])}, "getBrExposPubuseAreaInfo": {1: xml([unit("301")])}}
    insight = run(building.lookup(c_request()))
    assert insight.building.unit_use is None and insight.building.main_use == "공동주택(다세대주택)"
    assert building.NOTE_UNIT_NOT_FOUND in insight.notes


def test_detached_house_reads_title_only(fake):
    fake.pages = {"getBrTitleInfo": {1: xml([{**TITLE_RH, "mainPurpsCdNm": "단독주택", "etcPurps": "다가구주택",
                                               "hhldCnt": "0", "fmlyCnt": "12", "hoCnt": "0"}])}}
    insight = run(building.lookup(c_request(registry_type="건물")))
    assert insight.building.main_use == "단독주택(다가구주택)" and insight.families == 12
    assert "getBrExposPubuseAreaInfo" not in fake.calls


def test_retries_service_timeouts(fake):
    fake.fail_first = 2  # 두 번 시간 초과 뒤 성공
    fake.pages = {"getBrTitleInfo": {1: xml([TITLE_RH])}, "getBrExposPubuseAreaInfo": {1: xml([unit("302")])}}
    insight = run(building.lookup(c_request()))
    assert insight.status == "ok" and fake.calls["getBrTitleInfo"] == 3


def test_gives_up_after_three_timeouts(fake, caplog):
    caplog.set_level(logging.INFO)
    fake.fail_first = 5
    insight = run(building.lookup(c_request()))
    assert (insight.status, insight.message) == ("unavailable", building.UNAVAILABLE)
    assert fake.calls["getBrTitleInfo"] == 3
    assert "789" not in caplog.text and "test-data-key" not in caplog.text  # 번지·키는 로그에 남기지 않는다


def test_unregistered_key(fake):
    fake.denied = True
    insight = run(building.lookup(c_request()))
    assert insight.status == "unavailable" and fake.calls["getBrTitleInfo"] == 1  # 키 문제는 다시 부르지 않는다


def test_missing_lot_makes_no_calls(fake):
    insight = run(building.lookup(c_request(address_jibun="경기도 용인시 수지구 죽전동")))
    assert (insight.status, insight.message) == ("unavailable", building.NO_JIBUN)
    assert fake.requests == []


def test_not_found(fake):
    fake.pages = {"getBrTitleInfo": {1: xml([])}}
    insight = run(building.lookup(c_request()))
    assert (insight.status, insight.message, insight.building) == ("not_found", building.NOT_FOUND, None)


def test_route_skips_demo_and_reads_live(fake):
    fake.pages = {"getBrTitleInfo": {1: xml([TITLE_RH])}, "getBrExposPubuseAreaInfo": {1: xml([unit("302")])}}
    client = TestClient(main.app)
    demo = client.post("/api/building", json=c_request().model_copy(update={"mode": "demo"}).model_dump(mode="json"))
    assert demo.status_code == 200 and demo.json()["status"] == "unavailable"
    assert fake.requests == []
    live = client.post("/api/building", json=c_request().model_dump(mode="json"))
    assert live.status_code == 200 and live.json()["building"]["unit_use"] == "공동주택(다세대주택)"
