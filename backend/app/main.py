"""FastAPI 앱.

실행 (backend 폴더에서): .venv/bin/uvicorn app.main:app --port 8000
API 키 없이도 /api/health, /api/demo, /api/check, /api/checklist.ics는 동작한다.
"""

import asyncio
import datetime as dt
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Optional, TypeVar

from app import config

# 다른 모듈보다 먼저 .env를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다.
_ENV_KEYS_LOADED = config.load_env_file()

from fastapi import FastAPI, File, Request, UploadFile  # noqa: E402
from fastapi.exception_handlers import request_validation_exception_handler  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from starlette.datastructures import MutableHeaders  # noqa: E402
from starlette.formparsers import MultiPartParser  # noqa: E402

from app import extract, ics, privacy, uploads  # noqa: E402
from app.errors import ApiError, api_error_handler, error_response  # noqa: E402
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
EXTRACT_CONTRACT_PATH = "/api/extract/contract"  # 수정된 계약서 하나만
# 업로드 경로별 요청 본문 상한. 넘으면 본문을 더 읽지 않고 UNSUPPORTED_FILE.
UPLOAD_REQUEST_LIMITS = {
    EXTRACT_PATH: uploads.MAX_REQUEST_BYTES,
    EXTRACT_CONTRACT_PATH: uploads.MAX_SINGLE_FILE_REQUEST_BYTES,
}
DISCONNECT_POLL_SECONDS = 0.5  # 추출 중 클라이언트 연결 끊김을 확인하는 간격

# multipart 파일을 디스크 임시 파일로 넘기지 않고 메모리에 둔다.
# /api/extract 본문은 RequestContextMiddleware가 MAX_REQUEST_BYTES까지만 읽으므로
# 파일 하나도 이 크기를 넘을 수 없고, 메모리 사용도 그 안이다.
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


async def _read_body_capped(scope: dict, receive, limit: int) -> Optional[bytes]:
    """요청 본문을 limit 바이트까지만 메모리로 읽는다. 넘으면 그 자리에서 멈추고 None.

    Content-Length가 없는 chunked 요청도 받은 바이트를 세어 막으므로, 상한을 넘는 데이터는
    버퍼에 쌓이지 않고 디스크로도 가지 않는다.
    """
    if _content_length(scope) > limit:
        return None
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise _ClientGone()
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks)


def _replay_body(body: bytes, receive):
    """미리 읽은 본문을 한 번에 넘기고, 그다음부터는 원래 receive를 쓴다 (연결 끊김 감지용)."""
    pending = True

    async def replay():
        nonlocal pending
        if pending:
            pending = False
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


def _log_unhandled(exc: Exception) -> None:
    # 예외 메시지에는 입력값(이름·주소)이 들어 있을 수 있어 종류와 위치만 남긴다.
    frames = traceback.extract_tb(exc.__traceback__)[-4:]
    where = " <- ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in reversed(frames))
    logger.error("unhandled %s at %s", type(exc).__name__, where or "?")


