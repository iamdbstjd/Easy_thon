"""FastAPI 앱.

실행 (backend 폴더에서): .venv/bin/uvicorn app.main:app --port 8000
API 키 없이도 /api/health, /api/demo, /api/check, /api/checklist.ics는 동작한다.
"""

import asyncio
import datetime as dt
import os
import re
import time
import traceback
import uuid
import weakref
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypeVar, Union

from app import config

# 다른 모듈보다 먼저 .env를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다.
_ENV_KEYS_LOADED = config.load_env_file()

from fastapi import FastAPI, File, Request, UploadFile  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from starlette.datastructures import MutableHeaders  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402
from starlette.formparsers import MultiPartParser  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from app import extract, ics, pdf_sandbox, privacy, uploads  # noqa: E402
from app import market as market_api  # noqa: E402
from app.errors import DOCUMENTS, ApiError, api_error_handler, api_error_response, error_response  # noqa: E402
from app.rules import build_report  # noqa: E402
from app.schemas import (  # noqa: E402
    CheckRequest,
    CompareReport,
    CompareRequest,
    ContractExtract,
    ErrorResponse,
    ExtractResponse,
    HealthResponse,
    IcsRequest,
    MarketInsight,
    RecheckReport,
    RecheckRequest,
    Report,
)

logger = config.setup_logging()

KST = dt.timezone(dt.timedelta(hours=9))
DEMO_DIR: Path = config.BACKEND_DIR / "demo"  # 테스트에서 바꿔 끼울 수 있다
DEMO_SCENARIOS = ("A", "B", "C")
RECHECK_DEMO = "recheck-A"  # 계약 후 재확인 예시
COMPARE_DEMO = "compare-C"  # 수정 전·후 비교 예시
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]  # 개발용 (Vite)
EXTRACT_PATH = "/api/extract"
EXTRACT_CONTRACT_PATH = "/api/extract/contract"  # 수정된 계약서만
# 업로드 경로별 요청 본문 상한. 넘으면 본문을 더 읽지 않고 UNSUPPORTED_FILE.
UPLOAD_REQUEST_LIMITS = {
    EXTRACT_PATH: uploads.MAX_REQUEST_BYTES,
    EXTRACT_CONTRACT_PATH: uploads.MAX_REQUEST_BYTES,
}
# 그 밖의 본문(JSON) 상한. 화면이 보내는 검사 입력은 수십 KB다. 넘으면 413.
JSON_REQUEST_LIMIT = 1024 * 1024
BODY_METHODS = ("POST", "PUT", "PATCH", "DELETE")  # 본문을 미리 읽어 상한을 거는 메서드
BODY_IDLE_SECONDS = 30.0  # 본문 조각 사이에 이만큼 아무것도 오지 않으면 끊는다 (408)
JSON_BODY_SECONDS = 30.0  # JSON 본문 전체를 받는 시간 상한
# 업로드는 자리를 잡은 채로 받으므로, 아주 느리게 보내는 연결이 자리를 오래 붙잡지 못하게 한다.
# 유예 시간 뒤 평균 속도가 이보다 느리거나, 알려 준 길이를 마감 안에 다 받을 수 없는 속도면 끊는다.
UPLOAD_MIN_BYTES_PER_SECOND = 16 * 1024
UPLOAD_RATE_GRACE_SECONDS = 10.0
# 서류 읽기는 두 단계로 자리를 잡는다. 기다리는 시간은 요청이 들어온 때부터 마감(85초)까지다.
# - 업로드 자리: 본문을 읽기 전에 잡고, AI 자리를 잡으면 놓는다. 메모리에 올라가는 업로드 수를 묶는다.
# - AI 자리: 파일 검사를 마친 뒤에 잡는다. 동시에 부르는 AI 호출 수(워커당)를 묶는다.
# 메모리에 서류를 들고 있는 요청은 많아야 UPLOAD_SLOTS + AI_SLOTS개다.
UPLOAD_SLOTS = 6
AI_SLOTS = 4
DISCONNECT_POLL_SECONDS = 0.5  # 추출 중 클라이언트 연결 끊김을 확인하는 간격
MAX_VALIDATION_ERRORS = 20  # 422 응답에 담는 오류 수
STARTED_AT = "started_at"  # scope["state"]에 넣는 요청 시작 시각 (이벤트 루프 시각)
# 공개 배포에서 같은 IP가 짧은 시간에 서류 읽기를 너무 많이 하지 못하게 한다 (OpenAI 비용·남용 방지).
# 환경변수 RATE_LIMIT=1일 때만 켠다 (Dockerfile). 개발·테스트에서는 꺼져 있다.
# 묶음 이름 → (경로들, 시간당 횟수). 본문을 읽기 전에 거절한다.
RATE_LIMITS = {
    "extract": ((EXTRACT_PATH, EXTRACT_CONTRACT_PATH), 20),
    "market": (("/api/market",), 60),
}
RATE_WINDOW_SECONDS = 3600.0
_rate_hits: dict[tuple[str, str], deque] = {}
UPLOAD_SLOT = "release_upload_slot"  # scope["state"]에 넣는 업로드 자리 반납 함수

