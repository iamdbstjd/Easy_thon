"""Claude로 등기부·계약서를 읽어 8.1·8.2 형식으로 옮긴다 (PRD 6장).

- AI는 읽기만 한다. 위험 판단은 app/rules가 한다.
- 등기부와 계약서는 병렬로 따로 호출한다.
- 두 문서를 합쳐 마감 시간(EXTRACT_DEADLINE_SECONDS, 기본 85초) 안에 끝내거나 AI_FAILED로 실패한다.
  화면은 90초에 포기하므로(PRD S3) 그보다 짧다. SDK 자동 재시도는 끄고, 일시적인 오류
  (연결·timeout, 5xx, 429)는 마감 안에서 문서마다 한 번만 직접 다시 부른다 (PRD 6장).
- 로그에는 문서 종류, stop_reason, 토큰 수, 걸린 시간만 남긴다 (문서 내용·이름·주소는 남기지 않는다).
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
import os
import time
from typing import Any, NamedTuple, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.errors import ApiError
from app.prompts import (
    CONTRACT_SCHEMA,
    CONTRACT_SYSTEM_PROMPT,
    CONTRACT_USER_TEXT,
    REGISTRY_SCHEMA,
    REGISTRY_SYSTEM_PROMPT,
    REGISTRY_USER_TEXT,
)
from app.schemas import ContractExtract, ExtractResponse, RegistryExtract
from app.uploads import DocInput

# ---------------------------------------------------------------------------
# 호출 설정 (정확도·속도를 재면서 조정한다)
# ---------------------------------------------------------------------------

MODEL = "claude-opus-5-5"
EFFORT = "medium"  # PRD 6장: medium에서 시작해 충분하면 low로 낮춘다
MAX_TOKENS = 16000
RETRY_MAX_TOKENS = 32000  # stop_reason == "max_tokens"면 한 번만 이 값으로 다시 부른다
BETAS = ["server-side-fallback-2026-07-01"]
FALLBACKS = "default"  # 거절되면 서버가 다른 모델로 다시 시도한다
DEFAULT_DEADLINE_SECONDS = 85.0  # 환경변수 EXTRACT_DEADLINE_SECONDS로 바꾼다. 두 문서를 합친 전체 상한.
RETRY_MIN_SECONDS = 10.0  # 다시 부르려면(일시적 오류·max_tokens) 마감까지 최소 이만큼 남아 있어야 한다
RETRY_BACKOFF_SECONDS = 1.0  # 일시적 오류 뒤 retry-after 헤더가 없을 때 기다리는 시간
CLIENT_TIMEOUT = 90.0  # 초. 마감 시간이 없는 호출의 HTTP 상한 (마감이 있으면 남은 시간을 쓴다)
CLIENT_MAX_RETRIES = 0  # SDK 자동 재시도는 끈다. 재시도가 마감 시간을 다 써 버리지 않게 한다.

KST = dt.timezone(dt.timedelta(hours=9))

logger = logging.getLogger("app.extract")

_client: Any = None  # anthropic.AsyncAnthropic. 처음 필요할 때 만든다.
_sleep = asyncio.sleep  # 재시도 전 대기. 테스트에서 바꿔 끼운다.

M = TypeVar("M", bound=BaseModel)


def has_credentials() -> bool:
    """Claude API 키가 환경변수에 있는지 (/api/health의 ai_ready)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


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
        if not has_credentials():
            raise ApiError.ai_unavailable()
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


def _source_block(doc: DocInput) -> dict[str, Any]:
    data = base64.standard_b64encode(doc.data).decode("ascii")
    return {"type": doc.kind, "source": {"type": "base64", "media_type": doc.media_type, "data": data}}


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


