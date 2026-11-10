"""app/extract.py, app/prompts.py, app/uploads.py 테스트.

진짜 Anthropic 클라이언트는 만들지 않는다 (가짜 클라이언트만 쓴다, 네트워크 없음).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import email.utils
import io
import json
import logging
import time
import typing
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.errors import DependencyError
from pypdf.generic import DecodedStreamObject, NameObject

from app import extract, prompts, uploads
from app.errors import ERROR_MESSAGES, ApiError
from app.schemas import (
    ContractExtract,
    ContractSources,
    ContractUnit,
    Entry,
    RegistryExtract,
    RegistryUnit,
)
from app.uploads import DocInput

# ---------------------------------------------------------------------------
# 가짜 클라이언트와 샘플 데이터
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

REAL_ASYNC_ANTHROPIC = anthropic.AsyncAnthropic  # autouse 픽스처가 바꾸기 전에 잡아 둔다

PDF_DOC = DocInput(kind="document", media_type="application/pdf", data=b"%PDF-1.4 test")
PNG_DOC = DocInput(kind="image", media_type="image/png", data=b"\x89PNG\r\n\x1a\nxxxx")

FORBIDDEN_PARAMS = {"thinking", "temperature", "top_p", "top_k", "tool_choice"}


def make_response(payload=None, *, stop_reason="end_turn", text=None, thinking=True):
    content = []
    if thinking:
        content.append(SimpleNamespace(type="thinking", thinking="", signature="sig"))
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


def responder(registry=None, contract=None):
    """문서 종류별로 응답(또는 예외)을 돌려주는 핸들러. 리스트면 호출 순서대로 쓴다."""
    queues = {"registry": registry, "contract": contract}

    def handler(kwargs, _n):
        item = queues[doc_kind(kwargs)]
        if isinstance(item, list):
            item = item.pop(0)
        return item

    return handler


def run(coro):
    return asyncio.run(coro)


def api_request():
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


PDF_MARKER = b"MARKER-TEXT-0626"  # 본문 스트림에 넣는 글자. 암호가 걸리면 bytes에서 보이지 않는다.


def make_pdf(pages=1, *, user_password=None, owner_password=None, algorithm="RC4-128") -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=200, height=200)
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 10 10 Td (" + PDF_MARKER + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    if user_password is not None or owner_password is not None:
        writer.encrypt(user_password=user_password or "", owner_password=owner_password, algorithm=algorithm)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


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


@pytest.fixture(autouse=True)
def retry_waits(monkeypatch):
    """재시도 전 대기(extract._sleep)를 실제로 하지 않고 기다릴 초만 기록한다."""
    waits: list[float] = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(extract, "_sleep", fake_sleep)
    return waits


# ---------------------------------------------------------------------------
# 스키마: Pydantic 모델과 맞는지, 구조화 출력 제약을 지키는지
# ---------------------------------------------------------------------------

UNSUPPORTED_KEYWORDS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                        "minLength", "maxLength", "maxItems", "uniqueItems", "$ref"}


def walk(schema):
    yield schema
    for value in schema.get("properties", {}).values():
        yield from walk(value)
    if "items" in schema:
        yield from walk(schema["items"])
    for option in schema.get("anyOf", []):
        yield from walk(option)


def count_unions(schema) -> int:
    return sum(1 for node in walk(schema) if "anyOf" in node or isinstance(node.get("type"), list))


def literal_values(annotation) -> set:
    values = set()
    for arg in typing.get_args(annotation):
        if typing.get_origin(arg) is typing.Literal:
            values |= set(typing.get_args(arg))
    return values


def sample(schema, *, nulls: bool):
    """스키마가 허용하는 예시 값을 만든다 (nulls=True면 null을 고를 수 있는 곳은 모두 null)."""
    if "anyOf" in schema:
        options = [o for o in schema["anyOf"] if o.get("type") != "null"]
        return None if nulls else sample(options[0], nulls=nulls)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema["type"]
    if kind == "object":
        return {key: sample(value, nulls=nulls) for key, value in schema["properties"].items()}
    if kind == "array":
        return [] if nulls else [sample(schema["items"], nulls=nulls)]
    if kind == "string":
        return {"date": "2026-11-14", "date-time": "2026-11-14T10:31:22+09:00"}.get(schema.get("format"), "글자")
    return {"integer": 120000000, "number": 59.94, "boolean": True}[kind]


def test_registry_schema_fields_match_pydantic_models():
    props = prompts.REGISTRY_SCHEMA["properties"]
    assert set(props) == set(RegistryExtract.model_fields)
    assert set(props["unit"]["properties"]) == set(RegistryUnit.model_fields)
    for key in ("gapgu", "eulgu"):
        assert set(props[key]["items"]["properties"]) == set(Entry.model_fields)
    assert set(props["registry_type"]["anyOf"][0]["enum"]) == literal_values(
        RegistryExtract.model_fields["registry_type"].annotation
    )


def test_contract_schema_fields_match_pydantic_models():
    props = prompts.CONTRACT_SCHEMA["properties"]
    assert set(props) == set(ContractExtract.model_fields)
    assert set(props["unit"]["properties"]) == set(ContractUnit.model_fields)
    assert set(props["sources"]["properties"]) == set(ContractSources.model_fields)
    assert set(props["lease_type"]["anyOf"][0]["enum"]) == literal_values(
        ContractExtract.model_fields["lease_type"].annotation
    )


@pytest.mark.parametrize("schema", [prompts.REGISTRY_SCHEMA, prompts.CONTRACT_SCHEMA], ids=["registry", "contract"])
def test_schema_follows_structured_output_rules(schema):
    for node in walk(schema):
        assert not (UNSUPPORTED_KEYWORDS & set(node)), node
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])
        if "anyOf" in node:
            assert node["anyOf"][-1] == {"type": "null"}
    # 구조화 출력 한도: union(anyOf) 필드는 요청당 16개까지
    assert count_unions(schema) <= 16
    json.dumps(schema)  # 직렬화 가능


@pytest.mark.parametrize(
    ("schema", "model"),
    [(prompts.REGISTRY_SCHEMA, RegistryExtract), (prompts.CONTRACT_SCHEMA, ContractExtract)],
    ids=["registry", "contract"],
)
@pytest.mark.parametrize("nulls", [True, False], ids=["nulls", "values"])
def test_schema_examples_validate_with_pydantic(schema, model, nulls):
    model.model_validate(sample(schema, nulls=nulls))


def test_prompts_carry_prd_principles():
    for prompt in (prompts.REGISTRY_SYSTEM_PROMPT, prompts.CONTRACT_SYSTEM_PROMPT):
        assert "null" in prompt
        assert "판단" in prompt  # 위험 판단을 하지 않는다
        assert "YYYY-MM-DD" in prompt
    registry_prompt = prompts.REGISTRY_SYSTEM_PROMPT
    for phrase in ("120000000", "수탁자", "근저당권자", "is_cancelled", "source_text", "빠뜨리지", "unreadable"):
        assert phrase in registry_prompt
    assert "special_terms" in prompts.CONTRACT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Claude 호출 모양
# ---------------------------------------------------------------------------


def test_registry_call_shape_matches_prd():
    fake = FakeClient(responder(registry=make_response(REGISTRY_OK)))
    result = run(extract.extract_registry(fake, PDF_DOC))

    assert isinstance(result, RegistryExtract)
    assert result.gapgu[0].holders == ["김민수"]
    (kwargs,) = fake.messages.calls
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 16000
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["fallbacks"] == "default"
    assert kwargs["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": prompts.REGISTRY_SCHEMA},
    }
    assert kwargs["system"] == prompts.REGISTRY_SYSTEM_PROMPT
    assert kwargs["timeout"] == extract.CLIENT_TIMEOUT  # 마감 없이 부르면 클라이언트 timeout
    assert not (FORBIDDEN_PARAMS & set(kwargs))
    (message,) = kwargs["messages"]
    assert message["role"] == "user"
    document, text = message["content"]
    assert document == {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0xLjQgdGVzdA=="},
    }
    assert text == {"type": "text", "text": "이 등기사항전부증명서를 정해진 형식으로 옮겨 주세요."}


def test_contract_photo_uses_image_block():
    fake = FakeClient(responder(contract=make_response(CONTRACT_OK)))
    result = run(extract.extract_contract(fake, PNG_DOC))

    assert result.deposit == 10000000
    (kwargs,) = fake.messages.calls
    assert kwargs["system"] == prompts.CONTRACT_SYSTEM_PROMPT
    assert kwargs["output_config"]["format"]["schema"] is prompts.CONTRACT_SCHEMA
    image = kwargs["messages"][0]["content"][0]
    assert image["type"] == "image"
    assert image["source"]["type"] == "base64"
    assert image["source"]["media_type"] == "image/png"


def test_text_block_after_thinking_and_fallback_blocks_is_used():
    resp = make_response(REGISTRY_OK)
    resp.content.insert(0, SimpleNamespace(type="fallback"))
    fake = FakeClient(responder(registry=resp))
    assert run(extract.extract_registry(fake, PDF_DOC)).building_name == "죽전빌라"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-11-14T10:31:22+09:00", "2026-11-14T10:31:22+09:00"),
        ("2026-11-13T16:00:00Z", "2026-11-14T01:00:00+09:00"),  # UTC로 와도 한국 시간으로 맞춘다
        ("2026-11-14T10:31:22", "2026-11-14T10:31:22+09:00"),  # 시간대가 없으면 한국 시간
    ],
)
def test_viewed_at_is_normalized_to_kst(raw, expected):
    fake = FakeClient(responder(registry=make_response({**REGISTRY_OK, "viewed_at": raw})))
    result = run(extract.extract_registry(fake, PDF_DOC))
    assert result.viewed_at == dt.datetime.fromisoformat(expected)
    assert result.viewed_at.utcoffset() == dt.timedelta(hours=9)


# ---------------------------------------------------------------------------
# 진짜 SDK + 메모리 안의 가짜 HTTP (네트워크 없음): 요청 직렬화와 오류 매핑 확인
# ---------------------------------------------------------------------------


def message_json(payload=None, stop_reason="end_turn", text=None):
    if text is None and payload is not None:
        text = json.dumps(payload, ensure_ascii=False)
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    if text is not None:
        content.append({"type": "text", "text": text})
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


def call_with_sdk(handler, fn=extract.extract_registry, doc=PDF_DOC):
    async def scenario():
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        async with REAL_ASYNC_ANTHROPIC(  # get_client()와 같은 timeout (재시도 지연만 끈다)
            api_key="test-key",
            base_url="https://api.anthropic.com",
            timeout=extract.CLIENT_TIMEOUT,
            max_retries=0,
            http_client=http_client,
        ) as client:
            return await fn(client, doc)

    return run(scenario())


def test_real_sdk_serializes_expected_request():
    seen: list[httpx2.Request] = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200, json=message_json(REGISTRY_OK))

    result = call_with_sdk(handler)
    assert result.building_name == "죽전빌라"
    (request,) = seen
    assert (request.method, request.url.path) == ("POST", "/v1/messages")
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
    body = json.loads(request.content)
    assert set(body) == {"model", "max_tokens", "fallbacks", "output_config", "system", "messages"}
    assert body["fallbacks"] == "default"
    assert body["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": prompts.REGISTRY_SCHEMA},
    }
    assert body["messages"][0]["content"][0]["source"]["media_type"] == "application/pdf"


def test_real_sdk_max_tokens_retry_and_refusal():
    replies = [message_json(stop_reason="max_tokens", text="{"), message_json(REGISTRY_OK)]
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["max_tokens"])
        return httpx2.Response(200, json=replies.pop(0))

    assert call_with_sdk(handler).is_registry is True
    assert seen == [16000, 32000]

    refusal = {**message_json(), "content": [], "stop_reason": "refusal"}
    with pytest.raises(ApiError) as excinfo:
        call_with_sdk(lambda request: httpx2.Response(200, json=refusal))
    assert excinfo.value.reason == "registry:refusal"


@pytest.mark.parametrize(
    ("status", "reason"),
    [(429, "rate_limited"), (500, "api_status_500"), (529, "api_status_529"), (400, "api_status_400")],
)
def test_real_sdk_http_errors_map_to_ai_failed(status, reason):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(status, json={"type": "error", "error": {"type": "error", "message": "x"}})

    with pytest.raises(ApiError) as excinfo:
        call_with_sdk(handler)
    assert_ai_failed(excinfo)
    assert excinfo.value.reason == f"registry:{reason}"
    assert len(seen) == (1 if status == 400 else 2)  # 429·5xx만 한 번 다시 부른다


def test_real_sdk_rate_limit_honors_retry_after(retry_waits):
    replies = [
        httpx2.Response(429, headers={"retry-after": "3"}, json={"type": "error", "error": {"type": "x", "message": "x"}}),
        httpx2.Response(200, json=message_json(REGISTRY_OK)),
    ]
    assert call_with_sdk(lambda request: replies.pop(0)).is_registry is True
    assert retry_waits == [3.0]


@pytest.mark.parametrize(
    ("error", "reason"),
    [(httpx2.ConnectError("down"), "connection_error"), (httpx2.ReadTimeout("slow"), "timeout")],
    ids=["connect", "timeout"],
)
def test_real_sdk_network_errors_map_to_ai_failed(error, reason):
    seen = []

    def handler(request):
        seen.append(request)
        raise error

    with pytest.raises(ApiError) as excinfo:
        call_with_sdk(handler)
    assert_ai_failed(excinfo)
    assert excinfo.value.reason == f"registry:{reason}"
    assert len(seen) == 2


# ---------------------------------------------------------------------------
# 응답 처리: refusal, max_tokens, 잘못된 JSON
# ---------------------------------------------------------------------------


def assert_ai_failed(excinfo, status=502):
    assert excinfo.value.code == "AI_FAILED"
    assert excinfo.value.status == status
    assert excinfo.value.message == ERROR_MESSAGES["AI_FAILED"]


def test_refusal_is_ai_failed_without_retry():
    fake = FakeClient(responder(registry=make_response(None, stop_reason="refusal")))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_registry(fake, PDF_DOC))
    assert_ai_failed(excinfo)
    assert len(fake.messages.calls) == 1


def test_max_tokens_retries_once_with_larger_limit():
    truncated = make_response(None, stop_reason="max_tokens", text='{"is_registry": tr')
    fake = FakeClient(responder(registry=[truncated, make_response(REGISTRY_OK)]))
    result = run(extract.extract_registry(fake, PDF_DOC))
    assert result.is_registry is True
    assert [c["max_tokens"] for c in fake.messages.calls] == [16000, 32000]


def test_max_tokens_twice_is_ai_failed():
    truncated = make_response(None, stop_reason="max_tokens", text="{")
    fake = FakeClient(responder(registry=[truncated, truncated]))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_registry(fake, PDF_DOC))
    assert_ai_failed(excinfo)
    assert len(fake.messages.calls) == 2


@pytest.mark.parametrize(
    "resp",
    [
        make_response(None, text="이건 JSON이 아니에요"),
        make_response(None, text='{"is_registry": "maybe"}'),  # 타입이 틀림
        make_response(None, text='{"is_registry": true, "owner": "김민수"}'),  # 정의되지 않은 필드
        make_response(None, text="[1, 2]"),
        make_response(None, text=None),  # text 블록 없음
        make_response(REGISTRY_OK, stop_reason="model_context_window_exceeded"),
    ],
    ids=["not-json", "wrong-type", "extra-field", "not-object", "no-text", "context-window"],
)
def test_bad_responses_are_ai_failed(resp):
    fake = FakeClient(responder(registry=resp))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_registry(fake, PDF_DOC))
    assert_ai_failed(excinfo)
    assert len(fake.messages.calls) == 1  # JSON·스키마 오류는 다시 부르지 않는다


@pytest.mark.parametrize(
    ("error", "calls"),
    [
        (anthropic.APITimeoutError(request=api_request()), 2),
        (anthropic.APIConnectionError(request=api_request()), 2),
        (anthropic.RateLimitError("rate limited", response=httpx2.Response(429, request=api_request()), body=None), 2),
        (anthropic.InternalServerError("boom", response=httpx2.Response(500, request=api_request()), body=None), 2),
        (anthropic.BadRequestError("bad", response=httpx2.Response(400, request=api_request()), body=None), 1),
        (anthropic.AnthropicError("credentials"), 1),
    ],
    ids=["timeout", "connection", "rate-limit", "server-500", "bad-request", "other-sdk-error"],
)
def test_sdk_errors_are_ai_failed(error, calls):
    fake = FakeClient(responder(registry=error))  # 매번 같은 오류
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_registry(fake, PDF_DOC))
    assert_ai_failed(excinfo)
    assert len(fake.messages.calls) == calls  # 일시적 오류만 한 번 다시 부른다


# ---------------------------------------------------------------------------
# 문서 판별: NOT_REGISTRY, LAND_REGISTRY, NOT_CONTRACT
# ---------------------------------------------------------------------------


def test_not_registry():
    payload = {**REGISTRY_OK, "is_registry": False, "registry_type": None}
    fake = FakeClient(responder(registry=make_response(payload)))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_registry(fake, PDF_DOC))
    assert (excinfo.value.code, excinfo.value.status) == ("NOT_REGISTRY", 422)


def test_land_registry():
    payload = {**REGISTRY_OK, "registry_type": "토지"}
    fake = FakeClient(responder(registry=make_response(payload)))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_registry(fake, PDF_DOC))
    assert (excinfo.value.code, excinfo.value.status) == ("LAND_REGISTRY", 422)


def test_not_contract():
    fake = FakeClient(responder(contract=make_response({**CONTRACT_OK, "is_contract": False})))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_contract(fake, PNG_DOC))
    assert (excinfo.value.code, excinfo.value.status) == ("NOT_CONTRACT", 422)


# ---------------------------------------------------------------------------
# 병렬 호출과 오류 우선순위
# ---------------------------------------------------------------------------


def test_registry_and_contract_run_concurrently():
    async def scenario():
        both_started = asyncio.Event()
        started = []

        async def handler_async(kwargs):
            started.append(doc_kind(kwargs))
            if len(started) == 2:
                both_started.set()
            # 순서대로 부르면 두 번째 호출이 시작되지 않아 여기서 시간 초과가 난다
            await asyncio.wait_for(both_started.wait(), timeout=2)
            return make_response(REGISTRY_OK if doc_kind(kwargs) == "registry" else CONTRACT_OK)

        fake = FakeClient(lambda kwargs, _n: handler_async(kwargs))
        return await extract.extract_documents(PDF_DOC, PNG_DOC, client=fake), started

    result, started = run(scenario())
    assert sorted(started) == ["contract", "registry"]
    assert result.registry.address_jibun == REGISTRY_OK["address_jibun"]
    assert result.contract is not None and result.contract.monthly_rent == 450000


def test_registry_only_returns_null_contract():
    fake = FakeClient(responder(registry=make_response(REGISTRY_OK)))
    result = run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert result.contract is None
    assert len(fake.messages.calls) == 1


def test_registry_error_wins_over_contract_error():
    fake = FakeClient(
        responder(
            registry=make_response({**REGISTRY_OK, "is_registry": False}),
            contract=make_response({**CONTRACT_OK, "is_contract": False}),
        )
    )
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_documents(PDF_DOC, PNG_DOC, client=fake))
    assert excinfo.value.code == "NOT_REGISTRY"


def test_contract_failure_fails_whole_request():
    fake = FakeClient(
        responder(registry=make_response(REGISTRY_OK), contract=make_response(None, stop_reason="refusal"))
    )
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_documents(PDF_DOC, PNG_DOC, client=fake))
    assert_ai_failed(excinfo)


# ---------------------------------------------------------------------------
# 마감 시간 (EXTRACT_DEADLINE_SECONDS): 두 문서를 합쳐 이 안에 끝내거나 AI_FAILED
# ---------------------------------------------------------------------------


def slow_handler(delays, cancelled, replies=None):
    """문서 종류별로 delays초 잠든 뒤 응답한다. 취소되면 문서 종류를 cancelled에 적는다."""
    replies = replies or {"registry": make_response(REGISTRY_OK), "contract": make_response(CONTRACT_OK)}

    async def handle(kwargs):
        kind = doc_kind(kwargs)
        try:
            await asyncio.sleep(delays.get(kind, 0))
        except asyncio.CancelledError:
            cancelled.append(kind)
            raise
        return replies[kind]

    return lambda kwargs, _n: handle(kwargs)


def timed(coro):
    started = time.perf_counter()
    try:
        return run(coro), time.perf_counter() - started
    except ApiError as e:
        e.elapsed = time.perf_counter() - started  # type: ignore[attr-defined]
        raise


def test_deadline_seconds_from_env(monkeypatch):
    assert extract.deadline_seconds() == 85.0
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "0.25")
    assert extract.deadline_seconds() == 0.25
    for bad in ("abc", "0", "-5", "nan", "inf", " "):
        monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", bad)
        assert extract.deadline_seconds() == 85.0


def test_slow_extraction_fails_at_deadline_and_cancels_calls(monkeypatch):
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "0.2")
    cancelled: list[str] = []
    fake = FakeClient(slow_handler({"registry": 10, "contract": 10}, cancelled))
    with pytest.raises(ApiError) as excinfo:
        timed(extract.extract_documents(PDF_DOC, PNG_DOC, client=fake))
    assert_ai_failed(excinfo)
    assert excinfo.value.reason == "deadline_0.2s"
    assert excinfo.value.elapsed < 2  # 10초를 기다리지 않는다
    assert sorted(cancelled) == ["contract", "registry"]  # 진행 중인 호출은 취소된다


def test_deadline_covers_both_documents(monkeypatch):
    # 등기부가 먼저 끝나도 계약서가 늦으면 전체가 마감에 걸린다
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "0.3")
    cancelled: list[str] = []
    fake = FakeClient(slow_handler({"registry": 0.01, "contract": 10}, cancelled))
    with pytest.raises(ApiError) as excinfo:
        timed(extract.extract_documents(PDF_DOC, PNG_DOC, client=fake))
    assert_ai_failed(excinfo)
    assert excinfo.value.elapsed < 2
    assert cancelled == ["contract"]


def test_concurrent_calls_share_one_deadline(monkeypatch):
    # 0.6초짜리 호출 둘은 동시에 돌아 1초 마감 안에 끝난다 (차례로 부르면 1.2초)
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "1.0")
    fake = FakeClient(slow_handler({"registry": 0.6, "contract": 0.6}, []))
    result, elapsed = timed(extract.extract_documents(PDF_DOC, PNG_DOC, client=fake))
    assert result.contract is not None
    assert elapsed < 1.0


def test_registry_error_does_not_wait_for_contract(monkeypatch):
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "5")
    cancelled: list[str] = []
    replies = {"registry": make_response({**REGISTRY_OK, "is_registry": False}), "contract": make_response(CONTRACT_OK)}
    fake = FakeClient(slow_handler({"contract": 10}, cancelled, replies))
    with pytest.raises(ApiError) as excinfo:
        timed(extract.extract_documents(PDF_DOC, PNG_DOC, client=fake))
    assert excinfo.value.code == "NOT_REGISTRY"  # 마감(AI_FAILED)에 가려지지 않는다
    assert excinfo.value.elapsed < 2
    assert cancelled == ["contract"]


def test_max_tokens_retry_skipped_when_first_attempt_was_too_slow(monkeypatch):
    # 첫 시도 0.6초, 남은 시간 약 0.4초 → 다시 불러도 마감 전에 못 끝나므로 바로 실패한다
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "1.0")
    monkeypatch.setattr(extract, "RETRY_MIN_SECONDS", 0.0)
    truncated = make_response(None, stop_reason="max_tokens", text="{")
    fake = FakeClient(slow_handler({"registry": 0.6}, [], {"registry": truncated}))
    with pytest.raises(ApiError) as excinfo:
        timed(extract.extract_documents(PDF_DOC, None, client=fake))
    assert_ai_failed(excinfo)
    assert excinfo.value.reason == "registry:max_tokens_no_time"
    assert len(fake.messages.calls) == 1


def test_max_tokens_retry_needs_min_seconds_left(monkeypatch):
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "5")  # 5초 < RETRY_MIN_SECONDS(10초)
    fake = FakeClient(responder(registry=make_response(None, stop_reason="max_tokens", text="{")))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert excinfo.value.reason == "registry:max_tokens_no_time"
    assert len(fake.messages.calls) == 1


def test_max_tokens_retry_within_default_deadline():
    truncated = make_response(None, stop_reason="max_tokens", text="{")
    fake = FakeClient(responder(registry=[truncated, make_response(REGISTRY_OK)]))
    run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert [c["max_tokens"] for c in fake.messages.calls] == [16000, 32000]


def test_request_timeout_is_remaining_time():
    fake = FakeClient(responder(registry=make_response(REGISTRY_OK)))
    run(extract.extract_documents(PDF_DOC, None, client=fake))
    (kwargs,) = fake.messages.calls
    assert 80 < kwargs["timeout"] <= 85  # 기본 마감 85초에서 남은 시간


# ---------------------------------------------------------------------------
# 일시적 오류 재시도: 문서마다 한 번, 마감까지 10초 이상 남았을 때만
# ---------------------------------------------------------------------------


def status_error(status, headers=None):
    response = httpx2.Response(status, headers=headers or {}, request=api_request())
    if status == 429:
        return anthropic.RateLimitError("rate limited", response=response, body=None)
    return anthropic.APIStatusError(f"status {status}", response=response, body=None)


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APITimeoutError(request=api_request()),
        anthropic.APIConnectionError(request=api_request()),
        status_error(500),
        status_error(529),
        status_error(429),
    ],
    ids=["timeout", "connection", "500", "529-overloaded", "429-no-retry-after"],
)
def test_transient_error_is_retried_once_and_succeeds(error, retry_waits, caplog):
    caplog.set_level(logging.INFO)
    fake = FakeClient(responder(registry=[error, make_response(REGISTRY_OK)]))
    result = run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert result.registry.building_name == "죽전빌라"
    first, second = fake.messages.calls
    assert first["max_tokens"] == second["max_tokens"] == 16000  # 같은 요청을 다시 보낸다
    assert 0 < second["timeout"] <= first["timeout"] <= 85  # 다시 부를 때 timeout은 남은 시간
    assert retry_waits == [extract.RETRY_BACKOFF_SECONDS]
    assert "claude retry doc=registry reason=" in caplog.text


def test_transient_retry_happens_only_once():
    fake = FakeClient(responder(registry=[status_error(503), status_error(502), make_response(REGISTRY_OK)]))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert excinfo.value.reason == "registry:api_status_502"
    assert len(fake.messages.calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 408, 409, 413, 422])
def test_no_retry_on_4xx_other_than_429(status, retry_waits):
    fake = FakeClient(responder(registry=[status_error(status), make_response(REGISTRY_OK)]))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert excinfo.value.reason == f"registry:api_status_{status}"
    assert len(fake.messages.calls) == 1
    assert retry_waits == []


def test_no_retry_when_less_than_10s_left(monkeypatch, retry_waits, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "9")
    fake = FakeClient(responder(registry=[status_error(500), make_response(REGISTRY_OK)]))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert_ai_failed(excinfo)
    assert excinfo.value.reason == "registry:api_status_500"
    assert len(fake.messages.calls) == 1
    assert retry_waits == []
    assert "claude no retry doc=registry reason=api_status_500" in caplog.text


def test_no_retry_when_wait_would_leave_less_than_10s(monkeypatch):
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "10.5")  # 1초 기다리면 9.5초만 남는다
    fake = FakeClient(responder(registry=[status_error(500), make_response(REGISTRY_OK)]))
    with pytest.raises(ApiError):
        run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert len(fake.messages.calls) == 1


def test_rate_limit_retry_after_is_honored(retry_waits):
    fake = FakeClient(responder(registry=[status_error(429, {"retry-after": "5"}), make_response(REGISTRY_OK)]))
    run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert len(fake.messages.calls) == 2
    assert retry_waits == [5.0]


def test_rate_limit_retry_after_too_long_is_not_retried(retry_waits):
    # 기본 마감 85초에서 120초를 기다리면 다시 부를 시간이 없다
    fake = FakeClient(responder(registry=[status_error(429, {"retry-after": "120"}), make_response(REGISTRY_OK)]))
    with pytest.raises(ApiError) as excinfo:
        run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert excinfo.value.reason == "registry:rate_limited"
    assert len(fake.messages.calls) == 1
    assert retry_waits == []


def test_server_can_forbid_retry():
    fake = FakeClient(responder(registry=[status_error(503, {"x-should-retry": "false"}), make_response(REGISTRY_OK)]))
    with pytest.raises(ApiError):
        run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert len(fake.messages.calls) == 1


def test_error_retry_and_max_tokens_retry_are_separate():
    truncated = make_response(None, stop_reason="max_tokens", text="{")
    fake = FakeClient(responder(registry=[status_error(529), truncated, make_response(REGISTRY_OK)]))
    run(extract.extract_documents(PDF_DOC, None, client=fake))
    assert [c["max_tokens"] for c in fake.messages.calls] == [16000, 16000, 32000]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 1.0),
        ({"retry-after": "7"}, 7.0),
        ({"retry-after-ms": "1500", "retry-after": "9"}, 1.5),
        ({"retry-after": "not a number"}, 1.0),
        ({"retry-after": "-3"}, 0.0),
    ],
)
def test_retry_wait_seconds(headers, expected):
    assert extract._retry_wait_seconds(status_error(429, headers)) == expected


def test_retry_wait_seconds_http_date():
    when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30)
    wait = extract._retry_wait_seconds(status_error(429, {"retry-after": email.utils.format_datetime(when)}))
    assert 25 < wait <= 30
    assert extract._retry_wait_seconds(anthropic.APIConnectionError(request=api_request())) == 1.0


# ---------------------------------------------------------------------------
# 클라이언트 만들기 (API 키)
# ---------------------------------------------------------------------------


def test_no_api_key_is_503_without_creating_client():
    with pytest.raises(ApiError) as excinfo:
        extract.get_client()
    assert_ai_failed(excinfo, status=503)
    assert extract._client is None


@pytest.mark.parametrize("env_name", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_client_is_created_lazily_once(monkeypatch, env_name):
    created = []

    def fake_constructor(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(kind="client")

    monkeypatch.setattr(anthropic, "AsyncAnthropic", fake_constructor)
    monkeypatch.setenv(env_name, "test-key")
    first = extract.get_client()
    assert extract.get_client() is first
    assert created == [{"timeout": 90.0, "max_retries": 0}]  # SDK 재시도 없음 (마감 시간 보호)
    assert extract.has_credentials() is True


def test_aclose_client_closes_and_forgets(monkeypatch):
    closed = []

    class Closable:
        async def close(self):
            closed.append(True)

    monkeypatch.setattr(extract, "_client", Closable())
    run(extract.aclose_client())
    assert closed == [True]
    assert extract._client is None
    run(extract.aclose_client())  # 클라이언트가 없어도 괜찮다


def test_logs_do_not_contain_document_content(caplog):
    caplog.set_level(logging.INFO)
    fake = FakeClient(
        responder(
            registry=make_response(REGISTRY_OK),
            contract=make_response(None, text=json.dumps({**CONTRACT_OK, "landlord": "김민수"}, ensure_ascii=False)),
        )
    )
    with pytest.raises(ApiError):
        run(extract.extract_documents(PDF_DOC, PNG_DOC, client=fake))
    assert "claude doc=registry" in caplog.text  # 상태 로그는 남는다
    for secret in ("김민수", "죽전", "800101", "일천만원"):
        assert secret not in caplog.text


# ---------------------------------------------------------------------------
# 업로드 검사 (app/uploads.py)
# ---------------------------------------------------------------------------


def unsupported(fn, data):
    with pytest.raises(ApiError) as excinfo:
        fn(data)
    assert (excinfo.value.code, excinfo.value.status) == ("UNSUPPORTED_FILE", 400)
    return excinfo.value.reason


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b"\xff\xd8\xff\xe0" + b"\x00" * 16, "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png"),
        (b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16, "image/webp"),
    ],
    ids=["jpeg", "png", "webp"],
)
def test_contract_photo_types_by_magic_bytes(data, media_type):
    doc = uploads.validate_contract(data)
    assert (doc.kind, doc.media_type, doc.data) == ("image", media_type, data)


@pytest.mark.parametrize(
    "data",
    [b"GIF89a" + b"\x00" * 16, b"hello, contract", b"RIFF\x24\x00\x00\x00WAVEfmt ", b"\x00\x00\x00\x18ftypheic"],
    ids=["gif", "text", "riff-not-webp", "heic"],
)
def test_contract_rejects_other_types(data):
    assert unsupported(uploads.validate_contract, data) == "contract:unsupported_type"


def test_contract_pdf_gets_pdf_checks():
    doc = uploads.validate_contract(make_pdf(2))
    assert (doc.kind, doc.media_type) == ("document", "application/pdf")
    assert unsupported(uploads.validate_contract, make_pdf(31)) == "contract:too_many_pages"


def test_registry_accepts_pdf_up_to_30_pages():
    data = make_pdf(30)
    doc = uploads.validate_registry(data)
    assert (doc.kind, doc.media_type, doc.data) == ("document", "application/pdf", data)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "registry:empty"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "registry:not_pdf"),
        (b"%PDF-1.7\n" + b"\x00" * 64, "registry:broken_pdf"),
        (make_pdf(31), "registry:too_many_pages"),
        (make_pdf(2, user_password="secret"), "registry:encrypted_pdf"),
        (make_pdf(2, user_password="secret", owner_password="owner", algorithm="AES-256"), "registry:encrypted_pdf"),
        (make_pdf(31, owner_password="owner", algorithm="AES-256"), "registry:too_many_pages"),  # 푼 사본으로 센다
    ],
    ids=["empty", "png", "broken", "31-pages", "user-password-rc4", "user-password-aes256", "owner-only-31-pages"],
)
def test_registry_rejections(data, reason):
    assert unsupported(uploads.validate_registry, data) == reason


@pytest.mark.parametrize("algorithm", ["AES-256", "AES-128", "RC4-128"])
def test_owner_only_encrypted_pdf_is_decrypted_in_memory(algorithm):
    # 인터넷등기소 PDF처럼 열람 암호 없이 권한 제한(소유자 암호)만 걸린 경우
    data = make_pdf(2, owner_password="owner", algorithm=algorithm)
    assert PdfReader(io.BytesIO(data)).is_encrypted
    assert PDF_MARKER not in data  # 원본 본문은 암호화돼 있다

    for validate in (uploads.validate_registry, uploads.validate_contract):
        doc = validate(data)
        assert (doc.kind, doc.media_type) == ("document", "application/pdf")
        plain = PdfReader(io.BytesIO(doc.data))
        assert plain.is_encrypted is False
        assert len(plain.pages) == 2
        assert PDF_MARKER in plain.pages[0].get_contents().get_data()


@pytest.mark.parametrize("offset", [1, 300, 1019])
def test_pdf_header_within_first_1024_bytes_is_accepted_and_sliced(offset):
    # PDF 뷰어(와 프론트엔드)처럼 앞 1024바이트 안의 "%PDF-"를 찾고, 그 위치부터 Claude에 보낸다
    pdf = make_pdf(2)
    data = b"\xef\xbb\xbf" + b"x" * (offset - 3) if offset >= 3 else b"x" * offset
    for validate in (uploads.validate_registry, uploads.validate_contract):
        doc = validate(data + pdf)
        assert doc.data == pdf
        assert doc.data.startswith(b"%PDF-")


def test_pdf_header_past_first_1024_bytes_is_rejected():
    data = b"x" * 1020 + make_pdf(1)  # "%PDF-"가 1024바이트를 넘어 걸친다
    assert unsupported(uploads.validate_registry, data) == "registry:not_pdf"
    assert unsupported(uploads.validate_contract, data) == "contract:unsupported_type"
    assert uploads.pdf_header_offset(b"x" * 1019 + b"%PDF-") == 1019
    assert uploads.pdf_header_offset(b"x" * 1020 + b"%PDF-") is None


def test_owner_encrypted_pdf_with_leading_bytes_is_decrypted():
    data = b"junk\r\n" + make_pdf(1, owner_password="owner", algorithm="AES-256")
    plain = PdfReader(io.BytesIO(uploads.validate_registry(data).data))
    assert plain.is_encrypted is False
    assert PDF_MARKER in plain.pages[0].get_contents().get_data()


def test_photo_with_pdf_text_in_metadata_stays_a_photo():
    jpeg = b"\xff\xd8\xff\xe1\x00\x20Exif\x00\x00 %PDF-1.4 in metadata " + b"\x00" * 64
    doc = uploads.validate_contract(jpeg)
    assert (doc.kind, doc.media_type, doc.data) == ("image", "image/jpeg", jpeg)


def test_unencrypted_pdf_bytes_are_passed_through_unchanged():
    data = make_pdf(2)
    assert uploads.validate_registry(data).data == data


def test_aes_pdf_without_cryptography_is_unsupported(monkeypatch):
    class NoCryptoReader:
        is_encrypted = True

        def __init__(self, stream):
            pass

        def decrypt(self, password):
            raise DependencyError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr(uploads, "PdfReader", NoCryptoReader)
    reason = unsupported(uploads.validate_registry, b"%PDF-1.7 aes")
    assert reason == "registry:encrypted_pdf_needs_cryptography"


def test_size_limit_is_10mb():
    uploads._check_size("registry", b"x" * uploads.MAX_UPLOAD_BYTES)  # 딱 10MB는 통과
    assert unsupported(uploads.validate_registry, b"%PDF" + b"x" * uploads.MAX_UPLOAD_BYTES) == "registry:too_large"
    assert unsupported(uploads.validate_contract, b"\xff\xd8\xff" + b"x" * uploads.MAX_UPLOAD_BYTES) == (
        "contract:too_large"
    )