# multipart 파일을 디스크 임시 파일로 넘기지 않고 메모리에 둔다.
# 업로드 본문은 RequestContextMiddleware가 MAX_REQUEST_BYTES까지만 읽으므로
# 파일들을 합쳐도 이 크기를 넘을 수 없고, 메모리 사용도 그 안이다.
MultiPartParser.spool_max_size = uploads.MAX_REQUEST_BYTES

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


# ---------------------------------------------------------------------------
# 미들웨어: 요청 ID, 시간 로그, 업로드 크기 상한, 처리되지 않은 예외
# ---------------------------------------------------------------------------


def _content_length(scope: dict) -> int:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return 0
    return 0


class _ClientGone(Exception):
    """본문을 받는 중에 클라이언트가 연결을 끊었다."""


class _SlowClient(Exception):
    """본문이 너무 느리게 오거나 멈췄다."""


async def _read_body_capped(
    scope: dict,
    receive,
    limit: int,
    *,
    idle_seconds: Optional[float] = None,
    total_seconds: Optional[float] = None,
    min_rate: Optional[float] = None,
) -> Optional[list[bytes]]:
    """요청 본문을 limit 바이트까지만 메모리로 읽어 받은 조각 목록으로 돌려준다. 넘으면 그 자리에서 멈추고 None.

    Content-Length가 없는 chunked 요청도 받은 바이트를 세어 막으므로, 상한을 넘는 데이터는
    버퍼에 쌓이지 않고 디스크로도 가지 않는다. 조각을 이어 붙이지 않아 본문 크기만큼 더 쓰지 않는다.
    조각 사이가 idle_seconds를 넘거나, 전체가 total_seconds를 넘으면 _SlowClient.
    min_rate가 있으면 유예 시간 뒤 평균 속도가 그보다 느리거나, 지금 속도로는 알려 준 길이를
    total_seconds 안에 다 받을 수 없을 때도 _SlowClient (자리를 붙잡은 채 느리게 보내는 연결을 일찍 끊는다).
    """
    expected = _content_length(scope)
    if expected > limit:
        return None
    idle = BODY_IDLE_SECONDS if idle_seconds is None else idle_seconds
    loop = asyncio.get_running_loop()
    started = loop.time()
    chunks: list[bytes] = []
    size = 0
    while True:
        wait = idle
        if total_seconds is not None:
            wait = min(wait, started + total_seconds - loop.time())
        if wait <= 0:
            raise _SlowClient()
        try:
            async with asyncio.timeout(wait):
                message = await receive()
        except TimeoutError:
            raise _SlowClient() from None
        if message["type"] == "http.disconnect":
            raise _ClientGone()
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            return chunks
        elapsed = loop.time() - started
        if min_rate is not None and elapsed > UPLOAD_RATE_GRACE_SECONDS:
            too_slow = size < min_rate * elapsed
            cannot_finish = (
                total_seconds is not None and 0 < size < expected and elapsed * expected / size > total_seconds
            )
            if too_slow or cannot_finish:
                raise _SlowClient()


def _replay_body(chunks: list[bytes], receive):
    """미리 읽은 본문 조각을 차례로 넘기고, 그다음부터는 원래 receive를 쓴다 (연결 끊김 감지용).

    넘긴 조각은 들고 있지 않는다. 업로드 본문(최대 21MB)이 요청이 끝날 때까지 메모리에 남지 않게 한다.
    """
    pending = list(reversed(chunks))
    chunks.clear()

    async def replay():
        if pending:
            return {"type": "http.request", "body": pending.pop(), "more_body": bool(pending)}
        return await receive()

    return replay