async def _wait_for_retry(kind: str, failure: _Failure, deadline: float | None) -> bool:
    """일시적 오류 뒤 다시 부를지 정한다. 기다린 뒤에도 마감까지 RETRY_MIN_SECONDS 이상 남아야 한다."""
    left = _seconds_left(deadline)
    if left - failure.wait < RETRY_MIN_SECONDS:
        logger.info("claude no retry doc=%s reason=%s wait=%.1fs left=%.1fs", kind, failure.reason, failure.wait, left)
        return False
    logger.info("claude retry doc=%s reason=%s wait=%.1fs left=%.1fs", kind, failure.reason, failure.wait, left)
    if failure.wait > 0:
        await _sleep(failure.wait)
    return True


async def _request_json(
    client: Any,
    *,
    kind: str,
    system: str,
    schema: dict[str, Any],
    doc: DocInput,
    user_text: str,
    deadline: float | None = None,
) -> Any:
    """Claude를 불러 JSON 응답을 파싱해 돌려준다. 실패하면 AI_FAILED.

    deadline(이벤트 루프 시각)이 있으면 요청 timeout을 남은 시간으로 둔다. 다시 부르는 경우는 둘이다.
    - 일시적 오류(연결·timeout, 5xx, 429): 한 번. retry-after를 기다린 뒤에도 RETRY_MIN_SECONDS 이상 남을 때만.
    - stop_reason == "max_tokens": 한도를 늘려 한 번. 남은 시간이 RETRY_MIN_SECONDS와 첫 시도 시간보다 길 때만.
    거절, 4xx(429 제외), JSON·스키마 오류는 다시 부르지 않는다.
    """
    content = [_source_block(doc), {"type": "text", "text": user_text}]
    max_tokens = MAX_TOKENS
    retried_after_error = False
    attempt = 0
    while True:
        attempt += 1
        started = time.perf_counter()
        try:
            resp = await client.beta.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                betas=BETAS,
                fallbacks=FALLBACKS,
                output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
                system=system,
                messages=[{"role": "user", "content": content}],
                timeout=_request_timeout(deadline),
            )
            failure = None
        except anthropic.APITimeoutError as e:
            failure = _Failure("timeout", True, _retry_wait_seconds(e))
        except anthropic.APIConnectionError as e:
            failure = _Failure("connection_error", True, _retry_wait_seconds(e))
        except anthropic.RateLimitError as e:
            failure = _Failure("rate_limited", _server_allows_retry(e), _retry_wait_seconds(e))
        except anthropic.APIStatusError as e:
            retryable = e.status_code >= 500 and _server_allows_retry(e)
            failure = _Failure(f"api_status_{e.status_code}", retryable, _retry_wait_seconds(e))
        except anthropic.AnthropicError as e:  # 인증 정보 해석 실패 등 그 밖의 SDK 오류
            failure = _Failure(f"sdk_{type(e).__name__}", False)
        if failure is not None:
            if failure.retryable and not retried_after_error and await _wait_for_retry(kind, failure, deadline):
                retried_after_error = True
                continue
            raise _ai_failed(kind, failure.reason)

        took = time.perf_counter() - started
        stop_reason = getattr(resp, "stop_reason", None)
        usage = getattr(resp, "usage", None)
        logger.info(
            "claude doc=%s attempt=%d stop=%s model=%s in_tokens=%s out_tokens=%s took=%.1fs",
            kind,
            attempt,
            stop_reason,
            getattr(resp, "model", None),
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
            took,
        )
        if stop_reason == "refusal":
            raise _ai_failed(kind, "refusal")
        if stop_reason == "max_tokens":
            if max_tokens == RETRY_MAX_TOKENS:
                raise _ai_failed(kind, "max_tokens")
            # 다시 부르면 첫 시도보다 오래 걸린다. 마감 전에 끝낼 수 없으면 바로 실패한다.
            if _seconds_left(deadline) < max(RETRY_MIN_SECONDS, took):
                raise _ai_failed(kind, "max_tokens_no_time")
            max_tokens = RETRY_MAX_TOKENS  # 한도를 늘려 한 번 더
            continue
        if stop_reason not in ("end_turn", "stop_sequence"):
            raise _ai_failed(kind, f"stop_{stop_reason}")

        # 생각(thinking)·fallback 블록이 앞에 올 수 있다. 첫 text 블록이 답이다.
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
        if text is None:
            raise _ai_failed(kind, "no_text_block")
        try:
            return json.loads(text)
        except ValueError:
            raise _ai_failed(kind, "invalid_json") from None


