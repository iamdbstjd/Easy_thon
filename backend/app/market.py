"""국토교통부 실거래가로 시세와 주변 보증금을 찾는다 (POST /api/market).

- 등기부 주소 → 행정안전부 도로명주소 API로 시군구 코드·법정동 이름 → 국토교통부 실거래가 API로 최근 12개월 매매·전월세.
- 밖으로 보내는 값을 줄인다: 주소 API에는 '시도 시군구 읍면동'까지만 보내고 번지·건물 이름은 보내지 않는다.
  실거래 API에는 시군구 코드와 계약 연월만 보낸다. 같은 건물인지는 받은 거래를 서버에서 번지로 맞춰 본다.
- 고르는 순서 (좁은 기준부터 넓혀 간다. 기간은 최근 1년 → 3년):
  같은 건물(같은 법정동·번지, 면적 ±10%) → 같은 동 면적 ±10% 3건 이상 →
  같은 동 면적 ±30% 2건 이상의 ㎡당 가격 중간값 × 이 집 면적(매매만, 추정). 시세는 매매 값이다.
  단독·다가구는 번지가 일부만 공개되고 매매가가 건물 전체 값이라, 시세는 채우지 않고 주변 보증금만 보여 준다.
- 결과의 market(MarketPrice)은 검사 입력의 market 칸으로 들어가 R5가 쓴다. 판단은 여전히 규칙 엔진이 한다.
  사용자가 시세를 직접 입력하면 그 값이 먼저다 (engine.market_of).
- 실패해도 예외를 내지 않고 status·message로 알린다. 매매·전월세는 따로 받아서, 한쪽 API만 막혀도
  (예: 매매 API 활용신청 전) 되는 쪽은 보여 준다. 로그에는 주소·지역 코드를 남기지 않는다.
- 같은 (서비스, 시군구, 연월) 응답은 6시간 메모리에 둔다. 테스트에서는 _transport를 바꿔 끼운다 (네트워크를 쓰지 않는다).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import re
import statistics
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from typing import Any, Optional
from urllib.parse import unquote

import httpx

from app.schemas import CheckRequest, MarketDeal, MarketInsight, MarketPrice, MarketStats, RegistryExtract

logger = logging.getLogger("app.market")

JUSO_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
RTMS_BASE = "https://apis.data.go.kr/1613000"
# 집 종류 → (매매, 전월세) 서비스 이름. 오퍼레이션 이름은 "get" + 서비스 이름이다.
SERVICES = {
    "아파트": ("RTMSDataSvcAptTrade", "RTMSDataSvcAptRent"),
    "연립다세대": ("RTMSDataSvcRHTrade", "RTMSDataSvcRHRent"),
    "오피스텔": ("RTMSDataSvcOffiTrade", "RTMSDataSvcOffiRent"),
    "단독다가구": ("RTMSDataSvcSHTrade", "RTMSDataSvcSHRent"),
}
MONTHS = 12  # 기본으로 볼 기간 (이번 달 포함)
WINDOWS = (12, 36)  # 거래가 모자라면 넓히는 기간 (개월). 마지막 값만큼 받아 둔다
CALL_TIMEOUT = 5.0  # 호출 하나
TOTAL_TIMEOUT = 12.0  # 조회 전체. 넘으면 불러오지 못한 것으로 본다 (검사는 막지 않는다)
CONCURRENCY = 6
CACHE_SECONDS = 6 * 3600
ROWS = 1000  # 한 번에 받을 거래 수
MAX_PAGES = 3
MAX_BODY_BYTES = 8 * 1024 * 1024
AREA_TOLERANCE = 0.10  # 비슷한 면적: ±10% (작은 집은 최소 ±3㎡)
AREA_MIN_TOLERANCE = 3.0
MIN_DONG_DEALS = 3  # 같은 동 비슷한 면적은 3건 이상일 때만
WIDE_AREA_TOLERANCE = 0.30  # 그래도 모자라면 면적 ±30%까지 넓혀
MIN_WIDE_DEALS = 2  # 2건 이상이면 (매매는 ㎡당 가격으로 이 집 면적에 맞춘다)
SHOWN = {"sale": 3, "main_rent": 4, "other_rent": 2}  # 화면에 보여 줄 거래 수

UNAVAILABLE = "지금은 실거래 정보를 불러오지 못했어요."
NO_REGION = "등기부 주소로 지역을 찾지 못해 실거래를 보지 못했어요."
NO_DEALS = "최근 1년 같은 동에서 비슷한 거래를 찾지 못했어요."
NOTE_HIDDEN_UNIT = "동·호수는 공개되지 않아 같은 건물 거래는 번지로 찾았어요."
NOTE_SH = "단독·다가구는 번지 일부만 공개되고 매매가가 건물 전체 값이라, 시세는 채우지 않고 같은 동 보증금만 보여요."
NOTE_NO_AREA = "면적을 몰라 같은 동의 같은 종류 거래 전체로 봤어요."
NOTE_SMALL_RENT = "보증금이 작은 월세는 신고 대상이 아니어서 빠졌을 수 있어요."
NOTE_NO_SALE_DATA = "매매 실거래를 불러오지 못해 시세는 채우지 않았어요."
NOTE_NO_RENT_DATA = "전월세 실거래를 불러오지 못해 주변 보증금은 보지 못했어요."

_transport: Optional[httpx.AsyncBaseTransport] = None  # 테스트에서 바꿔 끼운다
_cache: dict[tuple[str, str, str], tuple[float, list[dict[str, str]]]] = {}
_region_cache: dict[str, tuple[float, Optional["Region"]]] = {}


class _Denied(Exception):
    """키가 없거나 등록되지 않았다 (다시 불러도 같다)."""


class _Failed(Exception):
    """응답이 비정상이다."""


def data_key() -> Optional[str]:
    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    # 포털의 'Encoding' 키(%2B 등)를 넣었으면 풀어 둔다. httpx가 다시 인코딩한다.
    return (unquote(key) if "%" in key else key) or None


def juso_key() -> Optional[str]:
    return os.environ.get("JUSO_API_KEY", "").strip() or None


def ready() -> bool:
    """/api/health의 public_api_ready: 주소 API와 실거래 API 키가 모두 있는지."""
    return bool(data_key() and juso_key())


# ---------------------------------------------------------------------------
# 주소 → 지역
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Region:
    lawd: str  # 시군구 코드 5자리 (법정동코드 앞 5자리)
    dong: str  # 법정동(읍면동) 이름
    li: str  # 리 이름 (없으면 "")
    name: str  # 화면용: "용인시 수지구 죽전동"


_JIBUN = re.compile(r"^(산\s*)?\d+(-\d+)?(번지)?$")


def split_address(address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """소재지번을 지역과 번지로 나눈다. "경기도 용인시 수지구 죽전동 789-1" → ("경기도 용인시 수지구 죽전동", "789-1")."""
    if not address:
        return None, None
    tokens = address.replace(",", " ").split()
    for i in range(len(tokens) - 1, 0, -1):
        if _JIBUN.match(tokens[i]):
            area = " ".join(tokens[:i])
            if i > 0 and tokens[i - 1] == "산":  # "산 12-3"
                area = " ".join(tokens[: i - 1])
                return area or None, "산" + normalize_jibun(tokens[i])
            return area or None, normalize_jibun(tokens[i])
    return " ".join(tokens) or None, None


def normalize_jibun(text: Optional[str]) -> Optional[str]:
    """"789-0", "789번지", "산 12-03" → "789", "789", "산12-3". 별표로 가린 번지는 None."""
    if not text or "*" in text:
        return None
    t = text.replace(" ", "").replace("번지", "")
    m = re.fullmatch(r"(산)?(\d+)(?:-(\d+))?", t)
    if not m:
        return None
    main, sub = int(m.group(2)), int(m.group(3) or 0)
    return f"{m.group(1) or ''}{main}" + (f"-{sub}" if sub else "")


async def _region(client: httpx.AsyncClient, area: str, key: str) -> Optional[Region]:
    """'시도 시군구 읍면동'으로 주소 API를 불러 시군구 코드와 법정동 이름을 얻는다."""
    hit = _region_cache.get(area)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    r = await client.get(
        JUSO_URL,
        params={"confmKey": key, "currentPage": 1, "countPerPage": 20, "keyword": area, "resultType": "json"},
    )
    if r.status_code != 200:
        raise _Failed(f"juso_http_{r.status_code}")
    try:
        results = r.json()["results"]
        common, jusos = results["common"], results.get("juso") or []
    except (ValueError, KeyError, TypeError):
        raise _Failed("juso_bad_json") from None
    code = str(common.get("errorCode", ""))
    if code != "0":
        raise _Denied(f"juso_{code}") if code in ("E0001", "-999") else _Failed(f"juso_{code}")
    last = area.split()[-1] if area.split() else ""
    pick = next((j for j in jusos if last in (j.get("emdNm"), j.get("liNm"))), None)
    region = None
    if pick and len(str(pick.get("admCd", ""))) >= 5:
        dong, li = str(pick.get("emdNm") or ""), str(pick.get("liNm") or "")
        name = " ".join(p for p in (pick.get("sggNm"), dong, li) if p)
        region = Region(lawd=str(pick["admCd"])[:5], dong=dong, li=li, name=name)
    _region_cache[area] = (time.monotonic(), region)
    return region


# ---------------------------------------------------------------------------
# 실거래 받기
# ---------------------------------------------------------------------------


def _parse(r: httpx.Response) -> ET.Element:
    if len(r.content) > MAX_BODY_BYTES:
        raise _Failed("too_large")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        raise _Failed(f"bad_xml_{r.status_code}") from None
    reason = root.findtext(".//returnReasonCode")  # 게이트웨이 오류 (키 없음·미등록·트래픽 초과 등)
    if reason is not None:
        raise _Denied(f"gateway_{reason}") if reason in ("20", "30", "31", "32", "33") else _Failed(f"gateway_{reason}")
    if r.status_code in (401, 403):
        raise _Denied(f"http_{r.status_code}")
    code = (root.findtext(".//resultCode") or "").strip()
    if code not in ("00", "000", "0"):
        raise _Failed(f"result_{code or r.status_code}")
    return root


async def _month(client: httpx.AsyncClient, service: str, lawd: str, ym: str, key: str) -> list[dict[str, str]]:
    cache_key = (service, lawd, ym)
    hit = _cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    items: list[dict[str, str]] = []
    for page in range(1, MAX_PAGES + 1):
        r = await client.get(
            f"{RTMS_BASE}/{service}/get{service}",
            params={"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym, "pageNo": page, "numOfRows": ROWS},
        )
        root = _parse(r)
        batch = [{child.tag: (child.text or "").strip() for child in item} for item in root.iter("item")]
        items.extend(batch)
        total = int((root.findtext(".//totalCount") or "0").strip() or 0)
        if len(batch) < ROWS or len(items) >= total:
            break
    _cache[cache_key] = (time.monotonic(), items)
    return items


def _months(today: dt.date, count: int = MONTHS) -> list[str]:
    """이번 달부터 거꾸로 count개월 ("202611", "202610", …)."""
    out, y, m = [], today.year, today.month
    for _ in range(count):
        out.append(f"{y:04d}{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


async def _fetch(
    client: httpx.AsyncClient, service: str, lawd: str, months: list[str], key: str, gate: asyncio.Semaphore
) -> tuple[list[dict[str, str]], int]:
    """여러 달을 함께 받는다. 실패한 달 수도 돌려준다. 키 문제(_Denied)는 그대로 올린다."""

    async def one(ym: str) -> list[dict[str, str]]:
        async with gate:
            return await _month(client, service, lawd, ym, key)

    results = await asyncio.gather(*(one(ym) for ym in months), return_exceptions=True)
    items: list[dict[str, str]] = []
    failed = 0
    for result in results:
        if isinstance(result, _Denied):
            raise result
        if isinstance(result, BaseException):
            failed += 1
            continue
        items.extend(result)
    return items, failed


# ---------------------------------------------------------------------------
# 거래 읽기와 고르기
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Deal:
    kind: str  # sale, jeonse, monthly
    date: dt.date
    dong: str
    jibun: Optional[str]
    name: Optional[str]
    floor: Optional[str]
    area: Optional[float]
    price: Optional[int] = None
    deposit: Optional[int] = None
    monthly_rent: Optional[int] = None
    contract_type: Optional[str] = None
    same_building: bool = False


def _first(item: dict[str, str], *names: str) -> Optional[str]:
    for name in names:
        value = item.get(name)
        if value:
            return value.strip()
    return None


def _won(text: Optional[str]) -> Optional[int]:
    """만 원 단위 "82,500" → 825,000,000원."""
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) * 10_000 if digits else None


def _area(text: Optional[str]) -> Optional[float]:
    try:
        value = float((text or "").replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _deal(item: dict[str, str], sale: bool) -> Optional[_Deal]:
    """영문 항목 이름(2024년 이후)과 예전 한글 항목 이름을 모두 읽는다. 해제된 매매는 버린다."""
    try:
        date = dt.date(
            int(_first(item, "dealYear", "년") or ""),
            int(_first(item, "dealMonth", "월") or ""),
            int(_first(item, "dealDay", "일") or ""),
        )
    except ValueError:
        return None
    common: dict[str, Any] = {
        "date": date,
        "dong": _first(item, "umdNm", "법정동") or "",
        "jibun": normalize_jibun(_first(item, "jibun", "지번")),
        "name": _first(item, "aptNm", "mhouseNm", "offiNm", "아파트", "연립다세대", "단지"),
        "floor": _first(item, "floor", "층"),
        "area": _area(_first(item, "excluUseAr", "totalFloorAr", "전용면적", "계약면적", "연면적")),
    }
    if sale:
        if (_first(item, "cdealType", "해제여부") or "").upper() == "O":
            return None
        price = _won(_first(item, "dealAmount", "거래금액"))
        return _Deal(kind="sale", price=price, **common) if price else None
    deposit = _won(_first(item, "deposit", "보증금액", "보증금"))
    rent = _won(_first(item, "monthlyRent", "월세금액", "월세")) or 0
    if deposit is None:
        return None
    return _Deal(
        kind="monthly" if rent > 0 else "jeonse",
        deposit=deposit,
        monthly_rent=rent,
        contract_type=_first(item, "contractType", "계약구분"),
        **common,
    )


def _in_dong(deal: _Deal, region: Region) -> bool:
    names = {region.dong, region.li, f"{region.dong} {region.li}".strip()} - {""}
    return deal.dong in names or (bool(region.li) and deal.dong.endswith(region.li))


def _area_ok(deal: _Deal, area: Optional[float]) -> bool:
    if area is None:
        return True
    return deal.area is not None and abs(deal.area - area) <= max(AREA_MIN_TOLERANCE, area * AREA_TOLERANCE)


@dataclass(frozen=True)
class _Choice:
    """고른 거래 묶음. months: 본 기간, per_m2: ㎡당 가격으로 이 집 면적에 맞춘 추정인지."""

    scope: str
    deals: list[_Deal]
    months: int
    similar_area: bool
    per_m2: bool = False


def _choose(
    deals: list[_Deal], jibun: Optional[str], area: Optional[float], since: dict[int, dt.date], per_m2: bool
) -> tuple[Optional[_Choice], list[_Deal]]:
    """같은 동·같은 종류 거래(deals)에서 좁은 기준부터 넓혀 가며 고른다. 못 고르면 None과 보여 줄 거래."""
    strict = [d for d in deals if _area_ok(d, area)]
    similar = area is not None
    if jibun:
        for months in WINDOWS:
            same = [_with_same(d) for d in strict if d.jibun == jibun and d.date >= since[months]]
            if same:
                return _Choice("same_building", same, months, similar), same
    for months in WINDOWS:
        dong = [d for d in strict if d.date >= since[months]]
        if len(dong) >= MIN_DONG_DEALS:
            return _Choice("same_dong", dong, months, similar), dong
    if area is not None:
        wide = [
            d for d in deals
            if d.date >= since[WINDOWS[-1]] and d.area is not None and abs(d.area - area) <= area * WIDE_AREA_TOLERANCE
        ]
        if len(wide) >= MIN_WIDE_DEALS:
            return _Choice("same_dong", wide, WINDOWS[-1], True, per_m2=per_m2), wide
    recent = [d for d in strict if d.date >= since[WINDOWS[0]]]
    return None, recent or [d for d in strict if d.date >= since[WINDOWS[-1]]]


def _with_same(deal: _Deal) -> _Deal:
    return deal if deal.same_building else replace(deal, same_building=True)


def _round_manwon(value: float) -> int:
    return int(round(value / 10_000)) * 10_000


def _period(months: list[str], count: int) -> str:
    """받아 둔 달 목록(최근 순)에서 최근 count개월 기간: "2025-12 ~ 2026-11"."""
    first, last = months[min(count, len(months)) - 1], months[0]
    return f"{first[:4]}-{first[4:]} ~ {last[:4]}-{last[4:]}"


def _stats(
    choice: Optional[_Choice], value, area: Optional[float], months: list[str]
) -> Optional[MarketStats]:
    """고른 거래의 중간값·범위. per_m2면 거래마다 ㎡당 값을 이 집 면적에 맞춘 값으로 계산한다."""
    if choice is None:
        return None
    if choice.per_m2 and area:
        values = [value(d) / d.area * area for d in choice.deals if value(d) and d.area]
    else:
        values = [value(d) for d in choice.deals if value(d) is not None]
    if not values:
        return None
    return MarketStats(
        scope=choice.scope,  # type: ignore[arg-type]
        similar_area=choice.similar_area,
        per_m2=choice.per_m2,
        period=_period(months, choice.months),
        count=len(values),
        median=_round_manwon(statistics.median(values)),
        low=_round_manwon(min(values)) if choice.per_m2 else int(min(values)),
        high=_round_manwon(max(values)) if choice.per_m2 else int(max(values)),
    )


def _recent(deals: list[_Deal], n: int) -> list[_Deal]:
    return sorted(deals, key=lambda d: (not d.same_building, -d.date.toordinal()))[:n]


def _to_model(deal: _Deal) -> MarketDeal:
    return MarketDeal(
        kind=deal.kind,  # type: ignore[arg-type]
        date=deal.date,
        name=deal.name,
        floor=deal.floor,
        area_m2=deal.area,
        price=deal.price,
        deposit=deal.deposit,
        monthly_rent=deal.monthly_rent,
        contract_type=deal.contract_type,
        same_building=deal.same_building,
    )


def housing_type(registry: RegistryExtract) -> Optional[str]:
    """등기부 종류와 건물내역으로 실거래 자료 종류를 고른다."""
    lines = " ".join(registry.building_use_lines)
    if registry.registry_type == "건물":
        return "단독다가구"
    if "오피스텔" in lines or "업무시설" in lines:
        return "오피스텔"
    if "아파트" in lines:
        return "아파트"
    if "다세대" in lines or "연립" in lines or registry.registry_type == "집합건물":
        return "연립다세대"
    if "다가구" in lines or "단독주택" in lines:
        return "단독다가구"
    return None


def _monthly_lease(req: CheckRequest) -> bool:
    contract = req.contract
    if contract is not None and contract.lease_type is not None:
        return contract.lease_type == "월세"
    rent = (contract.monthly_rent if contract else None) or req.manual.monthly_rent
    return bool(rent and rent > 0)


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------


def _unavailable(message: str = UNAVAILABLE, **kwargs: Any) -> MarketInsight:
    return MarketInsight(status="unavailable", message=message, **kwargs)


async def lookup(req: CheckRequest, today: dt.date) -> MarketInsight:
    """등기부 주소로 최근 12개월 실거래를 찾아 시세(market)와 주변 보증금을 돌려준다. 예외를 내지 않는다."""
    started = time.perf_counter()
    dkey, jkey = data_key(), juso_key()
    kind = housing_type(req.registry)
    if not (dkey and jkey):
        logger.info("market skipped reason=no_key")
        return _unavailable()
    area_text, jibun = split_address(req.registry.address_jibun)
    if not area_text and req.registry.address_road:
        area_text, _ = split_address(req.registry.address_road)
    if not area_text or kind is None:
        logger.info("market skipped reason=%s", "no_address" if not area_text else "unknown_type")
        return _unavailable(NO_REGION if not area_text else UNAVAILABLE, housing_type=kind)

    try:
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT, transport=_transport) as client:
            async with asyncio.timeout(TOTAL_TIMEOUT):
                region = await _region(client, area_text, jkey)
                if region is None:
                    logger.info("market no_region type=%s", kind)
                    return _unavailable(NO_REGION, housing_type=kind)
                months = _months(today, WINDOWS[-1])
                sale_service, rent_service = SERVICES[kind]
                gate = asyncio.Semaphore(CONCURRENCY)
                want_sale = kind != "단독다가구"
                tasks = [_fetch(client, rent_service, region.lawd, months, dkey, gate)]
                if want_sale:
                    tasks.append(_fetch(client, sale_service, region.lawd, months, dkey, gate))
                # 매매·전월세는 따로 본다. 한쪽 API만 막혀도 되는 쪽은 쓴다.
                fetched = await asyncio.gather(*tasks, return_exceptions=True)
    except _Denied as e:  # 주소 API 키 문제
        logger.warning("market denied reason=%s", e)
        return _unavailable(housing_type=kind)
    except (TimeoutError, httpx.HTTPError, _Failed) as e:
        logger.info("market failed reason=%s", type(e).__name__ if not isinstance(e, _Failed) else e)
        return _unavailable(housing_type=kind)

    def usable(result: Any, part: str) -> Optional[list[dict[str, str]]]:
        """받은 거래 목록. 키가 막혔거나 모든 달이 실패했으면 None."""
        if isinstance(result, _Denied):
            logger.warning("market %s denied reason=%s", part, result)
            return None
        if isinstance(result, BaseException):
            logger.info("market %s failed reason=%s", part, type(result).__name__)
            return None
        items, failed = result
        if failed == len(months):
            logger.info("market %s failed reason=all_months", part)
            return None
        return items

    rent_got = usable(fetched[0], "rent")
    sale_got = usable(fetched[1], "sale") if want_sale else None
    if rent_got is None and (not want_sale or sale_got is None):
        return _unavailable(housing_type=kind)
    rent_items, sale_items = rent_got or [], sale_got or []

    area = None if kind == "단독다가구" else req.registry.unit.area_m2
    building_jibun = None if kind == "단독다가구" else jibun

    def in_dong(items: list[dict[str, str]], sale: bool) -> list[_Deal]:
        deals = (_deal(item, sale) for item in items)
        return [d for d in deals if d is not None and _in_dong(d, region)]

    # 기간 시작일: 최근 12개월 → 36개월
    since = {n: dt.date(int(months[n - 1][:4]), int(months[n - 1][4:]), 1) for n in WINDOWS}
    sale_choice, sales = (
        _choose(in_dong(sale_items, True), building_jibun, area, since, per_m2=True) if want_sale else (None, [])
    )
    rents = in_dong(rent_items, False)
    jeonse_choice, jeonse = _choose([d for d in rents if d.kind == "jeonse"], building_jibun, area, since, per_m2=False)
    monthly_choice, monthly = _choose(
        [d for d in rents if d.kind == "monthly"], building_jibun, area, since, per_m2=False
    )

    sale_stats = _stats(sale_choice, lambda d: d.price, area, months)
    market = None
    if sale_stats is not None:
        market = MarketPrice(
            price=sale_stats.median,
            method=sale_stats.scope,  # type: ignore[arg-type]
            deals=sale_stats.count,
            period=sale_stats.period,
        )
    jeonse_stats = _stats(jeonse_choice, lambda d: d.deposit, area, months)
    monthly_deposit = _stats(monthly_choice, lambda d: d.deposit, area, months)
    monthly_rent = _stats(monthly_choice, lambda d: d.monthly_rent or None, area, months)
    used = [c.months for c in (sale_choice, jeonse_choice, monthly_choice) if c is not None]

    is_monthly = _monthly_lease(req)
    main_rent, other_rent = (monthly, jeonse) if is_monthly else (jeonse, monthly)
    shown = (
        _recent(sales, SHOWN["sale"]) + _recent(main_rent, SHOWN["main_rent"]) + _recent(other_rent, SHOWN["other_rent"])
    )
    notes: list[str] = []
    if want_sale and sale_got is None:
        notes.append(NOTE_NO_SALE_DATA)
    if rent_got is None:
        notes.append(NOTE_NO_RENT_DATA)
    if kind == "단독다가구":
        notes.append(NOTE_SH)
    elif any(d.same_building for d in shown):
        notes.append(NOTE_HIDDEN_UNIT)
    if area is None and kind != "단독다가구":
        notes.append(NOTE_NO_AREA)
    if is_monthly:
        notes.append(NOTE_SMALL_RENT)

    found = bool(shown)
    def tag(choice: Optional[_Choice]) -> str:
        return "-" if choice is None else f"{choice.scope}{'/m2' if choice.per_m2 else ''}/{choice.months}m"

    logger.info(
        "market done type=%s sale=%s:%d jeonse=%s:%d monthly=%s:%d took=%.1fs",
        kind, tag(sale_choice), len(sales), tag(jeonse_choice), len(jeonse), tag(monthly_choice), len(monthly),
        time.perf_counter() - started,
    )
    return MarketInsight(
        status="ok" if found else "no_deals",
        message=None if found else NO_DEALS,
        housing_type=kind,  # type: ignore[arg-type]
        area_name=region.name,
        period=_period(months, max(used, default=WINDOWS[0])),
        market=market,
        sale=sale_stats,
        jeonse=jeonse_stats,
        monthly_deposit=monthly_deposit,
        monthly_rent=monthly_rent,
        deals=[_to_model(d) for d in shown],
        notes=notes,
    )