# 이벤트 루프마다 하나씩 (테스트는 요청마다 루프가 다를 수 있다)
_slot_table: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Semaphore]]" = (
    weakref.WeakKeyDictionary()
)


def _slots(kind: str, size: int) -> asyncio.Semaphore:
    table = _slot_table.setdefault(asyncio.get_running_loop(), {})
    if kind not in table:
        table[kind] = asyncio.Semaphore(size)
    return table[kind]


def upload_slots() -> asyncio.Semaphore:
    return _slots("upload", UPLOAD_SLOTS)


def ai_slots() -> asyncio.Semaphore:
    return _slots("ai", AI_SLOTS)


def _budget_left(started_at: Optional[float]) -> float:
    """요청이 들어온 때부터 잰 마감까지 남은 초."""
    budget = extract.deadline_seconds()
    if started_at is None:
        return budget
    return budget - (asyncio.get_running_loop().time() - started_at)


async def _wait_for_slot(slots: asyncio.Semaphore, seconds: float, kind: str) -> bool:
    """자리를 기다린다. seconds 안에 못 잡으면 False. 자리가 비어 있으면 seconds가 0 이하여도 바로 잡는다."""
    started = time.perf_counter()
    try:
        async with asyncio.timeout(max(seconds, 0.0)):
            await slots.acquire()
    except TimeoutError:
        logger.info("extract busy slot=%s waited=%.1fs", kind, time.perf_counter() - started)
        return False
    waited = time.perf_counter() - started
    if waited >= 0.5:
        logger.info("extract queued slot=%s waited=%.1fs", kind, waited)
    return True


def _releaser(slots: asyncio.Semaphore):
    """자리를 한 번만 반납하는 함수 (라우트와 미들웨어가 모두 불러도 된다)."""
    held = [slots]

    def release() -> None:
        if held:
            held.pop().release()

    return release


def request_started_at(request: Request) -> Optional[float]:
    """미들웨어가 기록한 요청 시작 시각 (이벤트 루프 시각). 없으면 None."""
    return getattr(request.state, STARTED_AT, None)


def release_upload_slot(request: Request) -> None:
    release = getattr(request.state, UPLOAD_SLOT, None)
    if release is not None:
        release()


def _log_unhandled(exc: Exception) -> None:
    # 예외 메시지에는 입력값(이름·주소)이 들어 있을 수 있어 종류와 위치만 남긴다.
    frames = traceback.extract_tb(exc.__traceback__)[-4:]
    where = " <- ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in reversed(frames))
    logger.error("unhandled %s at %s", type(exc).__name__, where or "?")


_CLOSE = {"Connection": "close"}  # 다 읽지 않은 본문이 남은 채로 답할 때는 연결을 닫는다


def rate_limit_on() -> bool:
    return os.environ.get("RATE_LIMIT", "").strip().lower() in ("1", "true", "on", "yes")


def _over_rate_limit(scope: dict) -> bool:
    """이 요청이 같은 IP의 시간당 상한을 넘는지. 넘지 않으면 이번 요청을 센다."""
    if scope["method"] != "POST" or not rate_limit_on():
        return False
    group = next((name for name, (paths, _) in RATE_LIMITS.items() if scope["path"] in paths), None)
    if group is None:
        return False
    limit = RATE_LIMITS[group][1]
    client = (scope.get("client") or ("-", 0))[0]  # uvicorn --proxy-headers면 실제 접속 IP
    now = time.monotonic()
    hits = _rate_hits.setdefault((group, client), deque())
    while hits and now - hits[0] > RATE_WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    if len(_rate_hits) > 10_000:  # 오래된 IP는 지워 메모리가 늘지 않게 한다
        for key in [k for k, v in _rate_hits.items() if not v or now - v[-1] > RATE_WINDOW_SECONDS]:
            del _rate_hits[key]
    return False


