"""app/main.py(라우트·오류 형식·미들웨어), app/ics.py, app/config.py 테스트.

진짜 Anthropic 클라이언트는 만들지 않는다 (가짜 클라이언트만 쓴다, 네트워크 없음).
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import io
import json
import logging
import os
import re
import time
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from starlette.formparsers import MultiPartParser

from app import config, extract, ics, main, privacy, prompts, uploads
from app.errors import ERROR_MESSAGES
from app.schemas import (
    RULE_NAMES,
    CheckRequest,
    ContractExtract,
    Counts,
    IcsRequest,
    Overall,
    RecheckChange,
    RecheckReport,
    RecheckRequest,
    RegistryExtract,
    Report,
    RuleResult,
    TermCheck,
)

# ---------------------------------------------------------------------------
# 공용 도구 (tests/test_extract.py와 같은 모양의 가짜 클라이언트)
# ---------------------------------------------------------------------------

REGISTRY_OK = {
    "is_registry": True,
    "registry_type": "집합건물",
    "viewed_at": "2026-11-14T10:31:22+09:00",
    "address_jibun": "경기도 용인시 수지구 죽전동 123-4",
    "address_road": "경기도 용인시 수지구 죽전로 12",
    "building_name": "죽전빌라",
    "unit": {"dong": None, "ho": "302호", "floor": "3층", "area_m2": 59.94},
    "building_use_lines": ["철근콘크리트구조 철근콘크리트지붕 4층 다세대주택", "3층 다세대주택 130.2㎡"],
    "gapgu": [
        {
            "page": 1,
            "source_text": "2 소유권이전 2019년5월10일 제1234호 2019년4월1일 매매 소유자 김민수 800101-*******",
            "rank": "2",
            "purpose": "소유권이전",
            "received_at": "2019-05-10",
            "cause": "매매",
            "holders": ["김민수"],
            "amount": None,
            "is_cancelled": False,
        }
    ],
    "eulgu": [],
    "unreadable": [],
}

CONTRACT_OK = {
    "is_contract": True,
    "landlord_names": ["김민수"],
    "agent_name": None,
    "address": "경기도 용인시 수지구 죽전동 123-4 죽전빌라 302호",
    "unit": {"dong": None, "ho": "302호"},
    "lease_type": "월세",
    "deposit": 10000000,
    "monthly_rent": 450000,
    "contract_date": "2026-11-14",
    "balance_date": "2026-12-01",
    "move_in_date": "2026-12-01",
    "lease_end": "2028-11-30",
    "special_terms": ["임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다."],
    "sources": {
        "landlord": "임대인 성명 김민수",
        "address": "소재지 경기도 용인시 수지구 죽전동 123-4 죽전빌라 302호",
        "deposit": "보증금 금 일천만원정 (₩10,000,000)",
        "special_terms": "1. 임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다.",
    },
}

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
KST = dt.timezone(dt.timedelta(hours=9))

# 사용자에게 보여 줄 오류 문구
EXPECTED_MESSAGES = {
    "UNSUPPORTED_FILE": "등기부는 PDF, 계약서는 사진이나 PDF로 10MB 이하만 올릴 수 있어요.",
    "NOT_REGISTRY": "등기부등본이 아닌 것 같아요. 인터넷등기소에서 받은 PDF를 올려주세요.",
    "LAND_REGISTRY": "토지 등기부예요. 건물(또는 집합건물) 등기부를 올려주세요.",
    "NOT_CONTRACT": "임대차 계약서가 아닌 것 같아요.",
    "AI_FAILED": "문서를 읽지 못했어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.",
    "NOT_FOUND": "예시 데이터를 찾지 못했어요. 예시는 A, B, C예요.",
    "INTERNAL_ERROR": "일시적인 오류가 생겼어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.",
}


def make_response(payload=None, *, stop_reason="end_turn", text=None):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    if text is None and payload is not None:
        text = json.dumps(payload, ensure_ascii=False)
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        model=extract.MODEL,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
    )


def doc_kind(kwargs) -> str:
    schema = kwargs["output_config"]["format"]["schema"]
    return "registry" if schema is prompts.REGISTRY_SCHEMA else "contract"


class FakeMessages:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.handler(kwargs, len(self.calls))
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, BaseException):
            raise result
        return result


class FakeClient:
    def __init__(self, handler):
        self.messages = FakeMessages(handler)
        self.beta = SimpleNamespace(messages=self.messages)
        self.closed = False

    async def close(self):
        self.closed = True


def responder(registry=None, contract=None):
    queues = {"registry": registry, "contract": contract}

    def handler(kwargs, _n):
        item = queues[doc_kind(kwargs)]
        if isinstance(item, list):
            item = item.pop(0)
        return item

    return handler


def install_ai(monkeypatch, registry=None, contract=None) -> FakeClient:
    fake = FakeClient(responder(registry, contract))
    monkeypatch.setattr(extract, "_client", fake)
    return fake


def make_pdf(pages=1, *, user_password=None, owner_password=None, algorithm="RC4-128") -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if user_password is not None or owner_password is not None:
        writer.encrypt(user_password=user_password or "", owner_password=owner_password, algorithm=algorithm)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def registry_file(data=None, name="registry.pdf", content_type="application/pdf"):
    return {"registry": (name, make_pdf(2) if data is None else data, content_type)}


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json() == {"error": {"code": code, "message": ERROR_MESSAGES[code]}}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """API 키를 지우고, 진짜 클라이언트를 만들려고 하면 실패하게 한다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("EXTRACT_DEADLINE_SECONDS", raising=False)
    monkeypatch.setattr(extract, "_client", None)

    def _forbidden(*args, **kwargs):
        raise AssertionError("tests must not create a real Anthropic client")

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _forbidden)

    async def no_wait(seconds):  # 재시도 전 대기를 건너뛴다
        return None

    monkeypatch.setattr(extract, "_sleep", no_wait)


@pytest.fixture
def client():
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# 오류 형식
# ---------------------------------------------------------------------------


def test_error_messages_match_prd():
    for code, message in EXPECTED_MESSAGES.items():
        assert ERROR_MESSAGES[code] == message


