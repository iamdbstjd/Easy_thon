"""건축물대장(국토교통부 건축HUB)으로 건물·호실 용도를 확인한다 (POST /api/building).

- 등기부 소재지번 → 주소 API(동 이름까지만, market과 같은 캐시)로 법정동 코드 → 건축물대장 표제부(주용도)와
  전유부(호실 용도). 결과(BuildingRegister)는 검사 입력의 building 칸으로 들어가 R10이 쓴다.
- 건축물대장 API에는 시군구·법정동 코드와 번지만 보낸다. 호수는 보내지 않고, 건물 전체 전유부를 받아
  서버에서 내 호실을 찾는다 (한 쪽에 100건, 최대 MAX_PAGES쪽).
- 공개 API에는 위반건축물 표시가 없어 is_violating은 비워 둔다 (R9는 '확인 못 함'과 확인 방법 안내).
- 건축물대장 서버는 가끔 시간 초과(05)나 빈 응답을 낸다. 호출마다 두 번까지 다시 부른다. 실패해도 예외를 내지 않는다.
- 로그에는 주소·번지·코드를 남기지 않는다. 테스트에서는 market._transport를 바꿔 끼운다.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app import market
from app.schemas import BuildingInsight, BuildingRegister, CheckRequest

logger = logging.getLogger("app.building")

BLD_BASE = "https://apis.data.go.kr/1613000/BldRgstHubService"
ROWS = 100  # 한 쪽에 받을 수 있는 최대 건수
MAX_PAGES = 10  # 전유부 최대 쪽 수 (큰 오피스텔도 1,000건까지)
TRIES = 3  # 호출마다 처음 + 두 번 더
RETRY_WAIT = 0.5
CALL_TIMEOUT = 4.0  # 평소에는 1초 안에 답한다. 늦으면 다시 부르는 편이 빠르다
TOTAL_TIMEOUT = 10.0  # 화면은 이 결과를 기다리지 않고, 오면 채운다
CONCURRENCY = 4

UNAVAILABLE = "지금은 건축물대장을 불러오지 못했어요."
NO_JIBUN = "등기부 소재지번에서 번지를 찾지 못해 건축물대장을 보지 못했어요."
NOT_FOUND = "이 번지의 건축물대장을 찾지 못했어요."
NOTE_NO_VIOLATION = "공개 건축물대장 자료에는 위반건축물 표시가 없어요. 정부24나 세움터에서 건축물대장을 떼어 확인하세요."
NOTE_UNIT_NOT_FOUND = "건축물대장에서 이 호실을 찾지 못해 건물 주용도로 봤어요."


@dataclass(frozen=True)
class Lot:
    """건축물대장 조회용 번지: 대지구분(0 대지, 1 산), 본번, 부번."""

    plat: str
    bun: int
    ji: int


def parse_lot(jibun: Optional[str]) -> Optional[Lot]:
    """정리된 번지("789-1", "789", "산12-3") → Lot. 모르면 None."""
    m = re.fullmatch(r"(산)?(\d+)(?:-(\d+))?", jibun or "")
    if not m:
        return None
    return Lot(plat="1" if m.group(1) else "0", bun=int(m.group(2)), ji=int(m.group(3) or 0))


def _ho_number(text: Optional[str]) -> Optional[str]:
    """"302호", "제302호", "302" → "302". 지하는 "B01" 같은 원문을 그대로 비교한다."""
    t = re.sub(r"\s|제|호$", "", (text or "").strip())
    return t.lstrip("0") or t if t else None


def _dong_number(text: Optional[str]) -> Optional[str]:
    m = re.search(r"(\d+)", text or "")
    return m.group(1).lstrip("0") or m.group(1) if m else None


def _use_text(item: dict[str, str]) -> Optional[str]:
    """주용도와 기타 용도를 합친다. 예: "공동주택(다세대주택)", "업무시설(오피스텔)"."""
    main, etc = item.get("mainPurpsCdNm", "").strip(), item.get("etcPurps", "").strip()
    if main and etc and etc != main and etc not in main:
        return f"{main}({etc})"
    return main or etc or None


def _int(text: Optional[str]) -> Optional[int]:
    try:
        value = int((text or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _date(text: Optional[str]) -> Optional[dt.date]:
    t = (text or "").strip()
    if not re.fullmatch(r"\d{8}", t):
        return None
    try:
        value = dt.date(int(t[:4]), int(t[4:6]), int(t[6:]))
    except ValueError:
        return None
    return value if 1900 <= value.year <= 2100 else None


async def _call(
    client: httpx.AsyncClient, op: str, params: dict[str, Any], key: str
) -> tuple[list[dict[str, str]], int]:
    """건축물대장 API 한 번. 시간 초과·빈 응답이면 두 번까지 다시 부른다. 키 문제는 market._Denied."""
    last: Exception = market._Failed("no_try")
    for attempt in range(TRIES):
        if attempt:
            await asyncio.sleep(RETRY_WAIT)
        try:
            r = await client.get(f"{BLD_BASE}/{op}", params={**params, "serviceKey": key})
            root = market._parse(r)
        except market._Denied:
            raise
        except (httpx.HTTPError, market._Failed) as e:
            last = e
            continue
        items = [{child.tag: (child.text or "").strip() for child in item} for item in root.iter("item")]
        total = int((root.findtext(".//totalCount") or "0").strip() or 0)
        return items, total
    raise last


def _pick_title(items: list[dict[str, str]], dong: Optional[str]) -> Optional[dict[str, str]]:
    """표제부가 여러 동이면 내 동, 아니면 주건축물."""
    if not items:
        return None
    want = _dong_number(dong)
    if want:
        for item in items:
            if _dong_number(item.get("dongNm")) == want:
                return item
    return next((i for i in items if i.get("mainAtchGbCdNm") == "주건축물"), items[0])


def _pick_unit(items: list[dict[str, str]], dong: Optional[str], ho: Optional[str]) -> Optional[dict[str, str]]:
    """전유부에서 내 호실의 '전유' 줄. 동을 알면 동도 맞춘다."""
    want_ho, want_dong = _ho_number(ho), _dong_number(dong)
    if not want_ho:
        return None
    rows = [i for i in items if i.get("exposPubuseGbCdNm") == "전유" and _ho_number(i.get("hoNm")) == want_ho]
    if want_dong:
        same = [i for i in rows if _dong_number(i.get("dongNm")) == want_dong]
        rows = same or rows
    return rows[0] if rows else None


async def lookup(req: CheckRequest) -> BuildingInsight:
    """등기부 소재지번으로 건축물대장을 찾아 주용도·호실 용도를 돌려준다. 예외를 내지 않는다."""
    started = time.perf_counter()
    dkey, jkey = market.data_key(), market.juso_key()
    if not (dkey and jkey):
        logger.info("building skipped reason=no_key")
        return BuildingInsight(status="unavailable", message=UNAVAILABLE)
    reg = req.registry
    area_text, jibun = market.split_address(reg.address_jibun)
    lot = parse_lot(jibun)
    if not area_text or lot is None:
        logger.info("building skipped reason=no_jibun")
        return BuildingInsight(status="unavailable", message=NO_JIBUN)

    try:
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT, transport=market._transport) as client:
            async with asyncio.timeout(TOTAL_TIMEOUT):
                region = await market._region(client, area_text, jkey)
                if region is None or len(region.adm) < 10:
                    logger.info("building no_region")
                    return BuildingInsight(status="unavailable", message=market.NO_REGION)
                base = {
                    "sigunguCd": region.adm[:5],
                    "bjdongCd": region.adm[5:10],
                    "platGbCd": lot.plat,
                    "bun": f"{lot.bun:04d}",
                    "ji": f"{lot.ji:04d}",
                    "numOfRows": ROWS,
                    "pageNo": 1,
                }
                titles, _ = await _call(client, "getBrTitleInfo", base, dkey)
                units: list[dict[str, str]] = []
                if reg.registry_type == "집합건물" and _ho_number(reg.unit.ho):
                    first, total = await _call(client, "getBrExposPubuseAreaInfo", base, dkey)
                    units.extend(first)
                    pages = min(MAX_PAGES, -(-total // ROWS)) if total else 1
                    if pages > 1:
                        gate = asyncio.Semaphore(CONCURRENCY)

                        async def page(n: int) -> list[dict[str, str]]:
                            async with gate:
                                items, _ = await _call(client, "getBrExposPubuseAreaInfo", {**base, "pageNo": n}, dkey)
                                return items

                        for items in await asyncio.gather(*(page(n) for n in range(2, pages + 1))):
                            units.extend(items)
    except market._Denied as e:
        logger.warning("building denied reason=%s", e)
        return BuildingInsight(status="unavailable", message=UNAVAILABLE)
    except (TimeoutError, httpx.HTTPError, market._Failed) as e:
        logger.info("building failed reason=%s", e if isinstance(e, market._Failed) else type(e).__name__)
        return BuildingInsight(status="unavailable", message=UNAVAILABLE)

    title = _pick_title(titles, reg.unit.dong)
    if title is None:
        logger.info("building not_found took=%.1fs", time.perf_counter() - started)
        return BuildingInsight(status="not_found", message=NOT_FOUND)

    main_use = _use_text(title)
    unit = _pick_unit(units, reg.unit.dong, reg.unit.ho) if units else None
    unit_use = _use_text(unit) if unit else None
    notes = [NOTE_NO_VIOLATION]
    if reg.registry_type == "집합건물" and _ho_number(reg.unit.ho) and unit is None:
        notes.append(NOTE_UNIT_NOT_FOUND)
    if unit_use:
        source_text = f"건축물대장(국토교통부) {reg.unit.ho or '이 호실'} 전유부 용도: {unit_use}"
    else:
        source_text = f"건축물대장(국토교통부) 주용도: {main_use}" if main_use else None
    building = BuildingRegister(
        main_use=main_use, unit_use=unit_use, is_violating=None, source="api", source_text=source_text
    )
    logger.info(
        "building done unit=%s units_rows=%d took=%.1fs", "found" if unit else "-", len(units), time.perf_counter() - started
    )
    return BuildingInsight(
        status="ok",
        building=building,
        name=title.get("bldNm") or None,
        use_approval_date=_date(title.get("useAprDay")),
        households=_int(title.get("hhldCnt")),
        families=_int(title.get("fmlyCnt")),
        units=_int(title.get("hoCnt")),
        notes=notes,
    )
