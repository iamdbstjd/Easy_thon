"""AI(OpenAI GPT 또는 Claude)로 등기부·계약서를 읽어 8.1·8.2 형식으로 옮긴다.

- AI는 읽기만 한다. 위험 판단은 app/rules가 한다.
- 어느 AI를 쓸지는 ai_provider()가 정한다 (AI_PROVIDER, 없으면 키가 있는 쪽. 둘 다 있으면 OpenAI).
  AI_PROVIDER는 openai·gpt, anthropic·claude를 받는다. 모르는 값이면 경고를 남기고 키로 고른다.
- 등기부와 계약서는 병렬로 따로 호출한다. 한 서류가 여러 파일(쪽마다 찍은 사진, 나눠 저장한 PDF)이면
  한 호출에 올린 순서대로 모두 넣고, 하나로 이어서 옮기게 한다.
- 두 문서를 합쳐 마감 시간(EXTRACT_DEADLINE_SECONDS, 기본 85초) 안에 끝내거나 AI_FAILED로 실패한다.
  화면은 90초에 포기하므로 그보다 짧다. 마감은 요청이 들어온 때부터 잰다 (대기열·업로드 시간 포함).
  SDK 자동 재시도는 끄고, 일시적인 오류(연결·timeout, 5xx, 429, 빈 응답 본문)는 마감 안에서
  문서마다 한 번만 직접 다시 부른다.
- 로그에는 문서 종류, 종료 사유, 토큰 수, 걸린 시간만 남긴다 (문서 내용·이름·주소는 남기지 않는다).
- AI 결과는 주민등록번호·전화번호를 먼저 가린 뒤 검사한다. 날짜·숫자 하나가 틀렸거나 글자 수가 넘치면
  문서 전체를 실패시키지 않고 그 칸만 비우거나 잘라 낸다 (등기부는 unreadable에 짧게 적는다).
- 테스트에서는 _client를 가짜 객체로 바꿔 끼운다 (네트워크를 쓰지 않는다).
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import logging
import math
import email.utils
import re
import os
import time
import typing
from typing import Any, Awaitable, Callable, NamedTuple, Sequence, TypeVar, Union

import anthropic
import openai
from pydantic import BaseModel, ValidationError

from app import privacy
from app.errors import ApiError
from app.prompts import (
    CONTRACT_SCHEMA,
    CONTRACT_SYSTEM_PROMPT,
    CONTRACT_USER_TEXT,
    REGISTRY_SCHEMA,
    REGISTRY_SYSTEM_PROMPT,
    REGISTRY_USER_TEXT,
    user_text_for,
)
from app.schemas import LINES_MAX, MAX_YEAR, MIN_YEAR, ContractExtract, ExtractResponse, RegistryExtract
from app.uploads import DocInput

# ---------------------------------------------------------------------------
# 호출 설정 (정확도·속도를 재면서 조정한다)
# ---------------------------------------------------------------------------

MODEL = "claude-opus-5-5"
EFFORT = "medium"  # medium에서 시작해 충분하면 low로 낮춘다
OPENAI_DEFAULT_MODEL = "gpt-5.5"  # 환경변수 OPENAI_MODEL로 바꾼다
OPENAI_DEFAULT_EFFORT = "low"  # 환경변수 OPENAI_REASONING_EFFORT로 바꾼다 (옮겨 적기라 낮게 둔다)
MAX_TOKENS = 16000
RETRY_MAX_TOKENS = 32000  # 출력 한도에 걸리면 한 번만 이 값으로 다시 부른다
BETAS = ["server-side-fallback-2026-07-01"]
FALLBACKS = "default"  # 거절되면 서버가 다른 모델로 다시 시도한다
DEFAULT_DEADLINE_SECONDS = 85.0  # 환경변수 EXTRACT_DEADLINE_SECONDS로 바꾼다. 두 문서를 합친 전체 상한.
RETRY_MIN_SECONDS = 10.0  # 다시 부르려면(일시적 오류·max_tokens) 마감까지 최소 이만큼 남아 있어야 한다
RETRY_BACKOFF_SECONDS = 1.0  # 일시적 오류 뒤 retry-after 헤더가 없을 때 기다리는 시간
CLIENT_TIMEOUT = 90.0  # 초. 마감 시간이 없는 호출의 HTTP 상한 (마감이 있으면 남은 시간을 쓴다)
CLIENT_MAX_RETRIES = 0  # SDK 자동 재시도는 끈다. 재시도가 마감 시간을 다 써 버리지 않게 한다.

KST = dt.timezone(dt.timedelta(hours=9))

logger = logging.getLogger("app.extract")

_client: Any = None  # anthropic.AsyncAnthropic 또는 OpenAIClient. 처음 필요할 때 만든다.
_sleep = asyncio.sleep  # 재시도 전 대기. 테스트에서 바꿔 끼운다.

M = TypeVar("M", bound=BaseModel)
T = TypeVar("T")

# 한 서류: 파일 하나 또는 올린 순서대로의 파일 목록
Docs = Union[DocInput, Sequence[DocInput]]


def _as_docs(doc: Docs) -> tuple[DocInput, ...]:
    return (doc,) if isinstance(doc, DocInput) else tuple(doc)


PROVIDER_ALIASES = {"openai": "openai", "gpt": "openai", "anthropic": "anthropic", "claude": "anthropic"}
_warned_settings: set[tuple[str, str]] = set()  # 같은 잘못된 설정 경고는 한 번만 남긴다


def _warn_once(name: str, value: str, fallback: str) -> None:
    if (name, value) not in _warned_settings:
        _warned_settings.add((name, value))
        logger.warning("invalid %s; using %s", name, fallback)  # 값 자체는 남기지 않는다 (키를 잘못 넣었을 수 있다)


def ai_provider() -> str | None:
    """서류를 읽을 AI: "openai" 또는 "anthropic". 쓸 수 있는 키가 없으면 None.

    AI_PROVIDER(openai·gpt, anthropic·claude)가 있으면 그쪽 키만 본다.
    없거나 모르는 값이면 OPENAI_API_KEY, ANTHROPIC_API_KEY 순서로 찾는다.
    """
    has_key = {
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
    }
    raw = os.environ.get("AI_PROVIDER", "").strip().lower()
    choice = PROVIDER_ALIASES.get(raw)
    if choice is not None:
        return choice if has_key[choice] else None
    if raw:
        _warn_once("AI_PROVIDER", raw, "the provider with an API key")
    return next((name for name, ok in has_key.items() if ok), None)


def _openai_efforts() -> frozenset[str]:
    """OpenAI SDK가 받는 reasoning effort 값 (SDK 타입에서 읽는다)."""
    try:
        from openai.types.shared import ReasoningEffort

        values = {
            value
            for arg in typing.get_args(ReasoningEffort)
            for value in typing.get_args(arg)
            if isinstance(value, str)
        }
    except Exception:
        values = set()
    return frozenset(values or {"minimal", "low", "medium", "high"})


OPENAI_EFFORTS = _openai_efforts()


def openai_effort(value: str | None = None) -> str:
    """value(없으면 OPENAI_REASONING_EFFORT)가 SDK가 받는 값이면 그대로, 아니면 경고를 남기고 기본값."""
    raw = (value if value is not None else os.environ.get("OPENAI_REASONING_EFFORT", "")).strip().lower()
    if not raw:
        return OPENAI_DEFAULT_EFFORT
    if raw not in OPENAI_EFFORTS:
        _warn_once("OPENAI_REASONING_EFFORT", raw, OPENAI_DEFAULT_EFFORT)
        return OPENAI_DEFAULT_EFFORT
    return raw


def openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", "").strip() or OPENAI_DEFAULT_MODEL


def describe_ai() -> dict[str, str]:
    """시작 로그용: 쓸 AI, 모델, effort. 키가 없으면 provider는 "-"."""
    provider = ai_provider()
    if provider == "openai":
        return {"provider": provider, "model": openai_model(), "effort": openai_effort()}
    if provider == "anthropic":
        return {"provider": provider, "model": MODEL, "effort": EFFORT}
    return {"provider": "-", "model": "-", "effort": "-"}


def has_credentials() -> bool:
    """AI API 키가 환경변수에 있는지 (/api/health의 ai_ready)."""
    return ai_provider() is not None


class OpenAIClient:
    """OpenAI SDK 클라이언트와 모델 설정. _request_json은 이 타입이면 OpenAI Responses API로 부른다."""

    def __init__(self, sdk: Any, *, model: str | None = None, effort: str | None = None) -> None:
        self.sdk = sdk
        self.model = model or openai_model()
        self.effort = openai_effort(effort)

    async def close(self) -> None:
        await self.sdk.close()


def deadline_seconds() -> float:
    """추출 전체 마감 시간(초). EXTRACT_DEADLINE_SECONDS가 없거나 잘못되면 기본값을 쓴다."""
    raw = os.environ.get("EXTRACT_DEADLINE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_DEADLINE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not (math.isfinite(value) and value > 0):
        logger.warning("invalid EXTRACT_DEADLINE_SECONDS; using %gs", DEFAULT_DEADLINE_SECONDS)
        return DEFAULT_DEADLINE_SECONDS
    return value


def _seconds_left(deadline: float | None) -> float:
    """마감까지 남은 초 (deadline은 이벤트 루프 시각). 마감이 없으면 무한대."""
    if deadline is None:
        return math.inf
    return deadline - asyncio.get_running_loop().time()


def _request_timeout(deadline: float | None) -> float:
    """HTTP 요청 하나의 timeout: 남은 시간(최소 1초). 마감이 없으면 CLIENT_TIMEOUT."""
    left = _seconds_left(deadline)
    return CLIENT_TIMEOUT if math.isinf(left) else max(1.0, left)


def get_client() -> Any:
    """클라이언트를 돌려준다. 키가 없으면 API를 부르지 않고 AI_FAILED(503)를 낸다."""
    global _client
    if _client is None:
        provider = ai_provider()
        if provider is None:
            raise ApiError.ai_unavailable()
        if provider == "openai":
            _client = OpenAIClient(openai.AsyncOpenAI(timeout=CLIENT_TIMEOUT, max_retries=CLIENT_MAX_RETRIES))
            return _client
        # 기본값이 아닌 timeout을 꼭 둔다. 클라이언트가 기본 timeout이고 요청에도 timeout이 없으면
        # SDK가 max_tokens=32000 비스트리밍 재시도를 "Streaming is required" ValueError로 막는다.
        # (요청마다 남은 시간을 timeout으로 넘기지만, 이 값은 그 밖의 호출을 위한 안전장치다.)
        _client = anthropic.AsyncAnthropic(timeout=CLIENT_TIMEOUT, max_retries=CLIENT_MAX_RETRIES)
    return _client


async def aclose_client() -> None:
    """서버 종료 때 연결을 닫는다."""
    global _client
    client, _client = _client, None
    close = getattr(client, "close", None)
    if close is not None:
        await close()


# ---------------------------------------------------------------------------
# 호출과 응답 처리
# ---------------------------------------------------------------------------


def _b64(doc: DocInput) -> str:
    return base64.standard_b64encode(doc.data).decode("ascii")


def _source_block(doc: DocInput) -> dict[str, Any]:
    """Claude용 문서 블록 (document 또는 image)."""
    return {"type": doc.kind, "source": {"type": "base64", "media_type": doc.media_type, "data": _b64(doc)}}


def _openai_source_block(doc: DocInput, kind: str, index: int | None = None) -> dict[str, Any]:
    """OpenAI용 문서 블록. PDF는 input_file, 사진은 input_image (손글씨·작은 글자 때문에 high).

    파일이 여러 개면 index(1부터)를 파일 이름에 붙인다 (registry-1.pdf, registry-2.pdf …).
    """
    data_url = f"data:{doc.media_type};base64,{_b64(doc)}"
    if doc.kind == "image":
        return {"type": "input_image", "image_url": data_url, "detail": "high"}
    filename = f"{kind}.pdf" if index is None else f"{kind}-{index}.pdf"
    return {"type": "input_file", "filename": filename, "file_data": data_url}


def _openai_source_blocks(docs: tuple[DocInput, ...], kind: str) -> list[dict[str, Any]]:
    if len(docs) == 1:
        return [_openai_source_block(docs[0], kind)]
    return [_openai_source_block(doc, kind, i) for i, doc in enumerate(docs, 1)]


def _ai_failed(kind: str, reason: str) -> ApiError:
    return ApiError("AI_FAILED", reason=f"{kind}:{reason}")


class _Failure(NamedTuple):
    """SDK 오류 요약. reason은 로그용(상태 코드 포함, 개인정보 없음)."""

    reason: str
    retryable: bool
    wait: float = 0.0


def _retry_wait_seconds(error: Exception) -> float:
    """다시 부르기 전 기다릴 초: retry-after-ms·retry-after 헤더, 없으면 RETRY_BACKOFF_SECONDS."""
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is not None:
        try:
            if (ms := headers.get("retry-after-ms")) is not None:
                return max(0.0, float(ms) / 1000)
            if (value := headers.get("retry-after")) is not None:
                try:
                    return max(0.0, float(value))
                except ValueError:  # HTTP 날짜 형식
                    when = email.utils.parsedate_to_datetime(value)
                    return max(0.0, (when - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            pass
    return RETRY_BACKOFF_SECONDS


def _server_allows_retry(error: Exception) -> bool:
    headers = getattr(getattr(error, "response", None), "headers", None)
    return headers is None or headers.get("x-should-retry", "").lower() != "false"


async def _wait_for_retry(name: str, kind: str, failure: _Failure, deadline: float | None) -> bool:
    """일시적 오류 뒤 다시 부를지 정한다. 기다린 뒤에도 마감까지 RETRY_MIN_SECONDS 이상 남아야 한다."""
    left = _seconds_left(deadline)
    if left - failure.wait < RETRY_MIN_SECONDS:
        logger.info("%s no retry doc=%s reason=%s wait=%.1fs left=%.1fs", name, kind, failure.reason, failure.wait, left)
        return False
    logger.info("%s retry doc=%s reason=%s wait=%.1fs left=%.1fs", name, kind, failure.reason, failure.wait, left)
    if failure.wait > 0:
        await _sleep(failure.wait)
    return True


class _Reply(NamedTuple):
    """AI 응답 요약. stop은 "ok", "max_tokens", "refusal" 또는 그 밖의 실패 사유다."""

    stop: str
    text: str | None
    raw_stop: Any  # 로그용 원래 종료 사유
    model: Any
    usage: Any


async def _call_claude(
    client: Any, *, kind: str, system: str, schema: dict[str, Any], docs: tuple[DocInput, ...], user_text: str,
    max_tokens: int, timeout: float,
) -> _Reply:
    resp = await client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        betas=BETAS,
        fallbacks=FALLBACKS,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
        system=system,
        messages=[
            {"role": "user", "content": [*(_source_block(doc) for doc in docs), {"type": "text", "text": user_text}]}
        ],
        timeout=timeout,
    )
    stop_reason = getattr(resp, "stop_reason", None)
    text = None
    if stop_reason in ("end_turn", "stop_sequence"):
        stop = "ok"
        # 생각(thinking)·fallback 블록이 앞에 올 수 있다. 첫 text 블록이 답이다.
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    elif stop_reason in ("max_tokens", "refusal"):
        stop = stop_reason
    else:
        stop = f"stop_{stop_reason}"
    return _Reply(stop, text, stop_reason, getattr(resp, "model", None), getattr(resp, "usage", None))


async def _call_openai(
    client: OpenAIClient, *, kind: str, system: str, schema: dict[str, Any], docs: tuple[DocInput, ...],
    user_text: str, max_tokens: int, timeout: float,
) -> _Reply:
    resp = await client.sdk.responses.create(
        model=client.model,
        instructions=system,
        input=[
            {
                "role": "user",
                "content": [*_openai_source_blocks(docs, kind), {"type": "input_text", "text": user_text}],
            }
        ],
        text={"format": {"type": "json_schema", "name": kind, "schema": schema, "strict": True}},
        reasoning={"effort": client.effort},
        max_output_tokens=max_tokens,
        store=False,  # 서류 내용을 OpenAI 쪽에 남기지 않는다
        timeout=timeout,
    )
    status = getattr(resp, "status", None)
    reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
    raw_stop = status if reason is None else f"{status}:{reason}"
    text = None
    if status == "completed":
        parts = [c for item in (getattr(resp, "output", None) or []) for c in (getattr(item, "content", None) or [])]
        if any(getattr(c, "type", None) == "refusal" for c in parts):
            stop = "refusal"
        else:
            stop = "ok"
            # 답이 output_text 여러 조각으로 나뉘어 올 수 있다. 모두 이어 붙인다.
            texts = [c.text for c in parts if getattr(c, "type", None) == "output_text" and isinstance(c.text, str)]
            text = "".join(texts) if texts else None
    elif status == "incomplete" and reason == "max_output_tokens":
        stop = "max_tokens"
    elif status == "incomplete" and reason == "content_filter":
        stop = "refusal"
    else:
        stop = f"status_{status}" + (f"_{reason}" if reason else "")
    return _Reply(stop, text, raw_stop, getattr(resp, "model", None), getattr(resp, "usage", None))


async def _request_json(
    client: Any,
    *,
    kind: str,
    system: str,
    schema: dict[str, Any],
    doc: Docs,
    user_text: str,
    deadline: float | None = None,
) -> Any:
    """AI를 불러 JSON 응답을 파싱해 돌려준다. 실패하면 AI_FAILED. client가 OpenAIClient면 OpenAI, 아니면 Claude.

    doc은 파일 하나 또는 한 서류를 이루는 파일 목록이다 (올린 순서대로 한 메시지에 넣는다).

    deadline(이벤트 루프 시각)이 있으면 요청 timeout을 남은 시간으로 둔다. 다시 부르는 경우는 둘이다.
    - 일시적 오류(연결·timeout, 5xx, 429): 한 번. retry-after를 기다린 뒤에도 RETRY_MIN_SECONDS 이상 남을 때만.
    - 출력 한도(max_tokens): 한도를 늘려 한 번. 남은 시간이 RETRY_MIN_SECONDS와 첫 시도 시간보다 길 때만.
    거절, 4xx(429 제외), JSON·스키마 오류는 다시 부르지 않는다.
    """
    call = _call_openai if isinstance(client, OpenAIClient) else _call_claude
    name = "openai" if isinstance(client, OpenAIClient) else "claude"
    docs = _as_docs(doc)
    max_tokens = MAX_TOKENS
    retried_after_error = False
    attempt = 0
    while True:
        attempt += 1
        started = time.perf_counter()
        try:
            reply = await call(
                client, kind=kind, system=system, schema=schema, docs=docs, user_text=user_text,
                max_tokens=max_tokens, timeout=_request_timeout(deadline),
            )
            failure = None
        except (anthropic.APITimeoutError, openai.APITimeoutError) as e:
            failure = _Failure("timeout", True, _retry_wait_seconds(e))
        except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
            failure = _Failure("connection_error", True, _retry_wait_seconds(e))
        except (anthropic.RateLimitError, openai.RateLimitError) as e:
            failure = _Failure("rate_limited", _server_allows_retry(e), _retry_wait_seconds(e))
        except (anthropic.APIStatusError, openai.APIStatusError) as e:
            retryable = e.status_code >= 500 and _server_allows_retry(e)
            failure = _Failure(f"api_status_{e.status_code}", retryable, _retry_wait_seconds(e))
        except (anthropic.AnthropicError, openai.OpenAIError) as e:  # 인증 정보 해석 실패 등 그 밖의 SDK 오류
            failure = _Failure(f"sdk_{type(e).__name__}", False)
        except ValueError:
            # 200 응답의 본문이 비었거나 잘려 SDK가 JSON을 풀지 못했다 (json.JSONDecodeError). 일시적인 문제로 본다.
            failure = _Failure("bad_response", True, RETRY_BACKOFF_SECONDS)
        if failure is not None:
            if failure.retryable and not retried_after_error and await _wait_for_retry(name, kind, failure, deadline):
                retried_after_error = True
                continue
            raise _ai_failed(kind, failure.reason)

        took = time.perf_counter() - started
        logger.info(
            "%s doc=%s files=%d attempt=%d stop=%s model=%s in_tokens=%s out_tokens=%s took=%.1fs",
            name,
            kind,
            len(docs),
            attempt,
            reply.raw_stop,
            reply.model,
            getattr(reply.usage, "input_tokens", None),
            getattr(reply.usage, "output_tokens", None),
            took,
        )
        if reply.stop == "refusal":
            raise _ai_failed(kind, "refusal")
        if reply.stop == "max_tokens":
            if max_tokens == RETRY_MAX_TOKENS:
                raise _ai_failed(kind, "max_tokens")
            # 다시 부르면 첫 시도보다 오래 걸린다. 마감 전에 끝낼 수 없으면 바로 실패한다.
            if _seconds_left(deadline) < max(RETRY_MIN_SECONDS, took):
                raise _ai_failed(kind, "max_tokens_no_time")
            max_tokens = RETRY_MAX_TOKENS  # 한도를 늘려 한 번 더
            continue
        if reply.stop != "ok":
            raise _ai_failed(kind, reply.stop)
        if reply.text is None:
            raise _ai_failed(kind, "no_text_block")
        try:
            return json.loads(reply.text)
        except ValueError:
            raise _ai_failed(kind, "invalid_json") from None


# 값이 틀리면 문서 전체를 실패시키지 않고 비우는 칸 (모두 Optional이다). 등기부는 unreadable에 적을 이름.
_NULLABLE_FIELDS = {
    "received_at": "접수일",
    "viewed_at": "열람 일시",
    "amount": "금액",
    "page": "페이지 번호",
    "area_m2": "전용면적",
    "contract_date": "계약일",
    "balance_date": "잔금일",
    "move_in_date": "입주일",
    "lease_end": "계약 종료일",
    "deposit": "보증금",
    "monthly_rent": "월세",
}
_SECTION_NAMES = {"gapgu": "갑구", "eulgu": "을구"}
# 잘라 낸 칸을 unreadable에 적을 이름
_CUT_LABELS = {
    "gapgu": "갑구 항목",
    "eulgu": "을구 항목",
    "source_text": "원문",
    "holders": "권리자",
    "purpose": "등기목적",
    "cause": "등기원인",
    "rank": "순위번호",
    "address_jibun": "지번 주소",
    "address_road": "도로명 주소",
    "building_name": "건물 이름",
    "dong": "동",
    "ho": "호",
    "floor": "층",
    "building_use_lines": "건물 표시",
}
_REPAIR_ROUNDS = 3  # 고친 뒤 메모를 붙이면 목록이 넘칠 수 있어 몇 번 더 본다


def _loc_text(loc: tuple) -> str:
    return ".".join(str(p) for p in loc)


def _container(data: Any, loc: tuple) -> tuple[Any, Any] | None:
    """loc의 마지막 칸을 담은 dict·list와 그 키. 없으면 None."""
    if not loc:
        return None
    node = data
    for part in loc[:-1]:
        if isinstance(node, dict) and isinstance(part, str) and part in node:
            node = node[part]
        elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
            node = node[part]
        else:
            return None
    key = loc[-1]
    if isinstance(node, dict) and isinstance(key, str) and key in node:
        return node, key
    if isinstance(node, list) and isinstance(key, int) and 0 <= key < len(node):
        return node, key
    return None


def _has_final_consonant(word: str) -> bool:
    last = word[-1]
    return "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0


def _object_particle(word: str) -> str:
    """받침이 있으면 "을", 없으면 "를"."""
    return "을" if _has_final_consonant(word) else "를"


def _subject_particle(word: str) -> str:
    """받침이 있으면 "이", 없으면 "가"."""
    return "이" if _has_final_consonant(word) else "가"


def _entry_label(data: dict, loc: tuple) -> str:
    """갑구·을구 항목 안의 위치면 "갑구 3번 " 같은 앞말, 아니면 빈 문자열."""
    if len(loc) < 3 or loc[0] not in _SECTION_NAMES or not isinstance(loc[1], int):
        return ""
    rank = data[loc[0]][loc[1]].get("rank") if isinstance(data[loc[0]][loc[1]], dict) else None
    label = rank.strip() if isinstance(rank, str) and 0 < len(rank.strip()) <= 10 else f"{loc[1] + 1}번째 항목"
    label += "번" if label[-1].isdigit() else ""
    return f"{_SECTION_NAMES[loc[0]]} {label} "


def _unreadable_note(data: dict, loc: tuple) -> str:
    """비운 칸을 사용자에게 알리는 짧은 메모 (값은 적지 않는다). 예: "갑구 3번 접수일을 읽지 못함"."""
    field = _NULLABLE_FIELDS[loc[-1]]
    return f"{_entry_label(data, loc)}{field}{_object_particle(field)} 읽지 못함"


def _cut_note(data: dict, loc: tuple, value: Any, limit: int) -> str | None:
    """잘라 낸 칸을 알리는 메모. 예: "갑구 항목이 많아 앞의 500개만 옮김", "갑구 3번 원문이 길어 앞부분만 옮김"."""
    if loc[0] == "unreadable":  # 읽지 못한 부분 목록 자체는 알리지 않는다
        return None
    key = loc[-1] if isinstance(loc[-1], str) else loc[-2] if len(loc) >= 2 else None
    label = _CUT_LABELS.get(key) if isinstance(key, str) else None
    if label is None:
        return None
    where = _entry_label(data, loc)
    if isinstance(value, list):
        return f"{where}{label}{_subject_particle(label)} 많아 앞의 {limit}개만 옮김"
    return f"{where}{label}{_subject_particle(label)} 길어 앞부분만 옮김"


def _repair(data: Any, errors: list[dict], kind: str) -> list[str] | None:
    """고칠 수 있는 오류만 고친다 (data를 바꾼다). 하나라도 못 고치면 None, 다 고치면 unreadable 메모 목록.

    - 글자 수·목록 길이가 넘치면 상한까지 자른다 (등기부는 무엇을 잘랐는지 적는다).
    - 날짜·숫자 칸(_NULLABLE_FIELDS) 값이 틀리면(없는 날짜, 범위 밖 등) 그 칸을 비운다.
    """
    notes: list[str] = []
    # 목록을 자르기 전에 그 안의 항목부터 고친다 (깊은 위치 먼저).
    for err in sorted(errors, key=lambda e: len(e["loc"]), reverse=True):
        loc, etype = tuple(err["loc"]), err["type"]
        found = _container(data, loc)
        if found is None:
            return None
        node, key = found
        value = node[key]
        limit = (err.get("ctx") or {}).get("max_length")
        if etype in ("string_too_long", "too_long") and isinstance(limit, int) and isinstance(value, (str, list)):
            node[key] = value[:limit]
            note = _cut_note(data, loc, value, limit) if kind == "registry" else None
        elif isinstance(key, str) and key in _NULLABLE_FIELDS and isinstance(node, dict):
            node[key] = None
            note = _unreadable_note(data, loc) if kind == "registry" else None
        else:
            return None
        if note is not None and note not in notes:
            notes.append(note)
    return notes


def _with_notes(unreadable: list, notes: list[str]) -> list:
    """unreadable 끝에 메모를 붙인다. 상한(LINES_MAX)을 넘으면 메모가 들어갈 자리를 남기고 앞의 것만 둔다."""
    notes = [note for note in dict.fromkeys(notes) if note not in unreadable][:LINES_MAX]
    return unreadable[: LINES_MAX - len(notes)] + notes


def _validate(model: type[M], data: Any, kind: str) -> M:
    """AI 결과를 모델로 검사한다. 주민등록번호·전화번호는 먼저 가리고, 고칠 수 있는 오류는 고친다."""
    data = privacy.mask_value(data)  # 새 사본이라 고쳐도 원래 값은 그대로다
    for _ in range(_REPAIR_ROUNDS):
        try:
            return model.model_validate(data)
        except ValidationError as e:
            errors = e.errors(include_url=False, include_input=False)
            # 오류 위치(필드 이름)만 남긴다. 값에는 개인정보가 있을 수 있다.
            locs = [_loc_text(err["loc"]) for err in errors[:5]]
            notes = _repair(data, errors, kind)
            if notes is None:
                logger.warning("extract schema mismatch doc=%s errors=%d at=%s", kind, len(errors), locs)
                raise _ai_failed(kind, "schema_mismatch") from None
            logger.info("extract repaired doc=%s fixed=%d at=%s", kind, len(errors), locs)
            if notes and isinstance(data.get("unreadable", []), list):
                data["unreadable"] = _with_notes(data.get("unreadable", []), notes)
    try:
        return model.model_validate(data)
    except ValidationError as e:
        logger.warning("extract schema mismatch doc=%s errors=%d after repair", kind, e.error_count())
        raise _ai_failed(kind, "schema_mismatch") from None


async def extract_registry(client: Any, doc: Docs, *, deadline: float | None = None) -> RegistryExtract:
    """등기부(파일 하나 또는 여러 개)를 읽는다. 등기부가 아니면 NOT_REGISTRY, 토지 등기부면 LAND_REGISTRY."""
    docs = _as_docs(doc)
    data = await _request_json(
        client,
        kind="registry",
        system=REGISTRY_SYSTEM_PROMPT,
        schema=REGISTRY_SCHEMA,
        doc=docs,
        user_text=user_text_for(REGISTRY_USER_TEXT, len(docs)),
        deadline=deadline,
    )
    registry = _validate(RegistryExtract, data, "registry")
    if not registry.is_registry:
        raise ApiError("NOT_REGISTRY", reason="registry:is_registry_false")
    if registry.registry_type == "토지":
        raise ApiError("LAND_REGISTRY", reason="registry:land")
    if registry.viewed_at is not None:
        # 열람 일시는 한국 시간으로 맞춘다 (시간대가 없으면 한국 시간으로 본다).
        # 바꾼 뒤 허용 범위(연도)를 벗어나면(예: 2100-12-31T23:30-12:00 → 2101년) 비우고 적는다.
        viewed = registry.viewed_at
        viewed = viewed.replace(tzinfo=KST) if viewed.tzinfo is None else viewed.astimezone(KST)
        if MIN_YEAR <= viewed.year <= MAX_YEAR:
            registry = registry.model_copy(update={"viewed_at": viewed})
        else:
            note = _unreadable_note({}, ("viewed_at",))
            registry = RegistryExtract.model_validate(
                registry.model_dump() | {"viewed_at": None, "unreadable": _with_notes(registry.unreadable, [note])}
            )
    return registry


# 특약 칸에 "없음"처럼 특약이 없다는 표시만 있을 때 AI가 그 글자를 특약으로 옮기는 경우가 있다.
# 구두점·괄호·공백·'/'를 빼고 비교한다 ("특약사항: 없음" → "특약사항없음", "N/A" → "na").
_NO_TERM_MARKS = {
    "없음", "없다", "없습니다", "없슴", "해당없음", "해당사항없음", "해당없습니다", "해당사항없습니다",
    "특약없음", "특약사항없음", "특약없습니다", "특약사항없습니다", "별도특약없음", "기타특약없음",
    "이하여백", "無", "none", "na", "nil",
}
_TERM_NUMBER = re.compile(r"^\s*(?:\d{1,2}|[①-⑳])\s*[.)]?\s*")  # 앞의 "1." "①" 같은 번호


def _is_no_term_mark(term: str) -> bool:
    key = re.sub(r"[\s.,·:;()\[\]{}<>\-—–~/\\*•'\"]", "", _TERM_NUMBER.sub("", term)).lower()
    return key == "" or key in _NO_TERM_MARKS


async def extract_contract(client: Any, doc: Docs, *, deadline: float | None = None) -> ContractExtract:
    """계약서(파일 하나 또는 여러 개)를 읽는다. 임대차 계약서가 아니면 NOT_CONTRACT."""
    docs = _as_docs(doc)
    data = await _request_json(
        client,
        kind="contract",
        system=CONTRACT_SYSTEM_PROMPT,
        schema=CONTRACT_SCHEMA,
        doc=docs,
        user_text=user_text_for(CONTRACT_USER_TEXT, len(docs)),
        deadline=deadline,
    )
    contract = _validate(ContractExtract, data, "contract")
    if not contract.is_contract:
        raise ApiError("NOT_CONTRACT", reason="contract:is_contract_false")
    terms = [t for t in contract.special_terms if not _is_no_term_mark(t)]
    if len(terms) != len(contract.special_terms):
        contract = contract.model_copy(update={"special_terms": terms})
    return contract


async def _extract_both(
    client: Any, registry: Docs, contract: Docs | None, deadline: float
) -> tuple[RegistryExtract, ContractExtract | None]:
    """두 문서를 동시에 읽는다. 등기부 결과를 먼저 기다려 등기부 오류를 먼저 알린다."""
    tasks = [asyncio.create_task(extract_registry(client, registry, deadline=deadline))]
    if contract is not None:
        tasks.append(asyncio.create_task(extract_contract(client, contract, deadline=deadline)))
    try:
        results = [await task for task in tasks]
    finally:
        # 하나가 실패하거나 마감에 걸리면 나머지 호출을 취소하고, 남은 예외를 거둔다.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return results[0], (results[1] if contract is not None else None)  # type: ignore[return-value]


async def _with_deadline(work: Callable[[float], Awaitable[T]], started_at: float | None = None) -> T:
    """work(deadline)를 마감 시간(deadline_seconds) 안에 끝낸다. 넘으면 진행 중인 호출을 취소하고 AI_FAILED.

    started_at(이벤트 루프 시각)이 있으면 그때부터 잰다. 요청이 대기열에서 기다리거나 업로드에 쓴 시간도
    마감에 넣어야 화면의 90초 시계보다 먼저 끝난다.
    """
    budget = deadline_seconds()
    now = asyncio.get_running_loop().time()
    deadline = (now if started_at is None else min(started_at, now)) + budget
    left = deadline - now
    if left <= 0:
        raise ApiError("AI_FAILED", reason=f"deadline_{budget:g}s")
    try:
        return await asyncio.wait_for(work(deadline), timeout=left)
    except asyncio.TimeoutError:
        raise ApiError("AI_FAILED", reason=f"deadline_{budget:g}s") from None


async def extract_documents(
    registry: Docs, contract: Docs | None, *, client: Any = None, started_at: float | None = None
) -> ExtractResponse:
    """등기부(필수)와 계약서(선택)를 병렬로 읽는다. 각각 파일 하나 또는 올린 순서대로의 파일 목록이다.

    - 두 문서를 합쳐 deadline_seconds() 안에(started_at이 있으면 그때부터) 끝내지 못하면
      진행 중인 호출을 취소하고 AI_FAILED.
    - 등기부 오류를 계약서 오류보다 먼저 알린다. 등기부가 실패하면 계약서는 기다리지 않는다.
    """
    client = client if client is not None else get_client()
    started = time.perf_counter()
    registry_docs = _as_docs(registry)
    contract_docs = _as_docs(contract) if contract is not None else None
    registry_result, contract_result = await _with_deadline(
        lambda deadline: _extract_both(client, registry_docs, contract_docs, deadline), started_at
    )
    files = len(registry_docs) + (len(contract_docs) if contract_docs else 0)
    logger.info(
        "extract done docs=%d files=%d took=%.1fs", 1 + (contract is not None), files, time.perf_counter() - started
    )
    return ExtractResponse(registry=registry_result, contract=contract_result)


async def extract_contract_only(
    contract: Docs, *, client: Any = None, started_at: float | None = None
) -> ContractExtract:
    """계약서만 읽는다 (수정된 계약서, 파일 하나 또는 여러 개). 호출·재시도·마감·NOT_CONTRACT는 extract_documents와 같다."""
    client = client if client is not None else get_client()
    started = time.perf_counter()
    docs = _as_docs(contract)
    result = await _with_deadline(lambda deadline: extract_contract(client, docs, deadline=deadline), started_at)
    logger.info("extract done docs=1 files=%d contract_only took=%.1fs", len(docs), time.perf_counter() - started)
    return result
