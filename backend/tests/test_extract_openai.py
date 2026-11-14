"""OpenAI(GPT)로 서류를 읽는 경로: AI 고르기, 요청 형태, 응답 처리, 재시도.

네트워크를 쓰지 않는다. OpenAIClient에 가짜 SDK를 끼워 responses.create 호출만 흉내 낸다.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from types import SimpleNamespace

import httpx
import openai
import pytest

from app import extract
from app.errors import ApiError
from test_extract import CONTRACT_OK, PDF_DOC, PNG_DOC, REGISTRY_OK


# ---------------------------------------------------------------------------
# 가짜 OpenAI SDK
# ---------------------------------------------------------------------------


def make_reply(payload=None, *, status="completed", reason=None, refusal=False, text=None):
    if refusal:
        content = [SimpleNamespace(type="refusal", refusal="I can't help with that.")]
    else:
        body = text if text is not None else json.dumps(payload, ensure_ascii=False)
        content = [SimpleNamespace(type="output_text", text=body)]
    output = [
        SimpleNamespace(type="reasoning", content=None),  # 생각 블록이 앞에 올 수 있다
        SimpleNamespace(type="message", content=content),
    ]
    return SimpleNamespace(
        status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        output=output if status == "completed" else [],
        model="gpt-test",
        usage=SimpleNamespace(input_tokens=100, output_tokens=200),
    )


class FakeResponses:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class FakeSdk:
    def __init__(self, replies):
        self.responses = FakeResponses(replies)
        self.closed = False

    async def close(self):
        self.closed = True


def openai_client(*replies, model="gpt-test", effort="low"):
    return extract.OpenAIClient(FakeSdk(replies), model=model, effort=effort)


def status_error(status: int, headers: dict | None = None) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status, request=request, headers=headers or {})
    cls = {429: openai.RateLimitError, 401: openai.AuthenticationError, 400: openai.BadRequestError}.get(
        status, openai.InternalServerError
    )
    return cls("error", response=response, body=None)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(extract, "_client", None)
    monkeypatch.delenv("EXTRACT_DEADLINE_SECONDS", raising=False)
    waits: list[float] = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(extract, "_sleep", fake_sleep)
    return waits


# ---------------------------------------------------------------------------
# 어느 AI를 쓸지
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env, expected",
    [
        ({}, None),
        ({"OPENAI_API_KEY": "sk-test"}, "openai"),
        ({"ANTHROPIC_API_KEY": "x"}, "anthropic"),
        ({"ANTHROPIC_AUTH_TOKEN": "x"}, "anthropic"),
        ({"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "x"}, "openai"),
        ({"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "x", "AI_PROVIDER": "anthropic"}, "anthropic"),
        ({"OPENAI_API_KEY": "sk-test", "ANTHROPIC_API_KEY": "x", "AI_PROVIDER": " OpenAI "}, "openai"),
        ({"ANTHROPIC_API_KEY": "x", "AI_PROVIDER": "openai"}, None),  # 고른 쪽 키가 없으면 쓰지 않는다
        ({"OPENAI_API_KEY": "sk-test", "AI_PROVIDER": "gemini"}, "openai"),  # 모르는 값이면 자동
        ({"OPENAI_API_KEY": ""}, None),
    ],
)
def test_ai_provider(monkeypatch, env, expected):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert extract.ai_provider() == expected
    assert extract.has_credentials() is (expected is not None)


def test_get_client_builds_openai_client_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-custom")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "medium")
    client = extract.get_client()
    assert isinstance(client, extract.OpenAIClient)
    assert isinstance(client.sdk, openai.AsyncOpenAI)
    assert client.sdk.max_retries == 0  # 재시도는 마감 시간 안에서 직접 한다
    assert (client.model, client.effort) == ("gpt-custom", "medium")
    assert extract.get_client() is client
    run(extract.aclose_client())
    assert extract._client is None


def test_openai_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = extract.get_client()
    assert (client.model, client.effort) == (extract.OPENAI_DEFAULT_MODEL, extract.OPENAI_DEFAULT_EFFORT)
    run(extract.aclose_client())


def test_no_key_is_503_without_calling(monkeypatch):
    with pytest.raises(ApiError) as e:
        extract.get_client()
    assert (e.value.code, e.value.status) == ("AI_FAILED", 503)


# ---------------------------------------------------------------------------
# 요청 형태
# ---------------------------------------------------------------------------


def test_registry_request_shape():
    client = openai_client(make_reply(REGISTRY_OK))
    result = run(extract.extract_registry(client, PDF_DOC))
    assert result.address_jibun == REGISTRY_OK["address_jibun"]
    (kwargs,) = client.sdk.responses.calls
    assert kwargs["model"] == "gpt-test"
    assert kwargs["instructions"].startswith("너는 한국 부동산 등기사항전부증명서")
    assert kwargs["store"] is False
    assert kwargs["reasoning"] == {"effort": "low"}
    assert kwargs["max_output_tokens"] == extract.MAX_TOKENS
    fmt = kwargs["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "registry"
    assert fmt["schema"] is extract.REGISTRY_SCHEMA
    (message,) = kwargs["input"]
    file_block, text_block = message["content"]
    assert file_block["type"] == "input_file"
    assert file_block["filename"] == "registry.pdf"
    assert file_block["file_data"].startswith("data:application/pdf;base64,")
    assert text_block == {"type": "input_text", "text": extract.REGISTRY_USER_TEXT}
    assert kwargs["timeout"] > 0


def test_contract_photo_is_sent_as_image():
    client = openai_client(make_reply(CONTRACT_OK))
    result = run(extract.extract_contract(client, PNG_DOC))
    assert result.deposit == 10000000
    image = client.sdk.responses.calls[0]["input"][0]["content"][0]
    assert image["type"] == "input_image"
    assert image["image_url"].startswith("data:image/png;base64,")
    assert image["detail"] == "high"
    assert client.sdk.responses.calls[0]["text"]["format"]["name"] == "contract"


def test_several_files_go_in_one_request_in_order():
    client = openai_client(make_reply(REGISTRY_OK))
    run(extract.extract_registry(client, [PDF_DOC, PNG_DOC, PDF_DOC]))
    (kwargs,) = client.sdk.responses.calls
    content = kwargs["input"][0]["content"]
    assert [b["type"] for b in content] == ["input_file", "input_image", "input_file", "input_text"]
    assert [content[0]["filename"], content[2]["filename"]] == ["registry-1.pdf", "registry-3.pdf"]
    assert content[-1]["text"] == extract.user_text_for(extract.REGISTRY_USER_TEXT, 3)


def test_extract_documents_reads_both_in_parallel():
    client = openai_client(make_reply(REGISTRY_OK), make_reply(CONTRACT_OK))
    result = run(extract.extract_documents(PDF_DOC, PNG_DOC, client=client))
    assert result.registry.building_name == "죽전빌라"
    assert result.contract is not None and result.contract.landlord_names == ["김민수"]
    assert len(client.sdk.responses.calls) == 2


# ---------------------------------------------------------------------------
# 응답 처리
# ---------------------------------------------------------------------------


def test_max_output_tokens_is_retried_once_with_larger_limit():
    client = openai_client(make_reply(status="incomplete", reason="max_output_tokens"), make_reply(REGISTRY_OK))
    run(extract.extract_registry(client, PDF_DOC))
    limits = [c["max_output_tokens"] for c in client.sdk.responses.calls]
    assert limits == [extract.MAX_TOKENS, extract.RETRY_MAX_TOKENS]


def test_max_output_tokens_twice_fails():
    client = openai_client(
        make_reply(status="incomplete", reason="max_output_tokens"),
        make_reply(status="incomplete", reason="max_output_tokens"),
    )
    with pytest.raises(ApiError) as e:
        run(extract.extract_registry(client, PDF_DOC))
    assert (e.value.code, e.value.reason) == ("AI_FAILED", "registry:max_tokens")


@pytest.mark.parametrize(
    "reply, reason",
    [
        (make_reply(refusal=True), "registry:refusal"),
        (make_reply(status="incomplete", reason="content_filter"), "registry:refusal"),
        (make_reply(status="failed"), "registry:status_failed"),
        (make_reply(text="not json"), "registry:invalid_json"),
        (make_reply({"is_registry": True, "gapgu": "not a list"}), "registry:schema_mismatch"),
    ],
)
def test_bad_replies_fail_without_retry(reply, reason):
    client = openai_client(reply)
    with pytest.raises(ApiError) as e:
        run(extract.extract_registry(client, PDF_DOC))
    assert (e.value.code, e.value.reason) == ("AI_FAILED", reason)
    assert len(client.sdk.responses.calls) == 1


def test_not_registry_and_not_contract():
    registry = copy.deepcopy(REGISTRY_OK) | {"is_registry": False}
    contract = copy.deepcopy(CONTRACT_OK) | {"is_contract": False}
    with pytest.raises(ApiError) as e:
        run(extract.extract_registry(openai_client(make_reply(registry)), PDF_DOC))
    assert e.value.code == "NOT_REGISTRY"
    with pytest.raises(ApiError) as e:
        run(extract.extract_contract(openai_client(make_reply(contract)), PNG_DOC))
    assert e.value.code == "NOT_CONTRACT"


def test_empty_message_is_no_text_block():
    reply = make_reply(REGISTRY_OK)
    reply.output = [SimpleNamespace(type="message", content=[])]
    with pytest.raises(ApiError) as e:
        run(extract.extract_registry(openai_client(reply), PDF_DOC))
    assert e.value.reason == "registry:no_text_block"


# ---------------------------------------------------------------------------
# 일시적 오류와 재시도
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        status_error(500),
        status_error(429, {"retry-after": "2"}),
        openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses")),
        openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/responses")),
    ],
)
def test_transient_error_is_retried_once(error, _isolated, caplog):
    caplog.set_level(logging.INFO)
    client = openai_client(error, make_reply(REGISTRY_OK))
    run(extract.extract_registry(client, PDF_DOC))
    assert len(client.sdk.responses.calls) == 2
    assert "openai retry doc=registry reason=" in caplog.text
    if isinstance(error, openai.RateLimitError):
        assert _isolated == [2.0]


@pytest.mark.parametrize("status, reason", [(400, "api_status_400"), (401, "api_status_401")])
def test_client_errors_are_not_retried(status, reason):
    client = openai_client(status_error(status), make_reply(REGISTRY_OK))
    with pytest.raises(ApiError) as e:
        run(extract.extract_registry(client, PDF_DOC))
    assert e.value.reason == f"registry:{reason}"
    assert len(client.sdk.responses.calls) == 1


def test_second_transient_error_fails():
    client = openai_client(status_error(503), status_error(503))
    with pytest.raises(ApiError) as e:
        run(extract.extract_registry(client, PDF_DOC))
    assert e.value.reason == "registry:api_status_503"


def test_logs_have_no_document_content(caplog):
    caplog.set_level(logging.INFO)
    run(extract.extract_documents(PDF_DOC, PNG_DOC, client=openai_client(make_reply(REGISTRY_OK), make_reply(CONTRACT_OK))))
    assert "openai doc=registry" in caplog.text and "model=gpt-test" in caplog.text
    for secret in ("김민수", "죽전", "800101", "base64"):
        assert secret not in caplog.text


def test_health_reports_ai_ready_with_openai_key(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with TestClient(app) as http:
        assert http.get("/api/health").json()["ai_ready"] is True


# ---------------------------------------------------------------------------
# 특약 칸의 "없음" 표시 (Claude·OpenAI 공통)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mark", ["없음", " 없음. ", "해당 없음", "특약 없음", "[특약사항] 없음", "-", "—", "無", "None", ""])
def test_no_term_mark_is_dropped(mark):
    payload = copy.deepcopy(CONTRACT_OK) | {"special_terms": [mark]}
    result = run(extract.extract_contract(openai_client(make_reply(payload)), PNG_DOC))
    assert result.special_terms == []


def test_real_terms_are_kept_next_to_marks():
    real = ["임대인은 잔금일 다음 날까지 저당권 등 담보권을 설정하지 않는다.", "반려동물 없음을 확인한다."]
    payload = copy.deepcopy(CONTRACT_OK) | {"special_terms": ["없음", *real]}
    result = run(extract.extract_contract(openai_client(make_reply(payload)), PNG_DOC))
    assert result.special_terms == real