class RequestContextMiddleware:
    """요청 ID(X-Request-ID), 상태·시간 로그, 본문 크기·시간 상한, 업로드 자리, 처리되지 않은 예외 → 500."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:12]
        token = config.request_id_var.set(request_id)
        started = time.perf_counter()
        loop = asyncio.get_running_loop()
        started_at = scope.setdefault("state", {})[STARTED_AT] = loop.time()
        state = {"status": 500, "started": False}
        release_upload = None

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                state["status"], state["started"] = message["status"], True
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            if _over_rate_limit(scope):
                # 본문을 읽지 않았으므로 연결을 닫는다. IP는 로그에 남기지 않는다.
                await api_error_response(ApiError("RATE_LIMITED", reason="rate_limit"), _CLOSE)(
                    scope, receive, send_with_id
                )
                return
            upload = scope["method"] == "POST" and scope["path"] in UPLOAD_REQUEST_LIMITS
            if upload or scope["method"] in BODY_METHODS:
                limit = UPLOAD_REQUEST_LIMITS[scope["path"]] if upload else JSON_REQUEST_LIMIT
                body = None
                if _content_length(scope) > limit:
                    pass  # 알려 준 길이가 이미 상한을 넘는다. 줄을 세우거나 읽지 않고 바로 거절한다.
                elif upload:
                    # 본문을 읽기 전에 업로드 자리를 잡는다. 동시에 메모리에 올라가는 업로드 수가 묶인다.
                    slots = upload_slots()
                    if not await _wait_for_slot(slots, _budget_left(started_at), "upload"):
                        # 본문을 읽지 않았으므로 연결을 닫는다
                        await api_error_response(ApiError.busy("upload"), _CLOSE)(scope, receive, send_with_id)
                        return
                    release_upload = scope["state"][UPLOAD_SLOT] = _releaser(slots)
                    body = await _read_body_capped(
                        scope, receive, limit, total_seconds=_budget_left(started_at),
                        min_rate=UPLOAD_MIN_BYTES_PER_SECOND,
                    )
                else:
                    body = await _read_body_capped(scope, receive, limit, total_seconds=JSON_BODY_SECONDS)
                if body is None:  # 상한을 넘었다. 나머지는 읽지 않고 거절하고 연결을 닫는다.
                    code, status = ("UNSUPPORTED_FILE", 400) if upload else ("INVALID_REQUEST", 413)
                    logger.info("error code=%s status=%d reason=request_too_large", code, status)
                    await error_response(code, status, headers=_CLOSE)(scope, receive, send_with_id)
                    return
                receive = _replay_body(body, receive)
                del body
            await self.app(scope, receive, send_with_id)
        except _ClientGone:
            state["status"] = 499  # 업로드 중에 연결이 끊겼다. 보낼 곳이 없으므로 응답하지 않는다.
        except _SlowClient:
            logger.info("error code=INVALID_REQUEST status=408 reason=slow_body")
            await error_response("INVALID_REQUEST", 408, headers=_CLOSE)(scope, receive, send_with_id)
        except Exception as exc:
            _log_unhandled(exc)
            if state["started"]:
                raise
            await error_response("INTERNAL_ERROR")(scope, receive, send_with_id)
        finally:
            if release_upload is not None:
                release_upload()  # 라우트가 이미 놓았으면 아무것도 하지 않는다
            took_ms = (time.perf_counter() - started) * 1000
            logger.info("%s %s -> %s (%.0f ms)", scope["method"], scope["path"], state["status"], took_ms)
            config.request_id_var.reset(token)


# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _ENV_KEYS_LOADED:
        logger.info("loaded from .env: %s", ", ".join(_ENV_KEYS_LOADED))  # 키 이름만 남긴다
    ai = extract.describe_ai()
    logger.info(
        "startup ai_ready=%s provider=%s model=%s effort=%s public_api_ready=%s extract_deadline=%gs "
        "upload_slots=%d ai_slots=%d",
        extract.has_credentials(),
        ai["provider"],
        ai["model"],
        ai["effort"],
        market_api.ready(),
        extract.deadline_seconds(),
        UPLOAD_SLOTS,
        AI_SLOTS,
    )
    # PDF 검사용 자식 프로세스가 이 컴퓨터에서 도는지 확인한다 (안 되면 같은 프로세스에서 검사한다)
    await run_in_threadpool(pdf_sandbox.self_test)
    yield
    await extract.aclose_client()


app = FastAPI(
    title="자취방 보증금 지킴이 API",
    version="0.1.0",
    description="등기부·계약서 추출(OpenAI GPT 또는 Claude)과 위험 신호 검사(규칙 엔진).",
    lifespan=lifespan,
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(  # 가장 바깥: 오류 응답에도 CORS 헤더가 붙는다
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)
app.add_exception_handler(ApiError, api_error_handler)


_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def _safe_loc(loc) -> list:
    """오류 위치에서 필드 이름·번호만 남긴다. 입력에서 온 키(정의되지 않은 필드 이름 등)는 "?"로 바꾼다."""
    return [p if isinstance(p, int) or (isinstance(p, str) and _FIELD_NAME.fullmatch(p)) else "?" for p in loc]


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    if request.url.path in UPLOAD_REQUEST_LIMITS:
        # 파일이 빠졌거나 파일이 아닌 값이 왔다. 어느 칸인지 알면 함께 알린다.
        loc = tuple(errors[0].get("loc", ())) if errors else ()
        document = loc[1] if len(loc) >= 2 and loc[0] == "body" and loc[1] in DOCUMENTS else None
        logger.info("error code=UNSUPPORTED_FILE status=400 reason=form_invalid document=%s", document or "-")
        return error_response("UNSUPPORTED_FILE", document=document)
    # 그 밖(/api/check 등)은 422와 detail 목록. 입력값(input)은 돌려주지 않는다:
    # 큰 입력을 그대로 되돌리면 느리고, 이름·주소가 다시 나간다. 위치·문구·종류만, 앞의 몇 개만 담는다.
    detail = [
        {
            "loc": _safe_loc(err.get("loc", ())),
            "msg": privacy.mask_text(str(err.get("msg", "")))[:200],
            "type": str(err.get("type", "")),
        }
        for err in errors[:MAX_VALIDATION_ERRORS]
    ]
    locs = [".".join(str(p) for p in item["loc"]) for item in detail[:5]]
    logger.info("request invalid path=%s errors=%d at=%s", request.url.path, len(errors), locs)
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(StarletteHTTPException)
async def _http_error_handler(request: Request, exc: StarletteHTTPException):
    """Starlette·FastAPI의 HTTP 오류(없는 경로, 메서드, multipart 해석 실패 등)도 공통 오류 형식으로 보낸다."""
    if request.url.path in UPLOAD_REQUEST_LIMITS and exc.status_code == 400:
        # multipart 해석 실패 (boundary 없음, 조각이 너무 많거나 큼 등)
        logger.info("error code=UNSUPPORTED_FILE status=400 reason=multipart_invalid")
        return error_response("UNSUPPORTED_FILE")
    logger.info("error code=INVALID_REQUEST status=%d reason=http_%d", exc.status_code, exc.status_code)
    return error_response("INVALID_REQUEST", exc.status_code, headers=getattr(exc, "headers", None))


_ERROR_DOC = {"model": ErrorResponse}


# ---------------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------------


async def _cancel_if_client_leaves(request: Request, work: Awaitable[T]) -> T:
    """클라이언트가 연결을 끊으면(화면 시간 초과·취소) 진행 중인 추출(AI 호출)을 취소한다."""
    task = asyncio.ensure_future(work)
    client_left = False

    async def watch() -> None:
        nonlocal client_left
        while not task.done():
            await asyncio.sleep(DISCONNECT_POLL_SECONDS)
            if await request.is_disconnected():
                client_left = True
                task.cancel()
                return

    watcher = asyncio.ensure_future(watch())
    try:
        return await task
    except asyncio.CancelledError:
        if client_left:  # 우리가 취소했다 (요청 자체가 취소된 것이 아니다)
            raise ApiError("AI_FAILED", reason="client_disconnected") from None
        raise
    finally:
        watcher.cancel()


async def _extract_with_ai_slot(request: Request, make_work: Callable[[], Awaitable[T]]) -> T:
    """AI 자리를 잡고 추출한다. 자리를 잡으면 업로드 자리는 다음 요청에 넘긴다.

    자리는 요청이 들어온 때부터 마감까지 기다리고, 그래도 없으면 BUSY(503).
    클라이언트가 떠나면 기다리기와 AI 호출을 모두 취소한다.
    """
    extract.get_client()  # 키가 없으면 줄을 서지 않고 바로 503
    started_at = request_started_at(request)

    async def run() -> T:
        slots = ai_slots()
        if not await _wait_for_slot(slots, _budget_left(started_at), "ai"):
            raise ApiError.busy("ai")
        try:
            release_upload_slot(request)
            return await make_work()
        finally:
            slots.release()

    return await _cancel_if_client_leaves(request, run())


async def _read_upload(upload: UploadFile) -> bytes:
    # 상한 + 1바이트까지만 읽는다. 넘으면 uploads 검사에서 거절된다.
    # 읽은 뒤 바로 닫아 multipart 버퍼(메모리)를 AI 호출 전에 놓는다.
    try:
        return await upload.read(uploads.MAX_UPLOAD_BYTES + 1)
    finally:
        await upload.close()


def _is_blank(upload: UploadFile) -> bool:
    """파일을 고르지 않은 빈 칸 (이름 없음, 0바이트)."""
    return not upload.filename and not upload.size


# 업로드 칸 하나. 파일을 고르지 않은 칸은 Starlette가 빈 문자열("")로 넘긴다.
FilePart = Union[UploadFile, str]


async def _read_uploads(doc: str, parts: Optional[list[FilePart]]) -> list[bytes]:
    """한 서류의 파일들을 올린 순서대로 읽는다. 빈 칸은 건너뛰고, 파일이 아닌 값은 UNSUPPORTED_FILE."""
    files: list[bytes] = []
    for part in parts or []:
        if isinstance(part, str):
            if part == "":
                continue
            raise ApiError("UNSUPPORTED_FILE", reason=f"{doc}:not_a_file")
        if not _is_blank(part):
            files.append(await _read_upload(part))
    return files


@app.post(
    "/api/extract",
    response_model=ExtractResponse,
    responses={400: _ERROR_DOC, 422: _ERROR_DOC, 502: _ERROR_DOC, 503: _ERROR_DOC},
)
async def extract_route(
    request: Request,
    registry: list[FilePart] = File(
        ..., description="등기부등본 PDF나 사진(JPG·PNG·WEBP). 필수, 여러 개면 올린 순서대로 한 등기부로 읽는다"
    ),
    contract: Optional[list[FilePart]] = File(
        None, description="계약서 사진이나 PDF. 선택, 여러 개면 올린 순서대로 한 계약서로 읽는다"
    ),
) -> ExtractResponse:
    """등기부(필수)와 계약서(선택)를 AI로 읽어 8.1·8.2 형식으로 돌려준다. 파일은 저장하지 않는다.

    서류마다 파일 10개, 쪽 수 합계 30쪽(사진 한 장은 한 쪽), 파일 하나 10MB, 전체 20MB까지 받는다.
    응답의 모든 문자열에서 주민등록번호 모양은 "******-*******"로 가린다.
    """
    registry_data = await _read_uploads("registry", registry)
    contract_data = await _read_uploads("contract", contract)
    uploads.check_total_size(registry_data + contract_data)
    registry_docs = await run_in_threadpool(uploads.validate_files, "registry", registry_data)
    contract_docs = None
    if contract_data:
        contract_docs = await run_in_threadpool(uploads.validate_files, "contract", contract_data)
    del registry_data, contract_data
    started_at = request_started_at(request)
    result = await _extract_with_ai_slot(
        request, lambda: extract.extract_documents(registry_docs, contract_docs, started_at=started_at)
    )
    return privacy.mask_resident_ids(result)


@app.post(
    EXTRACT_CONTRACT_PATH,
    response_model=ContractExtract,
    responses={400: _ERROR_DOC, 422: _ERROR_DOC, 502: _ERROR_DOC, 503: _ERROR_DOC},
)
async def extract_contract_route(
    request: Request,
    contract: list[FilePart] = File(
        ..., description="수정된 계약서 사진(JPG·PNG·WEBP)이나 PDF. 여러 개면 올린 순서대로 한 계약서로 읽는다"
    ),
) -> ContractExtract:
    """수정된 계약서만 읽는다. 검사·상한·호출·마감·오류·주민등록번호 가림은 /api/extract와 같다."""
    contract_data = await _read_uploads("contract", contract)
    uploads.check_total_size(contract_data)
    contract_docs = await run_in_threadpool(uploads.validate_files, "contract", contract_data)
    del contract_data
    started_at = request_started_at(request)
    result = await _extract_with_ai_slot(
        request, lambda: extract.extract_contract_only(contract_docs, started_at=started_at)
    )
    return privacy.mask_resident_ids(result)


def fill_public_data(req: CheckRequest) -> CheckRequest:
    """TODO: 비어 있는 building을 건축물대장 API로 채운다. 지금은 그대로 돌려준다.

    - 시세(market)는 여기서 채우지 않는다. 화면이 /api/market으로 미리 찾아 검사 입력에 넣는다
      (사용자가 값을 보고 고칠 수 있게, 그리고 /api/check가 밖으로 부르지 않게).
    - 등기부 주소 → 법정동코드·지번 → 건축물대장 API(용도, 위반 여부) → building
    - 호출당 타임아웃 5초. 실패하면 비워 둔다 (해당 규칙만 ⚪, 오류로 처리하지 않는다).
    """
    return req


@app.post("/api/check", response_model=Report)
def check_route(req: CheckRequest) -> Report:
    """AI를 부르지 않고 규칙 엔진으로 리포트를 만든다. today가 없으면 현재 한국 날짜를 쓴다.

    응답의 주민등록번호·전화번호 모양은 가린다 (근거 원문·요청서에 입력이 그대로 인용될 수 있다).
    """
    if req.today is None:
        req = req.model_copy(update={"today": today_kst()})
    if req.mode == "live" and (req.building is None or req.market is None):
        req = fill_public_data(req)  # 데모 모드에서는 외부 API를 부르지 않는다
    return privacy.mask_resident_ids(build_report(req))


def build_recheck(req: RecheckRequest) -> RecheckReport:
    """규칙 엔진의 build_recheck를 부른다.

    부를 때 가져온다: 규칙 엔진이 아직 내보내지 않아도 서버는 뜨고, 이 라우트만 500이 된다.
    테스트에서는 이 함수를 바꿔 끼운다.
    """
    from app.rules import build_recheck as rules_build_recheck

    return rules_build_recheck(req)


@app.post("/api/recheck", response_model=RecheckReport)
def recheck_route(req: RecheckRequest) -> RecheckReport:
    """계약 후 재확인: 오늘 뗀 등기부를 계약서와 맞춰 본다. AI를 부르지 않는다.

    today가 없으면 현재 한국 날짜를 쓰고, 응답의 주민등록번호 모양은 가린다.
    """
    if req.today is None:
        req = req.model_copy(update={"today": today_kst()})
    return privacy.mask_resident_ids(build_recheck(req))


def build_compare(req: CompareRequest) -> CompareReport:
    """규칙 엔진의 build_compare를 부를 때 가져온다. 아직 없으면 이 라우트만 500이다."""
    from app.rules import build_compare as rules_build_compare

    return rules_build_compare(req)


@app.post("/api/compare", response_model=CompareReport)
def compare_route(req: CompareRequest) -> CompareReport:
    """수정 전·후 계약서 비교. AI를 부르지 않는다.

    today가 없으면 수정 전 입력의 today, 그것도 없으면 현재 한국 날짜를 쓴다. 응답의 주민등록번호 모양은 가린다.
    """
    if req.today is None:
        req = req.model_copy(update={"today": req.before.today or today_kst()})
    return privacy.mask_resident_ids(build_compare(req))


def _load_demo(name: str, model: type[M]) -> M:
    """backend/demo/{name}.json을 읽어 검증한다. 없으면 NOT_FOUND, 형식이 틀리면 INTERNAL_ERROR."""
    path = DEMO_DIR / f"{name}.json"
    if not path.is_file():
        raise ApiError("NOT_FOUND", reason=f"demo:{name}_missing")
    try:
        req = model.model_validate_json(path.read_bytes())
    except ValidationError as e:
        locs = [".".join(str(p) for p in err["loc"]) for err in e.errors()[:5]]
        logger.error("demo file invalid scenario=%s errors=%d at=%s", name, e.error_count(), locs)
        raise ApiError("INTERNAL_ERROR", reason=f"demo:{name}_invalid") from None
    # 예시 데이터는 항상 데모 모드이고, 주민등록번호 모양은 가린다.
    return privacy.mask_resident_ids(req.model_copy(update={"mode": "demo"}))


# 아래 예시들은 /api/demo/{scenario}보다 먼저 선언해야 시나리오 이름으로 잡히지 않는다.
@app.get(f"/api/demo/{COMPARE_DEMO}", response_model=CompareRequest, responses={404: _ERROR_DOC})
def compare_demo_route() -> CompareRequest:
    """수정 전·후 비교 예시의 /api/compare 입력 전체. 안쪽 두 검사 입력도 데모 모드다."""
    req = _load_demo(COMPARE_DEMO, CompareRequest)
    return req.model_copy(
        update={
            "before": req.before.model_copy(update={"mode": "demo"}),
            "after": req.after.model_copy(update={"mode": "demo"}),
        }
    )


@app.get(f"/api/demo/{RECHECK_DEMO}", response_model=RecheckRequest, responses={404: _ERROR_DOC})
def recheck_demo_route() -> RecheckRequest:
    """계약 후 재확인 예시의 /api/recheck 입력 전체."""
    return _load_demo(RECHECK_DEMO, RecheckRequest)


@app.get("/api/demo/{scenario}", response_model=CheckRequest, responses={404: _ERROR_DOC})
def demo_route(scenario: str) -> CheckRequest:
    """데모 시나리오(A·B·C)의 /api/check 입력 전체. mode는 항상 "demo"이고, 주민등록번호 모양은 가린다."""
    name = scenario.upper()
    if name not in DEMO_SCENARIOS:
        raise ApiError("NOT_FOUND", reason="demo:unknown_scenario")
    return _load_demo(name, CheckRequest)


@app.get("/api/health", response_model=HealthResponse)
def health_route() -> HealthResponse:
    return HealthResponse(ai_ready=extract.has_credentials(), public_api_ready=market_api.ready())


@app.post("/api/market", response_model=MarketInsight)
async def market_route(req: CheckRequest) -> MarketInsight:
    """국토교통부 실거래가로 시세(검사 입력의 market)와 주변 보증금을 찾는다. AI를 부르지 않는다.

    - 입력은 /api/check와 같다. 등기부 주소·종류·면적과 계약 종류만 쓴다.
    - 주소 API에는 '시도 시군구 읍면동'까지만, 실거래 API에는 시군구 코드와 연월만 보낸다.
    - 예시(mode=demo)는 밖으로 부르지 않는다. 실패해도 200과 status·message로 알린다 (검사를 막지 않는다).
    """
    if req.mode == "demo":
        return MarketInsight(status="unavailable", message="예시에서는 실거래를 찾지 않아요.")
    return await market_api.lookup(req, req.today or today_kst())


@app.post(
    "/api/checklist.ics",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}, "description": ".ics 파일"}},
)
def checklist_ics_route(req: IcsRequest) -> Response:
    """리포트의 일정 체크리스트 → .ics 파일 (하루 전 09:00 알림)."""
    return Response(
        content=ics.build_ics(req).encode("utf-8"),
        media_type=ics.MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{ics.FILENAME}"'},
    )


# ---------------------------------------------------------------------------
# 배포: 빌드한 화면(frontend/dist)을 같은 주소에서 내준다
# ---------------------------------------------------------------------------

FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", str(config.BACKEND_DIR.parent / "frontend" / "dist")))


def mount_frontend(target: FastAPI, dist: Path) -> bool:
    """dist(index.html이 있는 폴더)를 "/"에 붙인다. 화면은 주소 경로를 바꾸지 않으므로 SPA 대체 경로는 필요 없다.

    API 경로를 모두 선언한 뒤에 불러야 한다 (먼저 선언한 경로가 먼저 잡힌다).
    """
    if not (dist / "index.html").is_file():
        logger.warning("frontend dist missing; serving API only")
        return False
    target.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return True


# SERVE_FRONTEND=1일 때만 (Dockerfile). 개발에서는 Vite 개발 서버가 화면을 내준다.
if os.environ.get("SERVE_FRONTEND", "").strip().lower() in ("1", "true", "on", "yes"):
    mount_frontend(app, FRONTEND_DIST)
