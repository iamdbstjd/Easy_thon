"""실거래가로 시세·주변 보증금 찾기 (app/market.py, POST /api/market).

네트워크는 쓰지 않는다. httpx.MockTransport로 주소 API(JSON)와 실거래 API(XML)를 흉내 낸다.
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

from app import main, market
from app.schemas import CheckRequest

TODAY = dt.date(2026, 11, 14)
DEMO_C = Path(__file__).resolve().parent.parent / "demo" / "C.json"


def c_request(**update) -> CheckRequest:
    """예시 C(죽전동 789-1 다세대 302호, 59.82㎡, 전세 1억 8천)를 실제 분석처럼: 시세 없음, live."""
    req = CheckRequest.model_validate_json(DEMO_C.read_bytes())
    return req.model_copy(update={"market": None, "mode": "live", **update})


def item(year=2026, month=10, day=5, **fields) -> dict:
    return {"dealYear": year, "dealMonth": month, "dealDay": day, **fields}


def sale(price_manwon, jibun="789-1", area=59.5, dong="죽전동", **extra) -> dict:
    return item(umdNm=dong, jibun=jibun, mhouseNm="○○파크빌", excluUseAr=area, floor=3,
                dealAmount=f"{price_manwon:,}", **extra)


def rent(deposit_manwon, monthly=0, jibun="789-1", area=59.5, dong="죽전동", **extra) -> dict:
    return item(umdNm=dong, jibun=jibun, mhouseNm="○○파크빌", excluUseAr=area, floor=2,
                deposit=f"{deposit_manwon:,}", monthlyRent=str(monthly), contractType="신규", **extra)


def rtms_xml(items: list[dict], code: str = "000") -> str:
    body = "".join("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in it.items()) + "</item>" for it in items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><response><header>'
        f"<resultCode>{code}</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><items>{body}</items><numOfRows>1000</numOfRows><pageNo>1</pageNo>"
        f"<totalCount>{len(items)}</totalCount></body></response>"
    )


GATEWAY_NOT_REGISTERED = (
    '<?xml version="1.0" encoding="UTF-8"?><OpenAPI_ServiceResponse><cmmMsgHeader>'
    "<errMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</errMsg><returnAuthMsg>등록되지 않은 서비스키</returnAuthMsg>"
    "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
)


def juso_json(jusos: list[dict], code: str = "0") -> dict:
    return {"results": {"common": {"errorCode": code, "errorMessage": "정상", "totalCount": str(len(jusos))},
                        "juso": jusos}}


SUJI_JUKJEON = {"admCd": "4146510200", "siNm": "경기도", "sggNm": "용인시 수지구", "emdNm": "죽전동", "liNm": ""}


class FakeApis:
    """주소 API와 실거래 API를 흉내 낸다. months: {"202610": {"RTMSDataSvcRHTrade": [...], ...}}."""

    def __init__(self, months=None, jusos=(SUJI_JUKJEON,), gateway_error=None, denied=()):
        self.months = months or {}
        self.jusos = list(jusos)
        self.gateway_error = gateway_error
        self.denied = set(denied)  # 활용신청 전인 서비스
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        if request.url.host == "business.juso.go.kr":
            return httpx.Response(200, json=juso_json(self.jusos))
        service = request.url.path.split("/")[2]
        if self.gateway_error or service in self.denied:
            error = self.gateway_error or GATEWAY_NOT_REGISTERED
            return httpx.Response(403, text=error, headers={"content-type": "application/xml"})
        items = self.months.get(params.get("DEAL_YMD"), {}).get(service, [])
        return httpx.Response(200, text=rtms_xml(items), headers={"content-type": "application/xml"})

    def rtms(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == "apis.data.go.kr"]

    def services(self) -> set[str]:
        return {r.url.path.split("/")[2] for r in self.rtms()}


@pytest.fixture
def apis(monkeypatch):
    """가짜 키와 가짜 응답. 캐시는 테스트마다 비운다."""
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "test-data-key")
    monkeypatch.setenv("JUSO_API_KEY", "test-juso-key")
    monkeypatch.setattr(market, "_cache", {})
    monkeypatch.setattr(market, "_region_cache", {})
    fake = FakeApis()
    monkeypatch.setattr(market, "_transport", httpx.MockTransport(fake))
    return fake


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 주소·번지·집 종류
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("경기도 용인시 수지구 죽전동 789-1", ("경기도 용인시 수지구 죽전동", "789-1")),
        ("경기도 용인시 수지구 죽전동 789", ("경기도 용인시 수지구 죽전동", "789")),
        ("경기도 용인시 수지구 죽전동 789-1 ○○파크빌", ("경기도 용인시 수지구 죽전동", "789-1")),
        ("강원특별자치도 평창군 대관령면 횡계리 산 12-3", ("강원특별자치도 평창군 대관령면 횡계리", "산12-3")),
        ("서울특별시 종로구 청운동 0789-01번지", ("서울특별시 종로구 청운동", "789-1")),
        (None, (None, None)),
    ],
)
def test_split_address(address, expected):
    assert market.split_address(address) == expected


def test_normalize_jibun():
    assert market.normalize_jibun("789-0") == "789"
    assert market.normalize_jibun("789-1") == "789-1"
    assert market.normalize_jibun("7**") is None  # 단독·다가구는 번지 일부만 공개된다
    assert market.normalize_jibun("") is None


@pytest.mark.parametrize(
    ("registry_type", "lines", "expected"),
    [
        ("집합건물", ["철근콘크리트구조 15층 아파트"], "아파트"),
        ("집합건물", ["4층 공동주택(다세대주택)"], "연립다세대"),
        ("집합건물", ["10층 업무시설(오피스텔)"], "오피스텔"),
        ("건물", ["3층 다가구주택"], "단독다가구"),
        (None, ["단독주택"], "단독다가구"),
        (None, [], None),
    ],
)
def test_housing_type(registry_type, lines, expected):
    req = c_request()
    registry = req.registry.model_copy(update={"registry_type": registry_type, "building_use_lines": lines})
    assert market.housing_type(registry) == expected


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------


def test_same_building_sets_market_and_rent_stats(apis):
    apis.months = {
        "202610": {
            "RTMSDataSvcRHTrade": [
                sale(31000), sale(33000, day=20),
                sale(99000, cdealType="O"),  # 해제된 거래는 뺀다
                sale(50000, area=120.0),  # 면적이 다르다
                sale(28000, jibun="790"),  # 같은 동 다른 건물
                sale(10000, dong="보정동"),  # 다른 동
            ],
            "RTMSDataSvcRHRent": [rent(20000), rent(22000), rent(1000, monthly=60, jibun="12")],
        },
        "202605": {"RTMSDataSvcRHTrade": [sale(35000, year=2026, month=5)]},
    }
    insight = run(market.lookup(c_request(), TODAY))

    assert insight.status == "ok" and insight.housing_type == "연립다세대"
    assert insight.area_name == "용인시 수지구 죽전동"
    assert insight.period == "2025-12 ~ 2026-11"
    assert insight.market is not None
    assert (insight.market.price, insight.market.method, insight.market.deals) == (330_000_000, "same_building", 3)
    assert insight.market.period == "2025-12 ~ 2026-11"
    assert (insight.sale.low, insight.sale.high) == (310_000_000, 350_000_000)
    assert (insight.jeonse.scope, insight.jeonse.median, insight.jeonse.count) == ("same_building", 210_000_000, 2)
    assert insight.monthly_deposit is None  # 같은 동 월세가 3건이 안 된다
    kinds = [(d.kind, d.same_building) for d in insight.deals]
    assert kinds[:3] == [("sale", True)] * 3 and ("jeonse", True) in kinds
    assert market.NOTE_HIDDEN_UNIT in insight.notes


def test_only_dong_level_address_and_codes_leave_the_server(apis):
    run(market.lookup(c_request(), TODAY))
    (juso,) = [r for r in apis.requests if r.url.host == "business.juso.go.kr"]
    query = parse_qs(urlsplit(str(juso.url)).query)
    assert query["keyword"] == ["경기도 용인시 수지구 죽전동"]  # 번지·건물 이름은 보내지 않는다
    for request in apis.rtms():
        params = parse_qs(urlsplit(str(request.url)).query)
        assert set(params) == {"serviceKey", "LAWD_CD", "DEAL_YMD", "pageNo", "numOfRows"}
        assert params["LAWD_CD"] == ["41465"]
    assert {parse_qs(urlsplit(str(r.url)).query)["DEAL_YMD"][0] for r in apis.rtms()} == set(market._months(TODAY, 36))
    assert apis.services() == {"RTMSDataSvcRHTrade", "RTMSDataSvcRHRent"}


def test_same_dong_three_deals_use_plain_median(apis):
    apis.months = {
        "202610": {
            "RTMSDataSvcRHRent": [rent(15000, jibun="790"), rent(17000, jibun="791"), rent(16000, jibun="792")],
        }
    }
    insight = run(market.lookup(c_request(), TODAY))
    assert (insight.jeonse.scope, insight.jeonse.count, insight.jeonse.median) == ("same_dong", 3, 160_000_000)
    assert insight.jeonse.similar_area is True and insight.jeonse.per_m2 is False
    assert insight.jeonse.period == "2025-12 ~ 2026-11"


def test_two_dong_sales_are_scaled_by_price_per_m2(apis):
    # 같은 건물도 없고 같은 동 비슷한 면적이 3건이 안 되면, 면적 ±30% 2건의 ㎡당 가격으로 이 집(59.82㎡)에 맞춘다
    apis.months = {"202610": {"RTMSDataSvcRHTrade": [sale(30000, jibun="790", area=50.0), sale(32000, jibun="791", area=70.0)]}}
    insight = run(market.lookup(c_request(), TODAY))
    per_m2 = sorted([300_000_000 / 50.0, 320_000_000 / 70.0])
    expected = int(round((per_m2[0] + per_m2[1]) / 2 * 59.82 / 10_000)) * 10_000
    assert (insight.sale.scope, insight.sale.per_m2, insight.sale.count) == ("same_dong", True, 2)
    assert insight.market.price == expected and insight.market.method == "same_dong"
    assert insight.market.period == "2023-12 ~ 2026-11"  # 넓힌 기준은 최근 3년


def test_one_dong_sale_is_not_enough(apis):
    apis.months = {"202610": {"RTMSDataSvcRHTrade": [sale(30000, jibun="790")]}}
    insight = run(market.lookup(c_request(), TODAY))
    assert insight.market is None and insight.sale is None
    assert insight.status == "ok" and len(insight.deals) == 1  # 시세는 못 내도 찾은 거래는 보여 준다


def test_same_building_extends_to_three_years(apis):
    apis.months = {"202503": {"RTMSDataSvcRHTrade": [sale(29000, year=2025, month=3)]}}
    insight = run(market.lookup(c_request(), TODAY))
    assert (insight.market.price, insight.market.method, insight.market.period) == (
        290_000_000, "same_building", "2023-12 ~ 2026-11"
    )
    assert insight.period == "2023-12 ~ 2026-11"


def test_detached_house_shows_neighborhood_deposits_only(apis):
    apis.months = {
        "202610": {
            "RTMSDataSvcSHRent": [
                item(umdNm="죽전동", jibun="7**", houseType="다가구", totalFloorAr=33.1, deposit="1,000", monthlyRent="55"),
                item(umdNm="죽전동", jibun="8**", houseType="다가구", totalFloorAr=40.2, deposit="2,000", monthlyRent="50"),
                item(umdNm="죽전동", jibun="9**", houseType="다가구", totalFloorAr=25.0, deposit="500", monthlyRent="45"),
            ]
        }
    }
    req = c_request()
    req = req.model_copy(update={
        "registry": req.registry.model_copy(update={"registry_type": "건물"}),
        "contract": req.contract.model_copy(update={"lease_type": "월세", "deposit": 10_000_000, "monthly_rent": 500_000}),
    })
    insight = run(market.lookup(req, TODAY))
    assert insight.housing_type == "단독다가구"
    assert apis.services() == {"RTMSDataSvcSHRent"}  # 건물 전체 매매가는 부르지 않는다
    assert insight.market is None
    assert (insight.monthly_deposit.median, insight.monthly_rent.median) == (10_000_000, 500_000)
    assert insight.monthly_deposit.similar_area is False  # 다가구는 면적으로 거르지 않는다
    assert not any(d.same_building for d in insight.deals)
    assert market.NOTE_SH in insight.notes and market.NOTE_SMALL_RENT in insight.notes


def test_korean_field_names_are_read(apis):
    korean = {"년": 2026, "월": 9, "일": 3, "법정동": "죽전동", "지번": "789-1", "연립다세대": "○○파크빌",
              "전용면적": 59.8, "층": 3, "거래금액": "32,000"}
    apis.months = {"202609": {"RTMSDataSvcRHTrade": [korean]}}
    insight = run(market.lookup(c_request(), TODAY))
    assert insight.market.price == 320_000_000 and insight.market.method == "same_building"
    assert insight.deals[0].date == dt.date(2026, 9, 3)


def test_unregistered_key_is_unavailable(apis, caplog):
    caplog.set_level(logging.INFO)
    apis.gateway_error = GATEWAY_NOT_REGISTERED
    insight = run(market.lookup(c_request(), TODAY))
    assert (insight.status, insight.message, insight.market) == ("unavailable", market.UNAVAILABLE, None)
    assert "market rent denied reason=gateway_30" in caplog.text and "market sale denied reason=gateway_30" in caplog.text
    # 주소·키는 로그에 남기지 않는다 (httpx가 남기는 요청 주소 로그도 꺼져 있다)
    assert "죽전" not in caplog.text and "test-data-key" not in caplog.text and "test-juso-key" not in caplog.text


def test_only_rent_api_registered_still_shows_deposits(apis, caplog):
    # 활용신청을 일부만 했을 때: 매매 API는 막혔지만 전월세는 된다
    caplog.set_level(logging.INFO)
    apis.denied = {"RTMSDataSvcRHTrade"}
    apis.months = {"202610": {"RTMSDataSvcRHRent": [rent(20000), rent(22000)]}}
    insight = run(market.lookup(c_request(), TODAY))
    assert insight.status == "ok" and insight.market is None and insight.sale is None
    assert (insight.jeonse.scope, insight.jeonse.median) == ("same_building", 210_000_000)
    assert market.NOTE_NO_SALE_DATA in insight.notes
    assert "market sale denied reason=gateway_30" in caplog.text


def test_only_sale_api_registered_still_sets_market(apis):
    apis.denied = {"RTMSDataSvcRHRent"}
    apis.months = {"202610": {"RTMSDataSvcRHTrade": [sale(31000)]}}
    insight = run(market.lookup(c_request(), TODAY))
    assert insight.status == "ok" and insight.market.price == 310_000_000
    assert insight.jeonse is None and market.NOTE_NO_RENT_DATA in insight.notes


def test_no_keys_makes_no_calls(apis, monkeypatch):
    monkeypatch.delenv("DATA_GO_KR_SERVICE_KEY")
    insight = run(market.lookup(c_request(), TODAY))
    assert insight.status == "unavailable" and apis.requests == []
    assert market.ready() is False


def test_unknown_region(apis):
    apis.jusos = [{**SUJI_JUKJEON, "emdNm": "보정동"}]  # 같은 이름의 동이 없다
    insight = run(market.lookup(c_request(), TODAY))
    assert (insight.status, insight.message) == ("unavailable", market.NO_REGION)
    assert apis.rtms() == []


def test_no_deals(apis):
    insight = run(market.lookup(c_request(), TODAY))
    assert (insight.status, insight.message, insight.deals) == ("no_deals", market.NO_DEALS, [])


def test_months_are_cached(apis):
    run(market.lookup(c_request(), TODAY))
    first = len(apis.requests)
    run(market.lookup(c_request(), TODAY))
    assert len(apis.requests) == first  # 주소·실거래 모두 다시 부르지 않는다


def test_encoded_key_is_decoded(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "abc%2Bdef%3D%3D")
    assert market.data_key() == "abc+def=="


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_market_route_and_check_use_the_found_price(apis):
    apis.months = {"202610": {"RTMSDataSvcRHTrade": [sale(31000), sale(33000), sale(35000)]}}
    client = TestClient(main.app)
    req = c_request(today=TODAY)
    r = client.post("/api/market", json=req.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["market"] == {"price": 330_000_000, "method": "same_building", "deals": 3, "period": "2025-12 ~ 2026-11"}

    # 화면은 찾은 시세를 검사 입력의 market 칸에 넣는다 → R5가 그 값을 쓴다
    checked = client.post("/api/check", json={**req.model_dump(mode="json"), "market": body["market"]})
    r5 = next(x for x in checked.json()["results"] if x["id"] == "R5")
    assert r5["level"] == "green" and "같은 건물 실거래가" in r5["summary"]


def test_market_route_skips_demo(apis):
    client = TestClient(main.app)
    r = client.post("/api/market", json=c_request(mode="demo").model_dump(mode="json"))
    assert r.status_code == 200 and r.json()["status"] == "unavailable"
    assert apis.requests == []


def test_health_reports_public_api_keys(apis):
    assert TestClient(main.app).get("/api/health").json()["public_api_ready"] is True