def _validate(model: type[M], data: Any, kind: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        # 오류 위치(필드 이름)만 남긴다. 값에는 개인정보가 있을 수 있다.
        locs = [".".join(str(p) for p in err["loc"]) for err in e.errors()[:5]]
        logger.warning("extract schema mismatch doc=%s errors=%d at=%s", kind, e.error_count(), locs)
        raise _ai_failed(kind, "schema_mismatch") from None


async def extract_registry(client: Any, doc: DocInput, *, deadline: float | None = None) -> RegistryExtract:
    """등기부를 읽는다. 등기부가 아니면 NOT_REGISTRY, 토지 등기부면 LAND_REGISTRY."""
    data = await _request_json(
        client,
        kind="registry",
        system=REGISTRY_SYSTEM_PROMPT,
        schema=REGISTRY_SCHEMA,
        doc=doc,
        user_text=REGISTRY_USER_TEXT,
        deadline=deadline,
    )
    registry = _validate(RegistryExtract, data, "registry")
    if not registry.is_registry:
        raise ApiError("NOT_REGISTRY", reason="registry:is_registry_false")
    if registry.registry_type == "토지":
        raise ApiError("LAND_REGISTRY", reason="registry:land")
    if registry.viewed_at is not None:
        # 열람 일시는 한국 시간으로 맞춘다 (시간대가 없으면 한국 시간으로 본다).
        viewed = registry.viewed_at
        viewed = viewed.replace(tzinfo=KST) if viewed.tzinfo is None else viewed.astimezone(KST)
        registry = registry.model_copy(update={"viewed_at": viewed})
    return registry


async def extract_contract(client: Any, doc: DocInput, *, deadline: float | None = None) -> ContractExtract:
    """계약서를 읽는다. 임대차 계약서가 아니면 NOT_CONTRACT."""
    data = await _request_json(
        client,
        kind="contract",
        system=CONTRACT_SYSTEM_PROMPT,
        schema=CONTRACT_SCHEMA,
        doc=doc,
        user_text=CONTRACT_USER_TEXT,
        deadline=deadline,
    )
    contract = _validate(ContractExtract, data, "contract")
    if not contract.is_contract:
        raise ApiError("NOT_CONTRACT", reason="contract:is_contract_false")
    return contract


async def _extract_both(
    client: Any, registry: DocInput, contract: DocInput | None, deadline: float
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


async def extract_documents(registry: DocInput, contract: DocInput | None, *, client: Any = None) -> ExtractResponse:
    """등기부(필수)와 계약서(선택)를 병렬로 읽는다.

    - 두 문서를 합쳐 deadline_seconds() 안에 끝내지 못하면 진행 중인 호출을 취소하고 AI_FAILED.
    - 등기부 오류를 계약서 오류보다 먼저 알린다. 등기부가 실패하면 계약서는 기다리지 않는다.
    """
    client = client if client is not None else get_client()
    budget = deadline_seconds()
    deadline = asyncio.get_running_loop().time() + budget
    started = time.perf_counter()
    try:
        registry_result, contract_result = await asyncio.wait_for(
            _extract_both(client, registry, contract, deadline), timeout=budget
        )
    except asyncio.TimeoutError:
        raise ApiError("AI_FAILED", reason=f"deadline_{budget:g}s") from None
    logger.info("extract done docs=%d took=%.1fs", 1 + (contract is not None), time.perf_counter() - started)
    return ExtractResponse(registry=registry_result, contract=contract_result)