def test_openapi_schema_builds(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/api/extract",
        "/api/check",
        "/api/demo/{scenario}",
        "/api/health",
        "/api/checklist.ics",
        "/api/recheck",
        "/api/demo/recheck-A",
    } <= set(paths)


# ---------------------------------------------------------------------------
# 주민등록번호 가리기
# ---------------------------------------------------------------------------

# 응답 JSON에 가려지지 않은 주민등록번호 앞자리(숫자 6개)가 남았는지 찾는다
UNMASKED_ID = re.compile(r"(?<!\d)\d{6}\s*[-‐‑‒–—−－]\s*[\d*＊∗xX○◯〇●]{7}(?!\d)")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("소유자 정○○ 620830-******* 경기도", "소유자 정○○ ******-******* 경기도"),
        ("정○○620830-*******", "정○○******-*******"),  # 이름 바로 뒤에 붙어 있어도
        ("620830 - 1234567", "******-*******"),
        ("620830-1●●●●●● / 620830-1○○○○○○", "******-******* / ******-*******"),
        ("620830-1xxxxxx / 6208XX-XXXXXXX", "******-******* / ******-*******"),
        ("620830-1＊＊＊＊＊＊", "******-*******"),
        ("620830－1234567, 620830–1234567", "******-*******, ******-*******"),  # 전각 하이픈, 대시
        ("근저당권자 주식회사○○은행 110111-*******", "근저당권자 주식회사○○은행 ******-*******"),  # 법인등록번호
    ],
)
def test_mask_text_hides_resident_ids(text, expected):
    assert privacy.mask_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "2026-11-14",
        "2026-11-14T09:12:41+09:00",
        "010-1234-5678",
        "031-123-4567",
        "경기도 용인시 수지구 죽전동 123-4",
        "산12-3",
        "고유번호 1234-2015-001234",
        "신탁원부 제2026-5678호",
        "제12345호",
        "금120,000,000원 (₩10,000,000)",
        "계좌 123-456789-12345",
        "사업자 123-45-67890",
        "기간 20261114-20281130",
        "2025-12 ~ 2026-11",
        "1234567-1234567",
        "620830-12345678",
    ],
)
def test_mask_text_leaves_other_numbers_alone(text):
    assert privacy.mask_text(text) == text


def test_extract_response_masks_ids_in_every_field(client, monkeypatch):
    registry = {
        **REGISTRY_OK,
        "gapgu": [
            {
                **REGISTRY_OK["gapgu"][0],
                "source_text": "2 소유권이전 2019년5월10일 제1234호 2019년4월1일 매매 소유자 김민수 800101-1234567 경기도",
                "holders": ["김민수 800101-1******"],
            }
        ],
        "eulgu": [
            {
                "page": 2,
                "source_text": "1 근저당권설정 2020년1월2일 제5678호 채권최고액 금120,000,000원 근저당권자 주식회사○○은행 110111-＊＊＊＊＊＊＊",
                "rank": "1",
                "purpose": "근저당권설정",
                "received_at": "2020-01-02",
                "cause": "설정계약",
                "holders": ["주식회사○○은행"],
                "amount": 120000000,
                "is_cancelled": False,
            }
        ],
        "unreadable": ["2쪽 620830-1xxxxxx 옆 글자가 흐림"],
    }
    contract = {
        **CONTRACT_OK,
        "landlord_names": ["김민수(800101-1●●●●●●)"],
        "special_terms": ["연락처 010-1234-5678, 계좌 123-456789-12345", "임대인 주민번호 800101－1234567 확인"],
        "sources": {**CONTRACT_OK["sources"], "landlord": "임대인 성명 김민수 주민등록번호 800101 - 1○○○○○○ 주소 서울"},
    }
    install_ai(monkeypatch, registry=make_response(registry), contract=make_response(contract))
    r = client.post("/api/extract", files={**registry_file(), "contract": ("c.png", PNG, "image/png")})
    assert r.status_code == 200, r.text

    assert UNMASKED_ID.search(r.text) is None
    for half in ("800101", "620830", "110111"):
        assert half not in r.text
    body = r.json()
    reg, con = body["registry"], body["contract"]
    assert reg["gapgu"][0]["source_text"].endswith("소유자 김민수 ******-******* 경기도")
    assert reg["gapgu"][0]["holders"] == ["김민수 ******-*******"]
    assert reg["eulgu"][0]["source_text"].endswith("근저당권자 주식회사○○은행 ******-*******")
    assert reg["unreadable"] == ["2쪽 ******-******* 옆 글자가 흐림"]
    assert con["landlord_names"] == ["김민수(******-*******)"]
    assert con["sources"]["landlord"] == "임대인 성명 김민수 주민등록번호 ******-******* 주소 서울"
    assert con["special_terms"] == ["연락처 010-1234-5678, 계좌 123-456789-12345", "임대인 주민번호 ******-******* 확인"]
    # 날짜·금액·지번·전화번호는 그대로
    assert reg["address_jibun"] == "경기도 용인시 수지구 죽전동 123-4"
    assert reg["eulgu"][0]["received_at"] == "2020-01-02" and reg["eulgu"][0]["amount"] == 120000000
    assert reg["viewed_at"] == "2026-11-14T10:31:22+09:00"
    assert con["deposit"] == 10000000 and con["contract_date"] == "2026-11-14"
    assert con["sources"]["deposit"] == "보증금 금 일천만원정 (₩10,000,000)"


@pytest.mark.parametrize("scenario", ["A", "B", "C"])
def test_real_demo_files_return_no_unmasked_ids(client, scenario):
    if not (config.BACKEND_DIR / "demo" / f"{scenario}.json").is_file():
        pytest.skip("데모 파일이 아직 없다")
    r = client.get(f"/api/demo/{scenario}")
    assert r.status_code == 200, r.text
    assert UNMASKED_ID.search(r.text) is None
    for half in ("620830", "900101", "110111", "620514", "850315", "550720", "780412"):
        assert half not in r.text
    CheckRequest.model_validate(r.json())


# ---------------------------------------------------------------------------
# POST /api/extract
# ---------------------------------------------------------------------------