class RequestContextMiddleware:
    """요청 ID(X-Request-ID), 상태·시간 로그, /api/extract 본문 크기 상한, 처리되지 않은 예외 → 500."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:12]
        token = config.request_id_var.set(request_id)
        started = time.perf_counter()
        state = {"status": 500, "started": False}

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                state["status"], state["started"] = message["status"], True
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            limit = UPLOAD_REQUEST_LIMITS.get(scope["path"])
            if limit is not None and scope["method"] == "POST":
                body = await _read_body_capped(scope, receive, limit)
                if body is None:  # 상한을 넘었다. 나머지는 읽지 않고 바로 거절한다.
                    logger.info("error code=UNSUPPORTED_FILE status=400 reason=request_too_large")
                    await error_response("UNSUPPORTED_FILE")(scope, receive, send_with_id)
                    return
                receive = _replay_body(body, receive)
            await self.app(scope, receive, send_with_id)
        except _ClientGone:
            state["status"] = 499  # 업로드 중에 연결이 끊겼다. 보낼 곳이 없으므로 응답하지 않는다.
        except Exception as exc:
            _log_unhandled(exc)
            if state["started"]:
                raise
            await error_response("INTERNAL_ERROR")(scope, receive, send_with_id)
        finally:
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
    logger.info(
        "startup ai_ready=%s public_api_ready=%s extract_deadline=%gs",
        extract.has_credentials(),
        False,
        extract.deadline_seconds(),
    )
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


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError):
    if request.url.path in UPLOAD_REQUEST_LIMITS:
        # 파일이 빠졌거나 파일이 아닌 값이 왔다
        logger.info("error code=UNSUPPORTED_FILE status=400 reason=form_invalid")
        return error_response("UNSUPPORTED_FILE")
    # 그 밖(/api/check 등)은 FastAPI 기본 형식(422, detail 목록). 로그에는 위치만 남긴다.
    locs = [".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()[:5]]
    logger.info("request invalid path=%s errors=%d at=%s", request.url.path, len(exc.errors()), locs)
    return await request_validation_exception_handler(request, exc)


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


async def _read_upload(upload: UploadFile) -> bytes:
    # 상한 + 1바이트까지만 읽는다. 넘으면 uploads 검사에서 거절된다.
    return await upload.read(uploads.MAX_UPLOAD_BYTES + 1)


def _is_blank(upload: UploadFile) -> bool:
    """파일을 고르지 않은 빈 칸 (이름 없음, 0바이트)."""
    return not upload.filename and not upload.size


@app.post(
    "/api/extract",
    response_model=ExtractResponse,
    responses={400: _ERROR_DOC, 422: _ERROR_DOC, 502: _ERROR_DOC, 503: _ERROR_DOC},
)
async def extract_route(
    request: Request,
    registry: UploadFile = File(..., description="등기부등본 PDF (필수, 10MB·30쪽 이하)"),
    contract: Optional[UploadFile] = File(None, description="계약서 사진(JPG·PNG·WEBP) 또는 PDF (선택, 10MB 이하)"),
) -> ExtractResponse:
    """등기부(필수)와 계약서(선택)를 AI로 읽어 8.1·8.2 형식으로 돌려준다. 파일은 저장하지 않는다.

    응답의 모든 문자열에서 주민등록번호 모양은 "******-*******"로 가린다.
    """
    registry_doc = await run_in_threadpool(uploads.validate_registry, await _read_upload(registry))
    contract_doc = None
    if contract is not None and not _is_blank(contract):
        contract_doc = await run_in_threadpool(uploads.validate_contract, await _read_upload(contract))
    result = await _cancel_if_client_leaves(request, extract.extract_documents(registry_doc, contract_doc))
    return privacy.mask_resident_ids(result)


@app.post(
    EXTRACT_CONTRACT_PATH,
    response_model=ContractExtract,
    responses={400: _ERROR_DOC, 422: _ERROR_DOC, 502: _ERROR_DOC, 503: _ERROR_DOC},
)
async def extract_contract_route(
    request: Request,
    contract: UploadFile = File(..., description="수정된 계약서 사진(JPG·PNG·WEBP) 또는 PDF (10MB 이하)"),
) -> ContractExtract:
    """수정된 계약서 하나만 읽는다. 검사·호출·마감·오류·주민등록번호 가림은 /api/extract와 같다."""
    contract_doc = await run_in_threadpool(uploads.validate_contract, await _read_upload(contract))
    result = await _cancel_if_client_leaves(request, extract.extract_contract_only(contract_doc))
    return privacy.mask_resident_ids(result)


def fill_public_data(req: CheckRequest) -> CheckRequest:
    """TODO: 비어 있는 building·market을 공공 API로 채운다. 지금은 그대로 돌려준다.

    - 등기부 주소 → 도로명주소 API(법정동코드·지번) → 건축물대장 API(용도, 위반 여부) → building
    - 실거래가 API → market
    - 호출당 타임아웃 5초. 실패하면 비워 둔다 (해당 규칙만 ⚪, 오류로 처리하지 않는다).
    - 같은 (시군구코드, 계약년월) 응답은 메모리에 캐시한다.
    - 구현하면 /api/health의 public_api_ready도 키 설정 여부로 바꾼다.
    """
    return req


@app.post("/api/check", response_model=Report)
def check_route(req: CheckRequest) -> Report:
    """AI를 부르지 않고 규칙 엔진으로 리포트를 만든다. today가 없으면 현재 한국 날짜를 쓴다."""
    if req.today is None:
        req = req.model_copy(update={"today": today_kst()})
    if req.mode == "live" and (req.building is None or req.market is None):
        req = fill_public_data(req)  # 데모 모드에서는 외부 API를 부르지 않는다
    return build_report(req)


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
    return HealthResponse(ai_ready=extract.has_credentials(), public_api_ready=False)


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