def test_extract_registry_only(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    pdf = make_pdf(3)
    r = client.post("/api/extract", files=registry_file(pdf))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contract"] is None
    expected = RegistryExtract.model_validate(REGISTRY_OK).model_dump(mode="json")
    expected["gapgu"][0]["source_text"] = expected["gapgu"][0]["source_text"].replace("800101-*******", "******-*******")
    assert body["registry"] == expected  # 주민등록번호 앞자리만 가리고 나머지는 그대로
    assert body["registry"]["viewed_at"] == "2026-11-14T10:31:22+09:00"
    (kwargs,) = fake.messages.calls
    assert doc_kind(kwargs) == "registry"
    assert kwargs["messages"][0]["content"][0]["source"]["data"] == base64.b64encode(pdf).decode()


def test_extract_registry_and_contract_photo(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK), contract=make_response(CONTRACT_OK))
    r = client.post(
        "/api/extract",
        files={**registry_file(), "contract": ("contract.jpg", JPEG, "image/jpeg")},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contract"] == ContractExtract.model_validate(CONTRACT_OK).model_dump(mode="json")
    assert body["registry"]["building_name"] == "죽전빌라"
    assert sorted(doc_kind(c) for c in fake.messages.calls) == ["contract", "registry"]
    contract_call = next(c for c in fake.messages.calls if doc_kind(c) == "contract")
    image = contract_call["messages"][0]["content"][0]
    assert image["type"] == "image"
    assert image["source"]["media_type"] == "image/jpeg"
    assert image["source"]["data"] == base64.b64encode(JPEG).decode()


def test_extract_contract_pdf_uses_document_block(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK), contract=make_response(CONTRACT_OK))
    r = client.post("/api/extract", files={**registry_file(), "contract": ("c.pdf", make_pdf(1), "application/pdf")})
    assert r.status_code == 200, r.text
    contract_call = next(c for c in fake.messages.calls if doc_kind(c) == "contract")
    assert contract_call["messages"][0]["content"][0]["type"] == "document"


def test_blank_contract_field_is_ignored(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    r = client.post("/api/extract", files={**registry_file(), "contract": ("", b"", "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["contract"] is None
    assert len(fake.messages.calls) == 1


def test_extract_max_tokens_retry(client, monkeypatch):
    truncated = make_response(None, stop_reason="max_tokens", text='{"is_reg')
    fake = install_ai(monkeypatch, registry=[truncated, make_response(REGISTRY_OK)])
    r = client.post("/api/extract", files=registry_file())
    assert r.status_code == 200, r.text
    assert [c["max_tokens"] for c in fake.messages.calls] == [16000, 32000]


@pytest.mark.parametrize(
    "resp",
    [
        make_response(None, stop_reason="refusal"),
        make_response(None, text="not json at all"),
        make_response(None, text='{"is_registry": true, "extra": 1}'),
    ],
    ids=["refusal", "invalid-json", "schema-mismatch"],
)
def test_extract_ai_failures_are_502(client, monkeypatch, resp):
    install_ai(monkeypatch, registry=resp)
    assert_error(client.post("/api/extract", files=registry_file()), 502, "AI_FAILED")


def test_extract_sdk_error_is_502(client, monkeypatch):
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    fake = install_ai(monkeypatch, registry=anthropic.APITimeoutError(request=request))
    assert_error(client.post("/api/extract", files=registry_file()), 502, "AI_FAILED")
    assert len(fake.messages.calls) == 2  # 일시적 오류는 한 번 다시 부른 뒤 실패


def test_extract_retries_transient_error_once(client, monkeypatch):
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    overloaded = anthropic.APIStatusError("overloaded", response=httpx2.Response(529, request=request), body=None)
    bad = anthropic.BadRequestError("bad", response=httpx2.Response(400, request=request), body=None)
    fake = install_ai(
        monkeypatch,
        registry=[overloaded, make_response(REGISTRY_OK)],
        contract=[bad, make_response(CONTRACT_OK)],
    )
    r = client.post("/api/extract", files={**registry_file(), "contract": ("c.png", PNG, "image/png")})
    assert_error(r, 502, "AI_FAILED")  # 계약서 400은 다시 부르지 않는다
    assert sorted(doc_kind(c) for c in fake.messages.calls) == ["contract", "registry", "registry"]

    fake = install_ai(monkeypatch, registry=[overloaded, make_response(REGISTRY_OK)])
    r = client.post("/api/extract", files=registry_file())
    assert r.status_code == 200, r.text  # 529 뒤 다시 불러 성공
    assert len(fake.messages.calls) == 2


def test_extract_not_registry(client, monkeypatch):
    install_ai(monkeypatch, registry=make_response({**REGISTRY_OK, "is_registry": False}))
    assert_error(client.post("/api/extract", files=registry_file()), 422, "NOT_REGISTRY")


def test_extract_land_registry(client, monkeypatch):
    install_ai(monkeypatch, registry=make_response({**REGISTRY_OK, "registry_type": "토지"}))
    assert_error(client.post("/api/extract", files=registry_file()), 422, "LAND_REGISTRY")


def test_extract_not_contract(client, monkeypatch):
    install_ai(
        monkeypatch,
        registry=make_response(REGISTRY_OK),
        contract=make_response({**CONTRACT_OK, "is_contract": False}),
    )
    r = client.post("/api/extract", files={**registry_file(), "contract": ("c.png", PNG, "image/png")})
    assert_error(r, 422, "NOT_CONTRACT")


@pytest.mark.parametrize(
    "files",
    [
        registry_file(PNG, name="looks.pdf"),  # 확장자·Content-Type이 PDF여도 내용으로 판단한다
        registry_file(b"hello", name="a.txt", content_type="text/plain"),
        registry_file(b""),
        registry_file(b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024)),  # 10MB 초과
        registry_file(make_pdf(31)),  # 30쪽 초과
        registry_file(make_pdf(1, user_password="secret")),  # 열람 암호 (RC4)
        registry_file(make_pdf(1, user_password="secret", owner_password="o", algorithm="AES-256")),  # 열람 암호 (AES)
        {**registry_file(), "contract": ("c.gif", b"GIF89a" + b"\x00" * 32, "image/gif")},
        {**registry_file(), "contract": ("c.txt", b"just text", "text/plain")},
        {**registry_file(), "contract": ("c.pdf", make_pdf(31), "application/pdf")},
    ],
    ids=["png-as-pdf", "text", "empty", "over-10mb", "31-pages", "user-password-rc4", "user-password-aes256",
         "contract-gif", "contract-text", "contract-31-pages"],
)
def test_extract_unsupported_files(client, monkeypatch, files):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK), contract=make_response(CONTRACT_OK))
    assert_error(client.post("/api/extract", files=files), 400, "UNSUPPORTED_FILE")
    assert fake.messages.calls == []  # 파일이 틀리면 AI를 부르지 않는다


@pytest.mark.parametrize("algorithm", ["AES-256", "RC4-128"])
def test_extract_accepts_owner_password_only_pdf(client, monkeypatch, algorithm):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK), contract=make_response(CONTRACT_OK))
    encrypted = make_pdf(3, owner_password="owner", algorithm=algorithm)
    assert PdfReader(io.BytesIO(encrypted)).is_encrypted
    r = client.post(
        "/api/extract",
        files={**registry_file(encrypted), "contract": ("c.pdf", encrypted, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert len(fake.messages.calls) == 2
    for call in fake.messages.calls:  # Claude에는 암호를 푼 사본을 보낸다
        sent = base64.b64decode(call["messages"][0]["content"][0]["source"]["data"])
        assert sent != encrypted
        reader = PdfReader(io.BytesIO(sent))
        assert reader.is_encrypted is False
        assert len(reader.pages) == 3


def test_extract_deadline_is_502(client, monkeypatch):
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "0.2")

    async def slow(kwargs):
        await asyncio.sleep(10)
        return make_response(REGISTRY_OK)

    fake = FakeClient(lambda kwargs, _n: slow(kwargs))
    monkeypatch.setattr(extract, "_client", fake)
    started = time.perf_counter()
    r = client.post("/api/extract", files={**registry_file(), "contract": ("c.png", PNG, "image/png")})
    assert_error(r, 502, "AI_FAILED")
    assert time.perf_counter() - started < 3  # 10초를 기다리지 않는다


def test_extract_missing_registry_is_unsupported_file(client):
    assert_error(client.post("/api/extract"), 400, "UNSUPPORTED_FILE")
    assert_error(client.post("/api/extract", data={"registry": "not a file"}), 400, "UNSUPPORTED_FILE")


def test_extract_request_too_large_is_rejected_before_parsing(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    huge = b"%PDF" + b"0" * (uploads.MAX_REQUEST_BYTES + 1)
    r = client.post("/api/extract", files=registry_file(huge))
    assert_error(r, 400, "UNSUPPORTED_FILE")
    assert r.headers["x-request-id"]
    assert fake.messages.calls == []


def multipart_body(filename: str, data: bytes, boundary: str = "testboundary") -> tuple[bytes, dict]:
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="registry"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), {
        "content-type": f"multipart/form-data; boundary={boundary}"
    }


def test_extract_chunked_body_over_cap_is_rejected(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    body, headers = multipart_body("big.pdf", b"%PDF-" + b"0" * (uploads.MAX_REQUEST_BYTES + 10))

    def chunks():  # 길이를 모르는 본문 → Transfer-Encoding: chunked, Content-Length 없음
        for i in range(0, len(body), 1024 * 1024):
            yield body[i : i + 1024 * 1024]

    r = client.post("/api/extract", content=chunks(), headers=headers)
    assert_error(r, 400, "UNSUPPORTED_FILE")
    assert fake.messages.calls == []


def run_asgi(scope_headers: list, receive, timeout: float = 5.0):
    """앱을 ASGI로 직접 부른다 (TestClient는 본문을 한 번에 넘겨 조각 단위 동작을 볼 수 없다)."""
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/extract",
        "raw_path": b"/api/extract",
        "query_string": b"",
        "root_path": "",
        "headers": scope_headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    asyncio.run(asyncio.wait_for(main.app(scope, receive, send), timeout))
    return sent


def test_middleware_stops_reading_chunked_body_at_cap(monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    chunk = b"0" * (1024 * 1024)
    received = []

    async def receive():  # 60MB를 1MB씩 보내는 chunked 업로드
        received.append(len(chunk))
        return {"type": "http.request", "body": chunk, "more_body": len(received) < 60}

    sent = run_asgi([(b"content-type", b"multipart/form-data; boundary=x"), (b"transfer-encoding", b"chunked")], receive)
    assert sent[0]["status"] == 400
    assert json.loads(sent[1]["body"]) == {"error": {"code": "UNSUPPORTED_FILE", "message": ERROR_MESSAGES["UNSUPPORTED_FILE"]}}
    assert sum(received) <= uploads.MAX_REQUEST_BYTES + len(chunk)  # 상한을 넘자마자 읽기를 멈췄다
    assert fake.messages.calls == []


def test_client_disconnect_during_upload_sends_nothing(monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    messages = [{"type": "http.request", "body": b"--x\r\n", "more_body": True}, {"type": "http.disconnect"}]

    async def receive():
        return messages.pop(0)

    assert run_asgi([(b"content-type", b"multipart/form-data; boundary=x")], receive) == []
    assert fake.messages.calls == []


def test_client_disconnect_cancels_claude_calls(monkeypatch):
    monkeypatch.setattr(main, "DISCONNECT_POLL_SECONDS", 0.05)
    cancelled = []

    async def slow(kwargs):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(doc_kind(kwargs))
            raise
        return make_response(REGISTRY_OK)

    monkeypatch.setattr(extract, "_client", FakeClient(lambda kwargs, _n: slow(kwargs)))
    body, headers = multipart_body("registry.pdf", make_pdf(1))
    state = {"sent_body": False, "disconnect_at": None}

    async def receive():
        loop = asyncio.get_running_loop()
        if not state["sent_body"]:
            state["sent_body"], state["disconnect_at"] = True, loop.time() + 0.3
            return {"type": "http.request", "body": body, "more_body": False}
        delay = state["disconnect_at"] - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)  # 0.3초 뒤 사용자가 화면을 닫는다
        return {"type": "http.disconnect"}

    started = time.perf_counter()
    run_asgi([(b"content-type", headers["content-type"].encode()), (b"content-length", str(len(body)).encode())], receive)
    assert time.perf_counter() - started < 3  # 마감(85초)까지 기다리지 않는다
    assert cancelled == ["registry"]


def test_extract_accepts_pdf_with_leading_bytes(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    pdf = make_pdf(1)
    r = client.post("/api/extract", files=registry_file(b"\xef\xbb\xbfjunk\r\n" + pdf))
    assert r.status_code == 200, r.text
    sent = base64.b64decode(fake.messages.calls[0]["messages"][0]["content"][0]["source"]["data"])
    assert sent == pdf  # 헤더("%PDF-")부터 보낸다


def test_extract_without_api_key_is_503(client):
    # autouse 픽스처가 키를 지웠고, 클라이언트를 만들면 AssertionError가 난다 (→ 500으로 실패)
    assert_error(client.post("/api/extract", files=registry_file()), 503, "AI_FAILED")


def test_file_validation_runs_before_api_key_check(client):
    assert_error(client.post("/api/extract", files=registry_file(PNG)), 400, "UNSUPPORTED_FILE")


def test_uploads_stay_in_memory():
    # Starlette 기본값(1MB)이면 큰 파일이 디스크 임시 파일로 넘어간다
    assert MultiPartParser.spool_max_size >= uploads.MAX_REQUEST_BYTES


def test_extract_logs_have_no_personal_data(client, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    install_ai(monkeypatch, registry=make_response(REGISTRY_OK), contract=make_response(CONTRACT_OK))
    r = client.post(
        "/api/extract",
        files={**registry_file(name="김민수_등기부.pdf"), "contract": ("김민수_계약서.jpg", JPEG, "image/jpeg")},
    )
    assert r.status_code == 200
    bad = json.dumps({**REGISTRY_OK, "owner": "김민수"}, ensure_ascii=False)
    install_ai(monkeypatch, registry=make_response(None, text=bad))
    assert client.post("/api/extract", files=registry_file()).status_code == 502
    assert "POST /api/extract -> 200" in caplog.text
    for secret in ("김민수", "죽전", "800101", "일천만원"):
        assert secret not in caplog.text


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------


def test_health_without_key(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ai_ready": False, "public_api_ready": False}
    assert r.headers["x-request-id"]


@pytest.mark.parametrize("env_name", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_health_with_key(client, monkeypatch, env_name):
    monkeypatch.setenv(env_name, "test-key")
    assert client.get("/api/health").json() == {"ai_ready": True, "public_api_ready": False}


# ---------------------------------------------------------------------------
# GET /api/demo/{scenario}
# ---------------------------------------------------------------------------

DEMO_FIXTURE = {
    "registry": REGISTRY_OK,
    "contract": CONTRACT_OK,
    "manual": {},
    "building": {"main_use": "다세대주택", "unit_use": "다세대주택", "is_violating": False, "source": "api"},
    "market": {"price": 200000000, "method": "same_building", "deals": 3, "period": "2025-12 ~ 2026-11"},
    "today": "2026-11-14",
}


@pytest.fixture
def demo_dir(tmp_path, monkeypatch):
    (tmp_path / "A.json").write_text(json.dumps(DEMO_FIXTURE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main, "DEMO_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize("scenario", ["A", "a"])
def test_demo_returns_check_request(client, demo_dir, scenario):
    r = client.get(f"/api/demo/{scenario}")
    assert r.status_code == 200, r.text
    req = CheckRequest.model_validate(r.json())
    assert req.mode == "demo"  # 데모 데이터는 항상 데모 모드
    assert req.today == dt.date(2026, 11, 14)
    assert req.registry.address_jibun == REGISTRY_OK["address_jibun"]
    assert req.market is not None and req.market.price == 200000000
    assert "800101" not in r.text and "소유자 김민수 ******-*******" in req.registry.gapgu[0].source_text


def test_demo_unknown_scenario_is_404(client, demo_dir):
    assert_error(client.get("/api/demo/D"), 404, "NOT_FOUND")
    assert_error(client.get("/api/demo/A.json"), 404, "NOT_FOUND")
    assert client.get("/api/demo/..%2FA").status_code == 404  # 경로 조작은 라우팅에서 막힌다


def test_demo_missing_file_is_404(client, demo_dir):
    assert_error(client.get("/api/demo/B"), 404, "NOT_FOUND")


@pytest.mark.parametrize("content", ["{not json", json.dumps({**DEMO_FIXTURE, "unknown_field": 1})])
def test_demo_invalid_file_is_500(client, demo_dir, content):
    (demo_dir / "C.json").write_text(content, encoding="utf-8")
    assert_error(client.get("/api/demo/C"), 500, "INTERNAL_ERROR")


def test_demo_dir_defaults_to_backend_demo():
    assert main.DEMO_DIR == config.BACKEND_DIR / "demo"
    assert (config.BACKEND_DIR / "app" / "main.py").is_file()


# ---------------------------------------------------------------------------
# POST /api/check
# ---------------------------------------------------------------------------


def make_report(req: CheckRequest) -> Report:
    return Report(
        mode=req.mode,
        generated_at=dt.datetime(2026, 11, 14, 19, 2, tzinfo=KST),
        today=req.today,
        overall=Overall(level="green", title="큰 위험 신호 없음", message="확인한 범위에서는 큰 위험 신호를 찾지 못했어요."),
        counts=Counts(green=1),
        results=[RuleResult(id="R1", name=RULE_NAMES["R1"], level="green")],
        disclaimer="이 결과는 참고 정보예요.",
    )


@pytest.fixture
def fake_rules(monkeypatch):
    seen: list[CheckRequest] = []

    def fake_build_report(req):
        seen.append(req)
        return make_report(req)

    monkeypatch.setattr(main, "build_report", fake_build_report)
    return seen


def test_check_calls_rules_engine(client, fake_rules):
    r = client.post("/api/check", json={"registry": REGISTRY_OK, "contract": CONTRACT_OK, "today": "2026-11-14"})
    assert r.status_code == 200, r.text
    report = Report.model_validate(r.json())
    assert (report.mode, report.today) == ("live", dt.date(2026, 11, 14))
    (req,) = fake_rules
    assert isinstance(req, CheckRequest)
    assert req.contract is not None and req.contract.landlord_names == ["김민수"]


def test_check_fills_today_with_korean_date(client, fake_rules, monkeypatch):
    monkeypatch.setattr(main, "today_kst", lambda: dt.date(2030, 1, 2))
    r = client.post("/api/check", json={"registry": REGISTRY_OK})
    assert r.status_code == 200, r.text
    assert fake_rules[0].today == dt.date(2030, 1, 2)
    assert r.json()["today"] == "2030-01-02"


def test_today_kst_uses_korean_time():
    assert main.today_kst() == dt.datetime.now(KST).date()


@pytest.mark.parametrize(
    ("extra", "called"),
    [
        ({}, True),  # live + building·market 없음 → 공공 API 자리(P1)를 거친다
        ({"mode": "demo"}, False),  # 데모는 외부 API를 부르지 않는다
        ({"building": DEMO_FIXTURE["building"], "market": DEMO_FIXTURE["market"]}, False),
    ],
    ids=["live-missing", "demo", "live-complete"],
)
def test_check_public_data_hook(client, fake_rules, monkeypatch, extra, called):
    calls = []
    monkeypatch.setattr(main, "fill_public_data", lambda req: calls.append(req) or req)
    r = client.post("/api/check", json={"registry": REGISTRY_OK, "today": "2026-11-14", **extra})
    assert r.status_code == 200, r.text
    assert bool(calls) is called


def test_check_invalid_body_is_422(client, fake_rules):
    r = client.post("/api/check", json={"registry": {"is_registry": "maybe"}})
    assert r.status_code == 422
    assert "detail" in r.json()
    assert fake_rules == []


def test_check_unhandled_error_is_500_without_leaking(client, monkeypatch, caplog):
    def broken(req):
        raise ValueError(f"bad landlord {req.contract.landlord_names[0]}")

    monkeypatch.setattr(main, "build_report", broken)
    caplog.set_level(logging.INFO)
    r = client.post("/api/check", json={"registry": REGISTRY_OK, "contract": CONTRACT_OK})
    assert_error(r, 500, "INTERNAL_ERROR")
    assert "unhandled ValueError" in caplog.text
    assert "김민수" not in caplog.text


def test_check_with_real_rules_engine(client):
    from app import rules

    req = CheckRequest.model_validate({**DEMO_FIXTURE, "mode": "demo"})
    try:
        rules.build_report(req)
    except NotImplementedError:
        pytest.skip("규칙 엔진(app/rules)이 아직 구현되지 않았다")
    r = client.post("/api/check", json=req.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    report = Report.model_validate(r.json())
    assert (report.mode, report.today) == ("demo", dt.date(2026, 11, 14))


# ---------------------------------------------------------------------------
# POST /api/checklist.ics
# ---------------------------------------------------------------------------

ICS_REQUEST = {
    "checklist": [
        {"when": "계약 전", "date": None, "title": "등기부 다시 떼기"},
        {"when": "계약일", "date": "2026-11-14", "title": "특약 넣기, 계약금은 소유자 명의 계좌로 보내기"},
        {"when": "잔금일", "date": "2026-12-31", "title": "잔금 보내기 전 등기부 다시 떼기 (새 근저당이 없는지)"},
        {"when": "입주일", "date": "2027-01-02", "title": "전입신고, 확정일자 받기; 당일"},
        {"when": "입주 후", "date": "2027-01-10", "title": "전세보증금 반환보증 가입"},
    ],
    "address": "경기도 용인시 수지구 죽전동 123-4; 죽전빌라 302호\n(메모 \\ 끝)",
}
NOW = dt.datetime(2026, 11, 14, 10, 0, tzinfo=KST)


def unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def test_ics_endpoint_returns_attachment(client):
    r = client.post("/api/checklist.ics", json=ICS_REQUEST)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/calendar")
    assert r.headers["content-disposition"] == 'attachment; filename="bojeunggeum-checklist.ics"'
    assert r.text.startswith("BEGIN:VCALENDAR\r\n")
    assert r.text.count("BEGIN:VEVENT") == 2


def test_ics_uses_crlf_and_folds_long_lines():
    text = ics.build_ics(IcsRequest.model_validate(ICS_REQUEST), now=NOW)
    assert text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    assert "\r" not in text.replace("\r\n", "")
    physical = text.encode("utf-8").split(b"\r\n")[:-1]
    assert any(line.startswith(b" ") for line in physical)  # 접힌 줄이 있다
    for line in physical:
        assert len(line) <= 75
        line.decode("utf-8")  # UTF-8 글자가 잘리지 않았다


def test_ics_events_dates_alarm_and_escaping():
    lines = unfold(ics.build_ics(IcsRequest.model_validate(ICS_REQUEST), now=NOW))
    assert lines[:4] == ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{ics.PRODID}", "CALSCALE:GREGORIAN"]
    assert lines.count("BEGIN:VEVENT") == 2  # 잔금일·입주일만
    summaries = [line for line in lines if line.startswith("SUMMARY:")]
    assert summaries == [
        "SUMMARY:[보증금 지킴이] 잔금일: 잔금 보내기 전 등기부 다시 떼기 (새 근저당이 없는지)",
        "SUMMARY:[보증금 지킴이] 입주일: 전입신고\\, 확정일자 받기\\; 당일",
    ]
    assert "DTSTART;VALUE=DATE:20261114" not in lines  # 계약일은 넣지 않는다
    assert "DTSTART;VALUE=DATE:20261231" in lines
    assert "DTEND;VALUE=DATE:20270101" in lines  # 다음 날 (해가 바뀜)
    assert "DTSTART;VALUE=DATE:20270102" in lines
    assert "DTEND;VALUE=DATE:20270103" in lines
    assert "DESCRIPTION:주소: 경기도 용인시 수지구 죽전동 123-4\\; 죽전빌라 302호\\n(메모 \\\\ 끝)" in lines
    assert lines.count("DTSTAMP:20261114T010000Z") == 2  # UTC
    assert lines.count("BEGIN:VALARM") == 2
    assert lines.count("ACTION:DISPLAY") == 2
    assert lines.count("TRIGGER:-PT15H") == 2  # 종일 일정 0시 - 15시간 = 전날 09:00
    assert lines.count("END:VALARM") == 2
    uids = [line for line in lines if line.startswith("UID:")]
    assert len(set(uids)) == 2


def test_ics_is_deterministic_and_skips_description_without_address():
    req = IcsRequest.model_validate({**ICS_REQUEST, "address": None})
    first = ics.build_ics(req, now=NOW)
    assert first == ics.build_ics(req, now=NOW)
    assert "DESCRIPTION:주소" not in first


def test_ics_always_has_seoul_timezone_component():
    lines = unfold(ics.build_ics(IcsRequest.model_validate(ICS_REQUEST), now=NOW))
    start = lines.index("BEGIN:VTIMEZONE")
    assert lines[start : start + 10] == [
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Seoul",
        "X-LIC-LOCATION:Asia/Seoul",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0900",
        "TZOFFSETTO:+0900",
        "TZNAME:KST",
        "DTSTART:19700101T000000",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
    assert start < lines.index("BEGIN:VEVENT")


@pytest.mark.parametrize(
    "checklist",
    [
        [],
        [{"when": "입주 후", "title": "계약서 보관"}],
        [{"when": "계약일", "date": "2026-11-14", "title": "특약 넣기"}],
        [{"when": "잔금일", "date": None, "title": "잔금 보내기 전 등기부 다시 떼기"}],
    ],
    ids=["empty", "after-move-in", "contract-day-only", "balance-day-without-date"],
)
def test_ics_without_events_is_still_valid_calendar(client, checklist):
    r = client.post("/api/checklist.ics", json={"checklist": checklist})
    assert r.status_code == 200, r.text
    lines = unfold(r.text)
    assert "BEGIN:VEVENT" not in lines
    # RFC 5545: VCALENDAR에는 구성요소가 하나 이상 있어야 한다
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2:] == ["END:VCALENDAR", ""]
    assert lines.count("BEGIN:VTIMEZONE") == 1 and lines.count("END:VTIMEZONE") == 1


def test_ics_escape_and_fold_helpers():
    assert ics.escape_text("a\\b;c,d\ne\r\nf") == "a\\\\b\\;c\\,d\\ne\\nf"
    ascii_75 = "X" * 75
    assert ics.fold_line(ascii_75) == ascii_75
    assert ics.fold_line("X" * 76) == "X" * 75 + "\r\n X"
    korean = "SUMMARY:" + "보증금지킴이" * 20
    folded = ics.fold_line(korean)
    assert folded.replace("\r\n ", "") == korean
    for part in folded.split("\r\n"):
        assert len(part.encode("utf-8")) <= 75


# ---------------------------------------------------------------------------
# CORS, 요청 ID, 시작/종료, .env
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_cors_allows_vite_dev_server(client, origin):
    r = client.options("/api/extract", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    r = client.get("/api/health", headers={"Origin": origin})
    assert r.headers["access-control-allow-origin"] == origin


def test_cors_rejects_other_origins(client):
    r = client.options("/api/check", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_lifespan_closes_ai_client(monkeypatch):
    fake = install_ai(monkeypatch)
    with TestClient(main.app) as c:
        assert c.get("/api/health").status_code == 200
    assert fake.closed is True
    assert extract._client is None


def test_env_loader(tmp_path, monkeypatch):
    names = ["BOJ_TEST_KEY", "BOJ_TEST_QUOTED", "BOJ_TEST_SINGLE", "BOJ_TEST_EMPTY", "BOJ_TEST_INLINE"]
    for name in names:  # 테스트가 끝나면 지워지도록 monkeypatch에 등록
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)
    monkeypatch.setenv("BOJ_TEST_KEEP", "from-env")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "﻿# 주석\n"
        "\n"
        "BOJ_TEST_KEY=sk-test-123\n"
        'export BOJ_TEST_QUOTED="a b"\n'
        "BOJ_TEST_SINGLE='c'\n"
        "BOJ_TEST_EMPTY=\n"
        "BOJ_TEST_KEEP=from-file\n"
        "BOJ_TEST_INLINE=value # 설명\n"
        "not a pair\n"
        "=no-key\n",
        encoding="utf-8",
    )
    loaded = config.load_env_file(env_file)
    assert loaded == ["BOJ_TEST_KEY", "BOJ_TEST_QUOTED", "BOJ_TEST_SINGLE", "BOJ_TEST_INLINE"]
    assert os.environ["BOJ_TEST_KEY"] == "sk-test-123"
    assert os.environ["BOJ_TEST_QUOTED"] == "a b"
    assert os.environ["BOJ_TEST_SINGLE"] == "c"
    assert os.environ["BOJ_TEST_INLINE"] == "value"
    assert os.environ["BOJ_TEST_KEEP"] == "from-env"  # 이미 있는 값은 덮어쓰지 않는다
    assert "BOJ_TEST_EMPTY" not in os.environ
    assert config.load_env_file(tmp_path / "missing.env") == []


def test_env_example_documents_api_key():
    text = (config.BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^ANTHROPIC_API_KEY=$", text, flags=re.MULTILINE)


def test_request_id_is_unique_per_request(client):
    ids = {client.get("/api/health").headers["x-request-id"] for _ in range(3)}
    assert len(ids) == 3


# ---------------------------------------------------------------------------
# 계약 후 재확인: POST /api/recheck, GET /api/demo/recheck-A
# ---------------------------------------------------------------------------

RECHECK_FIXTURE = {
    "registry": {
        **REGISTRY_OK,
        "eulgu": [
            {
                "page": 3,
                "source_text": "1 근저당권설정 2026년11월27일 제9999호 채권최고액 금120,000,000원 "
                "채무자 김민수 800101-1234567 근저당권자 주식회사○○은행 110111-*******",
                "rank": "1",
                "purpose": "근저당권설정",
                "received_at": "2026-11-27",
                "cause": "설정계약",
                "holders": ["주식회사○○은행"],
                "amount": 120000000,
                "is_cancelled": False,
            }
        ],
    },
    "contract": CONTRACT_OK,
    "today": "2026-11-29",
}


def make_recheck_report(req: RecheckRequest) -> RecheckReport:
    """규칙 엔진 대신 쓰는 가짜 리포트. 입력의 원문을 그대로 옮겨 가림 처리를 확인한다."""
    entry = req.registry.eulgu[0] if req.registry.eulgu else None
    return RecheckReport(
        mode=req.mode,
        generated_at=dt.datetime(2026, 11, 29, 10, 0, tzinfo=KST),
        today=req.today,
        phase="before_balance",
        baseline_date=req.contract.contract_date,
        contract_date=req.contract.contract_date,
        balance_date=req.contract.balance_date,
        overall=Overall(level="red", title="잔금 보류 권장", message="계약 후 새로 생긴 권리가 1건 있어요."),
        changes=[
            RecheckChange(
                section="eulgu",
                rank=entry.rank,
                purpose=entry.purpose,
                received_at=entry.received_at,
                holders=["김민수 800101-1******"],
                amount=entry.amount,
                level="red",
                note="계약 후 새로 생긴 근저당권설정",
                page=entry.page,
                source_text=entry.source_text,
            )
        ]
        if entry
        else [],
        term_checks=[TermCheck(term=req.contract.special_terms[0], status="위반", level="red", note="담보 설정 금지 위반")],
        actions=["잔금을 보내기 전에 임대인(800101-1234567)에게 말소를 요구하세요."],
        disclaimer="이 결과는 참고 정보예요.",
    )


@pytest.fixture
def fake_recheck(monkeypatch):
    seen: list[RecheckRequest] = []

    def fake(req):
        seen.append(req)
        return make_recheck_report(req)

    monkeypatch.setattr(main, "build_recheck", fake)
    return seen


def test_recheck_calls_rules_engine(client, fake_recheck):
    r = client.post("/api/recheck", json=RECHECK_FIXTURE)
    assert r.status_code == 200, r.text
    report = RecheckReport.model_validate(r.json())
    assert (report.mode, report.today, report.phase) == ("live", dt.date(2026, 11, 29), "before_balance")
    assert report.overall.title == "잔금 보류 권장"
    (req,) = fake_recheck
    assert isinstance(req, RecheckRequest)
    assert req.registry.eulgu[0].amount == 120000000


def test_recheck_fills_today_with_korean_date(client, fake_recheck, monkeypatch):
    monkeypatch.setattr(main, "today_kst", lambda: dt.date(2030, 1, 2))
    r = client.post("/api/recheck", json={**RECHECK_FIXTURE, "today": None})
    assert r.status_code == 200, r.text
    assert fake_recheck[0].today == dt.date(2030, 1, 2)
    assert r.json()["today"] == "2030-01-02"


def test_recheck_masks_resident_ids(client, fake_recheck):
    r = client.post("/api/recheck", json=RECHECK_FIXTURE)
    assert r.status_code == 200, r.text
    assert UNMASKED_ID.search(r.text) is None
    for half in ("800101", "110111"):
        assert half not in r.text
    change = r.json()["changes"][0]
    assert change["holders"] == ["김민수 ******-*******"]
    assert change["source_text"].endswith("채무자 김민수 ******-******* 근저당권자 주식회사○○은행 ******-*******")
    assert "금120,000,000원" in change["source_text"] and change["received_at"] == "2026-11-27"
    assert r.json()["actions"] == ["잔금을 보내기 전에 임대인(******-*******)에게 말소를 요구하세요."]


def test_recheck_invalid_body_is_422(client, fake_recheck):
    r = client.post("/api/recheck", json={"registry": REGISTRY_OK})  # 계약서가 빠졌다
    assert r.status_code == 422
    assert "detail" in r.json()
    assert fake_recheck == []


def test_recheck_unhandled_error_is_500(client, monkeypatch):
    def broken(req):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "build_recheck", broken)
    assert_error(client.post("/api/recheck", json=RECHECK_FIXTURE), 500, "INTERNAL_ERROR")


def test_recheck_demo_returns_masked_request(client, tmp_path, monkeypatch):
    (tmp_path / "recheck-A.json").write_text(json.dumps(RECHECK_FIXTURE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main, "DEMO_DIR", tmp_path)
    r = client.get("/api/demo/recheck-A")
    assert r.status_code == 200, r.text
    req = RecheckRequest.model_validate(r.json())
    assert req.mode == "demo"
    assert req.today == dt.date(2026, 11, 29)
    assert UNMASKED_ID.search(r.text) is None
    assert "채무자 김민수 ******-*******" in req.registry.eulgu[0].source_text


def test_recheck_demo_missing_file_is_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DEMO_DIR", tmp_path)  # recheck-A.json이 없다
    assert_error(client.get("/api/demo/recheck-A"), 404, "NOT_FOUND")
    assert_error(client.get("/api/demo/recheck-B"), 404, "NOT_FOUND")  # 다른 이름은 시나리오로도 없다


def test_recheck_demo_invalid_file_is_500(client, tmp_path, monkeypatch):
    (tmp_path / "recheck-A.json").write_text(json.dumps({"registry": REGISTRY_OK}), encoding="utf-8")
    monkeypatch.setattr(main, "DEMO_DIR", tmp_path)
    assert_error(client.get("/api/demo/recheck-A"), 500, "INTERNAL_ERROR")


def test_check_demo_routes_still_work_next_to_recheck_demo(client, demo_dir):
    assert client.get("/api/demo/A").status_code == 200


def test_recheck_with_real_rules_engine(client):
    try:
        from app.rules import build_recheck
    except ImportError:
        pytest.skip("규칙 엔진에 build_recheck가 아직 없다")
    req = RecheckRequest.model_validate({**RECHECK_FIXTURE, "mode": "demo"})
    try:
        build_recheck(req)
    except NotImplementedError:
        pytest.skip("build_recheck가 아직 구현되지 않았다")
    r = client.post("/api/recheck", json=req.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    report = RecheckReport.model_validate(r.json())
    assert (report.mode, report.today) == ("demo", dt.date(2026, 11, 29))
    assert UNMASKED_ID.search(r.text) is None


def test_real_recheck_demo_file_is_valid_and_masked(client):
    if not (config.BACKEND_DIR / "demo" / "recheck-A.json").is_file():
        pytest.skip("demo/recheck-A.json이 아직 없다")
    r = client.get("/api/demo/recheck-A")
    assert r.status_code == 200, r.text
    assert RecheckRequest.model_validate(r.json()).mode == "demo"
    assert UNMASKED_ID.search(r.text) is None
