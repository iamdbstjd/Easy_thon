"""서버 보호 장치 테스트.

- PDF 검사 격리(시간·메모리 상한), 업로드 동시 처리 수와 대기열, 마감 시간(요청 시작부터)
- 모든 POST 본문 상한, 느린 본문 끊기, 422 응답 형식(입력을 돌려주지 않음), HTTP 오류 공통 형식
- 입력 모델 상한(글자 수·목록 길이·날짜 범위), .ics 보호, 주민등록번호·전화번호 가리기
- AI 응답 처리(빈 본문, 여러 조각, 틀린 날짜 비우기), AI 설정(별칭, effort, 시작 로그)

진짜 AI는 부르지 않는다 (가짜 클라이언트만 쓴다).
"""

from __future__ import annotations

import asyncio
import copy
import datetime as dt
import importlib.util
import io
import json
import logging
import struct
import sys
import time
import zlib
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject

from app import config, extract, ics, main, pdf_sandbox, privacy, uploads
from app.errors import ERROR_MESSAGES
from app.schemas import ChecklistItem, Evidence, IcsRequest, Report, RuleResult
from test_api import (
    CONTRACT_OK,
    PNG,
    REGISTRY_OK,
    FakeClient,
    assert_error,
    install_ai,
    make_pdf,
    make_report,
    make_response,
    multipart_body,
    registry_file,
    unfold,
)
from test_extract import PDF_DOC, PNG_DOC
from test_extract_openai import make_reply, openai_client

NOW = dt.datetime(2026, 11, 14, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=9)))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """API 키를 지우고, 진짜 클라이언트를 만들려고 하면 실패하게 한다."""
    monkeypatch.delenv("EXTRACT_DEADLINE_SECONDS", raising=False)
    monkeypatch.setattr(extract, "_client", None)
    monkeypatch.setattr(extract, "_warned_settings", set())
    monkeypatch.setattr(pdf_sandbox, "_unavailable", None)  # 자식 프로세스 사용 가능 상태로 시작

    def _forbidden(*args, **kwargs):
        raise AssertionError("tests must not create a real AI client")

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _forbidden)

    async def no_wait(seconds):
        return None

    monkeypatch.setattr(extract, "_sleep", no_wait)


@pytest.fixture
def client():
    return TestClient(main.app)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# ASGI를 직접 부르는 도구 (한 이벤트 루프에서 여러 요청을 동시에 보낼 때)
# ---------------------------------------------------------------------------


def body_receive(body: bytes):
    """본문을 한 번에 보내고, 그 뒤로는 연결을 유지한 채 기다리는 클라이언트."""
    state = {"sent": False}

    async def receive():
        if not state["sent"]:
            state["sent"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)

    return receive


async def asgi_call(path: str, receive, headers: list[tuple[bytes, bytes]], method: str = "POST"):
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    await main.app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, body


def upload_call(pdf: bytes):
    body, headers = multipart_body("registry.pdf", pdf)
    scope_headers = [(b"content-type", headers["content-type"].encode()), (b"content-length", str(len(body)).encode())]
    return asgi_call(main.EXTRACT_PATH, body_receive(body), scope_headers)


# ---------------------------------------------------------------------------
# PDF 검사 격리
# ---------------------------------------------------------------------------


def objstm_chain_pdf(n: int, pad: int) -> bytes:
    """쪽 트리 노드를 압축 객체 스트림 n개에 하나씩 넣고, 스트림마다 pad 바이트를 덧붙인 PDF.

    파일은 수십 KB지만 pypdf가 객체를 찾을 때마다 큰 스트림을 다시 풀어 몇 초씩 걸린다.
    """
    objs: dict[int, bytes] = {}
    compressed: dict[int, tuple[int, int]] = {}

    def pnode(i):
        return 3 + i

    def stm(i):
        return 3 + n + i

    objs[1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pnode(0)
    objs[2] = b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 10 10] >>" % pnode(n - 1)
    for i in range(n):
        kid = pnode(i + 1) if i < n - 1 else 2
        data = (b"%d 0 " % pnode(i)).ljust(20) + b"<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % kid + b" " * pad
        comp = zlib.compress(data, 9)
        objs[stm(i)] = (
            b"<< /Type /ObjStm /N 1 /First 20 /Filter /FlateDecode /Length %d >>\nstream\n" % len(comp)
            + comp
            + b"\nendstream"
        )
        compressed[pnode(i)] = (stm(i), 0)
    buf = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(buf)
        buf += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref_num = 3 + 2 * n
    rows = b""
    for num in range(xref_num + 1):
        if num == 0:
            rows += struct.pack(">BIH", 0, 0, 65535)
        elif num in offsets:
            rows += struct.pack(">BIH", 1, offsets[num], 0)
        elif num in compressed:
            rows += struct.pack(">BIH", 2, *compressed[num])
        else:
            rows += struct.pack(">BIH", 1, len(buf), 0)
    xoff = len(buf)
    buf += (
        b"%d 0 obj\n<< /Type /XRef /Size %d /W [1 4 2] /Root 1 0 R /Length %d >>\nstream\n"
        % (xref_num, xref_num + 1, len(rows))
        + rows
        + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % xoff
    )
    return bytes(buf)


SLOW_PDF = objstm_chain_pdf(30, 1_000_000)  # 같은 프로세스에서 세면 2초 넘게 걸린다


def check_isolated(data: bytes, **kwargs) -> pdf_sandbox.PdfCheck:
    return pdf_sandbox.inspect_isolated(
        data, max_pages=uploads.MAX_PDF_PAGES, max_plain_bytes=uploads.MAX_DECRYPTED_BYTES, **kwargs
    )


def test_slow_pdf_is_cut_off_at_wall_timeout():
    started = time.perf_counter()
    assert check_isolated(SLOW_PDF, timeout=0.5).outcome == "pdf_timeout"
    assert time.perf_counter() - started < 2


def test_slow_pdf_upload_is_unsupported_file_without_calling_ai(client, monkeypatch):
    monkeypatch.setattr(pdf_sandbox, "WALL_TIMEOUT_SECONDS", 0.5)
    fake = install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    started = time.perf_counter()
    r = client.post("/api/extract", files=registry_file(SLOW_PDF))
    assert_error(r, 400, "UNSUPPORTED_FILE", document="registry")
    assert time.perf_counter() - started < 3
    assert fake.messages.calls == []


HAS_RESOURCE = importlib.util.find_spec("resource") is not None


@pytest.mark.skipif(not HAS_RESOURCE, reason="resource 모듈이 없는 운영체제 (윈도우)")
def test_memory_limit_rejects_instead_of_growing():
    # 상한을 아주 낮추면 자식 프로세스가 PDF를 읽다 멈추고 거절된다 (서버 프로세스는 영향 없음)
    big = b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024)
    assert check_isolated(big, memory=24 * 1024 * 1024).outcome == "pdf_too_complex"
    assert pdf_sandbox._unavailable is None  # PDF 탓이므로 자식 프로세스는 계속 쓴다


def test_isolated_check_matches_in_process_check():
    for data in (make_pdf(3), make_pdf(2, owner_password="o", algorithm="AES-256"), make_pdf(1, user_password="u")):
        assert check_isolated(data) == pdf_sandbox.inspect(
            data, max_pages=uploads.MAX_PDF_PAGES, max_plain_bytes=uploads.MAX_DECRYPTED_BYTES
        )


def spy_popen(monkeypatch) -> dict:
    seen: dict = {}
    real_popen = pdf_sandbox.subprocess.Popen

    def spy(args, **kwargs):
        seen.update(kwargs, args=args)
        return real_popen(args, **kwargs)

    monkeypatch.setattr(pdf_sandbox.subprocess, "Popen", spy)
    return seen


def test_pdf_child_env_keeps_only_os_names(monkeypatch):
    seen = spy_popen(monkeypatch)
    for name, value in {
        "OPENAI_API_KEY": "sk-should-not-leak",
        "ANTHROPIC_AUTH_TOKEN": "tok-should-not-leak",
        "PYTHONPATH": "/somewhere",
        "SYSTEMROOT": "C:\\Windows",  # 윈도우 파이썬이 시작하는 데 필요하다
        "PATH": "/usr/bin",
    }.items():
        monkeypatch.setenv(name, value)
    assert check_isolated(make_pdf(1)).outcome == "ok"
    env = seen["env"]
    assert set(env) <= {name for name in pdf_sandbox.CHILD_ENV_NAMES}
    assert env["SYSTEMROOT"] == "C:\\Windows" and env["PATH"] == "/usr/bin"
    assert "sk-should-not-leak" not in json.dumps(env) and "tok-should-not-leak" not in json.dumps(env)
    assert seen["stderr"] is pdf_sandbox.subprocess.DEVNULL


def test_child_finds_pypdf_through_parent_path(monkeypatch):
    # 자식에 site-packages가 없어도(-S) 부모의 sys.path로 pypdf를 찾는다 (PYTHONPATH로만 pypdf가 보이는 경우와 같다)
    monkeypatch.setattr(pdf_sandbox, "CHILD_FLAGS", ("-I", "-S"))
    assert check_isolated(make_pdf(2)) == ("ok", 2, None)
    assert pdf_sandbox._unavailable is None


def test_child_that_cannot_import_pypdf_falls_back_in_process(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(pdf_sandbox, "CHILD_FLAGS", ("-I", "-S"))
    monkeypatch.setattr(pdf_sandbox, "child_path", lambda: [])  # 자식이 pypdf를 찾을 길이 없다
    assert check_isolated(make_pdf(2)).outcome == "ok"  # 거절하지 않고 같은 프로세스에서 검사했다
    assert pdf_sandbox._unavailable == "child_setup_failed"
    assert "pdf sandbox unavailable" in caplog.text
    assert [r.levelname for r in caplog.records if "pdf sandbox unavailable" in r.getMessage()] == ["ERROR"]
    seen = spy_popen(monkeypatch)
    assert check_isolated(make_pdf(1)).outcome == "ok"
    assert seen == {}  # 그 뒤로는 자식 프로세스를 띄우지 않는다
    assert check_isolated(make_pdf(31)) == ("ok", 31, None)  # 쪽수 검사는 그대로 (uploads가 거절한다)


def test_child_that_cannot_import_app_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_sandbox, "BACKEND_DIR", tmp_path)  # app 패키지가 없는 폴더
    assert check_isolated(make_pdf(1)).outcome == "ok"
    assert pdf_sandbox._unavailable == "child_setup_failed"


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        (("_python", lambda: "/nonexistent/python3"), "spawn_failed"),
        (("_CHILD_CODE", "import sys; sys.exit(1)"), "child_exit_1"),  # 파이썬이 시작하다 실패한 경우 (윈도우 SYSTEMROOT 등)
    ],
    ids=["no-interpreter", "dies-before-ready"],
)
def test_sandbox_setup_failures_fall_back_in_process(monkeypatch, patch, reason):
    monkeypatch.setattr(pdf_sandbox, *patch)
    data = make_pdf(2, owner_password="o", algorithm="AES-256")
    result = check_isolated(data)
    assert (result.outcome, result.pages) == ("ok", 2) and result.plain is not None
    assert pdf_sandbox._unavailable == reason


def test_valid_upload_passes_when_sandbox_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(pdf_sandbox, "_python", lambda: "/nonexistent/python3")
    install_ai(monkeypatch, registry=make_response(REGISTRY_OK))
    assert client.post("/api/extract", files=registry_file()).status_code == 200
    assert_error(client.post("/api/extract", files=registry_file(make_pdf(31))), 400, "UNSUPPORTED_FILE")


def test_limits_are_skipped_without_resource_module(monkeypatch):
    # 윈도우처럼 resource가 없으면 상한 없이(부모의 시간 상한만) 검사한다
    monkeypatch.setitem(sys.modules, "resource", None)
    assert pdf_sandbox._set_limits(1, 1) is False
    stdin = io.BytesIO(
        json.dumps({"path": [], "max_pages": 30, "max_plain_bytes": 1 << 20, "memory": 1, "cpu": 1}).encode() + b"\n"
        + make_pdf(2)
    )
    stdout = io.BytesIO()
    pdf_sandbox.serve(stdin, stdout)
    out = stdout.getvalue()
    assert out.startswith(pdf_sandbox.READY)
    assert json.loads(out[1:].split(b"\n", 1)[0]) == {"outcome": "ok", "pages": 2, "plain": False, "limits": False}


def test_limits_the_os_refuses_are_skipped(monkeypatch):
    # macOS 등에서 setrlimit이 거절하는 상한은 건너뛴다
    calls = []

    def refuse(limit, values):
        calls.append(limit)
        raise ValueError("not allowed")

    fake = SimpleNamespace(RLIMIT_AS=1, RLIMIT_CPU=2, RLIMIT_FSIZE=3, RLIMIT_CORE=4, setrlimit=refuse)
    monkeypatch.setitem(sys.modules, "resource", fake)
    assert pdf_sandbox._set_limits(1, 1) is False
    assert calls == [1, 2, 3, 4]


def test_self_test_logs_result(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    assert pdf_sandbox.self_test() is True
    assert "pdf sandbox ok limits=" in caplog.text
    monkeypatch.setattr(pdf_sandbox, "_CHILD_CODE", "import sys; sys.exit(1)")
    assert pdf_sandbox.self_test() is False
    assert "pdf sandbox unavailable reason=child_exit_1" in caplog.text


def test_declared_page_count_over_limit_is_rejected_without_walking_tree():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer._root_object["/Pages"][NameObject("/Count")] = NumberObject(100_000)
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(uploads.ApiError) as e:
        uploads.validate_registry(buf.getvalue())
    assert e.value.reason == "registry:too_many_pages"


def test_demo_pdfs_still_pass():
    demo_docs = sorted((config.BACKEND_DIR.parent / "demo-docs").glob("*.pdf"))
    if not demo_docs:
        pytest.skip("demo-docs 폴더가 없다")
    for path in demo_docs:
        validate = uploads.validate_registry if "등기부" in path.name else uploads.validate_contract
        doc = validate(path.read_bytes())
        assert doc.kind == "document" and 0 < len(PdfReader(io.BytesIO(doc.data)).pages) <= uploads.MAX_PDF_PAGES


def test_header_at_start_is_not_copied():
    data = make_pdf(1)
    assert uploads._from_header(data, 0) is data
    assert uploads._from_header(b"xx" + data, 2) == data


# ---------------------------------------------------------------------------
# 본문 상한·시간 상한
# ---------------------------------------------------------------------------

JSON_PATHS = ["/api/check", "/api/recheck", "/api/compare", "/api/checklist.ics"]


@pytest.mark.parametrize("path", JSON_PATHS)
def test_json_body_over_limit_is_413(client, path):
    body = b'{"x": "' + b"a" * main.JSON_REQUEST_LIMIT + b'"}'
    r = client.post(path, content=body, headers={"content-type": "application/json"})
    assert_error(r, 413, "INVALID_REQUEST", document=None)
    assert r.headers["connection"] == "close"


def test_chunked_json_body_over_limit_is_413(client):
    def chunks():  # 길이를 모르는 본문 → Content-Length 없음
        for _ in range(3):
            yield b"a" * (600 * 1024)

    r = client.post("/api/check", content=chunks(), headers={"content-type": "application/json"})
    assert_error(r, 413, "INVALID_REQUEST")


def test_json_body_reading_stops_at_limit():
    received = []

    async def receive():  # 1MB 조각 60개를 보내는 chunked 요청
        received.append(1)
        return {"type": "http.request", "body": b"a" * (1024 * 1024), "more_body": len(received) < 60}

    status, _, _ = run(asgi_call("/api/check", receive, [(b"content-type", b"application/json")]))
    assert status == 413
    assert len(received) <= 2  # 상한을 넘자마자 읽기를 멈췄다


def test_stalled_body_is_408(monkeypatch):
    monkeypatch.setattr(main, "BODY_IDLE_SECONDS", 0.2)
    messages = [{"type": "http.request", "body": b'{"registry":', "more_body": True}]

    async def receive():
        if messages:
            return messages.pop(0)
        await asyncio.sleep(3600)  # 그 뒤로 아무것도 보내지 않는다

    started = time.perf_counter()
    status, headers, body = run(asgi_call("/api/check", receive, [(b"content-type", b"application/json")]))
    assert (status, json.loads(body)["error"]["code"]) == (408, "INVALID_REQUEST")
    assert headers["connection"] == "close"
    assert time.perf_counter() - started < 2


def test_trickling_upload_is_cut_off_and_frees_its_slot(monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_RATE_GRACE_SECONDS", 0.3)

    async def receive():  # 1바이트씩 천천히 (slowloris)
        await asyncio.sleep(0.02)
        return {"type": "http.request", "body": b"x", "more_body": True}

    async def scenario():
        started = time.perf_counter()
        status, _, body = await asgi_call(
            main.EXTRACT_PATH, receive, [(b"content-type", b"multipart/form-data; boundary=x")]
        )
        took = time.perf_counter() - started
        return status, json.loads(body), took, main.upload_slots()._value

    status, body, took, free_slots = run(scenario())
    assert (status, body["error"]["code"]) == (408, "INVALID_REQUEST")
    assert took < 2
    assert free_slots == main.UPLOAD_SLOTS  # 자리를 돌려놓았다


def test_upload_that_cannot_finish_before_deadline_is_cut_early(monkeypatch):
    # 최저 속도보다는 빠르지만 알려 준 길이를 마감 안에 다 보낼 수 없는 속도 → 유예 시간 뒤 바로 끊는다
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "5")
    monkeypatch.setattr(main, "UPLOAD_RATE_GRACE_SECONDS", 0.3)
    total = 10 * 1024 * 1024

    async def receive():  # 초당 약 400KB
        await asyncio.sleep(0.05)
        return {"type": "http.request", "body": b"x" * 20_000, "more_body": True}

    async def scenario():
        started = time.perf_counter()
        status, _, body = await asgi_call(
            main.EXTRACT_PATH,
            receive,
            [(b"content-type", b"multipart/form-data; boundary=x"), (b"content-length", str(total).encode())],
        )
        return status, json.loads(body), time.perf_counter() - started, main.upload_slots()._value

    status, body, took, free_slots = run(scenario())
    assert (status, body["error"]["code"]) == (408, "INVALID_REQUEST")
    assert took < 1.5  # 마감(5초)까지 자리를 붙잡지 않는다
    assert free_slots == main.UPLOAD_SLOTS


def test_replay_body_hands_over_chunks_and_releases_them():
    first_chunk, last_chunk = bytes(bytearray(b"x" * 1000)), bytes(bytearray(b"y" * 10))  # 공유하지 않는 객체

    async def receive():
        return {"type": "http.disconnect"}

    replay = main._replay_body([first_chunk, last_chunk], receive)
    before = sys.getrefcount(first_chunk)
    message = run(replay())
    assert message["body"] is first_chunk and message["more_body"] is True
    del message
    assert sys.getrefcount(first_chunk) == before - 1  # replay가 더는 들고 있지 않다
    assert run(replay()) == {"type": "http.request", "body": last_chunk, "more_body": False}
    assert run(replay()) == {"type": "http.disconnect"}


# ---------------------------------------------------------------------------
# 서류 읽기 동시 처리 수, 대기열, 마감 시간
# ---------------------------------------------------------------------------


def slow_ai(monkeypatch, seconds, counts=None):
    async def slow(kwargs):
        if counts is not None:
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        try:
            await asyncio.sleep(seconds)
        finally:
            if counts is not None:
                counts["active"] -= 1
        return make_response(REGISTRY_OK)

    monkeypatch.setattr(extract, "_client", FakeClient(lambda kwargs, _n: slow(kwargs)))


def test_ai_calls_are_limited_and_others_wait(monkeypatch):
    monkeypatch.setattr(main, "AI_SLOTS", 2)
    counts = {"active": 0, "peak": 0}
    slow_ai(monkeypatch, 0.3, counts)
    pdf = make_pdf(1)

    async def scenario():
        return await asyncio.gather(*(upload_call(pdf) for _ in range(5)))

    results = run(scenario())
    assert [status for status, _, _ in results] == [200] * 5  # 기다린 요청도 처리된다
    assert counts["peak"] == 2


def test_upload_bodies_are_limited_before_reading(monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_SLOTS", 2)
    slow_ai(monkeypatch, 0)
    body, headers = multipart_body("registry.pdf", make_pdf(1))
    scope_headers = [(b"content-type", headers["content-type"].encode()), (b"content-length", str(len(body)).encode())]
    reading = {"now": 0, "peak": 0}

    def slow_sender():
        state = {"sent": False}

        async def receive():
            if state["sent"]:
                await asyncio.sleep(3600)
            state["sent"] = True
            reading["now"] += 1
            reading["peak"] = max(reading["peak"], reading["now"])
            await asyncio.sleep(0.2)  # 본문을 천천히 보낸다
            reading["now"] -= 1
            return {"type": "http.request", "body": body, "more_body": False}

        return receive

    async def scenario():
        return await asyncio.gather(*(asgi_call(main.EXTRACT_PATH, slow_sender(), scope_headers) for _ in range(5)))

    results = run(scenario())
    assert [status for status, _, _ in results] == [200] * 5
    assert reading["peak"] == 2  # 동시에 본문을 받는 요청은 업로드 자리 수까지


def test_slow_uploads_do_not_block_other_users(monkeypatch):
    # 느린 업로드가 업로드 자리 일부를 잡고 있어도, 다른 사용자는 남은 자리로 바로 처리된다
    monkeypatch.setattr(main, "UPLOAD_SLOTS", 3)
    slow_ai(monkeypatch, 0)
    pdf = make_pdf(1)

    async def stalled():  # 본문을 조금 보내고 멈춘 연결 (아직 끊기기 전)
        await asyncio.sleep(3)
        return {"type": "http.disconnect"}

    async def scenario():
        holders = [
            asyncio.ensure_future(
                asgi_call(main.EXTRACT_PATH, stalled, [(b"content-type", b"multipart/form-data; boundary=x")])
            )
            for _ in range(2)
        ]
        await asyncio.sleep(0.1)
        started = time.perf_counter()
        status, _, _ = await upload_call(pdf)
        took = time.perf_counter() - started
        for holder in holders:
            holder.cancel()
        await asyncio.gather(*holders, return_exceptions=True)
        return status, took

    status, took = run(scenario())
    assert status == 200 and took < 2


def test_upload_slot_is_handed_over_when_ai_starts(monkeypatch):
    # AI를 부르는 동안에는 업로드 자리를 놓으므로, 업로드 자리가 하나여도 두 요청이 겹쳐 처리된다
    monkeypatch.setattr(main, "UPLOAD_SLOTS", 1)
    slow_ai(monkeypatch, 1.0)
    pdf = make_pdf(1)

    async def scenario():
        started = time.perf_counter()
        results = await asyncio.gather(upload_call(pdf), upload_call(pdf))
        return results, time.perf_counter() - started

    results, took = run(scenario())
    assert [status for status, _, _ in results] == [200, 200]
    assert took < 1.8  # 하나씩 처리했다면 2초 넘게 걸린다


def test_ai_queue_waits_until_deadline_then_busy(monkeypatch):
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "1.5")
    monkeypatch.setattr(main, "AI_SLOTS", 1)
    slow_ai(monkeypatch, 0)

    async def scenario():
        slots = main.ai_slots()
        await slots.acquire()  # 다른 요청이 AI를 오래 부르고 있다
        started = time.perf_counter()
        result = await upload_call(make_pdf(1))
        took = time.perf_counter() - started
        slots.release()
        return result, took, main.upload_slots()._value, main.ai_slots()._value

    (status, _, body), took, free_upload, free_ai = run(scenario())
    assert status == 503
    assert json.loads(body) == {"error": {"code": "BUSY", "message": ERROR_MESSAGES["BUSY"]}}
    assert 1.3 < took < 2.2  # 예전처럼 정해진 시간이 아니라, 요청이 들어온 때부터 마감(1.5초)까지 기다렸다
    assert (free_upload, free_ai) == (main.UPLOAD_SLOTS, main.AI_SLOTS)


def test_upload_queue_waits_until_deadline_then_busy(monkeypatch):
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "0.5")
    monkeypatch.setattr(main, "UPLOAD_SLOTS", 1)

    async def scenario():
        slots = main.upload_slots()
        await slots.acquire()  # 업로드 자리가 모두 찼다
        started = time.perf_counter()
        result = await upload_call(make_pdf(1))
        slots.release()
        return result, time.perf_counter() - started

    (status, headers, body), took = run(scenario())
    assert status == 503 and json.loads(body)["error"]["code"] == "BUSY"
    assert headers["connection"] == "close"  # 읽지 않은 본문이 남은 연결은 닫는다
    assert 0.4 < took < 1.5


def test_no_api_key_does_not_wait_for_ai_slot(monkeypatch):
    monkeypatch.setattr(main, "AI_SLOTS", 1)

    async def scenario():
        await main.ai_slots().acquire()  # AI 자리가 모두 찼다
        started = time.perf_counter()
        status, _, body = await upload_call(make_pdf(1))
        return status, json.loads(body), time.perf_counter() - started

    status, body, took = run(scenario())
    assert (status, body["error"]["code"]) == (503, "AI_FAILED")
    assert took < 1.5


def test_slots_are_released_on_every_path(monkeypatch):
    monkeypatch.setattr(main, "BODY_IDLE_SECONDS", 0.2)
    monkeypatch.setattr(main, "DISCONNECT_POLL_SECONDS", 0.05)

    async def handler(kwargs, n):
        if n == 1:
            return make_response(REGISTRY_OK)  # 성공
        if n == 2:
            return make_response(None, stop_reason="refusal")  # AI 실패
        await asyncio.sleep(30)  # 클라이언트가 떠날 때까지 끝나지 않는다

    monkeypatch.setattr(extract, "_client", FakeClient(handler))
    pdf = make_pdf(1)
    body, headers = multipart_body("registry.pdf", pdf)
    scope_headers = [(b"content-type", headers["content-type"].encode()), (b"content-length", str(len(body)).encode())]

    def leaves_after(seconds):
        state = {"leave_at": None}

        async def receive():
            loop = asyncio.get_running_loop()
            if state["leave_at"] is None:
                state["leave_at"] = loop.time() + seconds
                return {"type": "http.request", "body": body, "more_body": False}
            if loop.time() < state["leave_at"]:  # 연결 확인은 취소된 채로 불리므로 남은 시간만 기다린다
                await asyncio.sleep(state["leave_at"] - loop.time())
            return {"type": "http.disconnect"}

        return receive

    async def stalls():
        await asyncio.sleep(3600)

    async def scenario():
        statuses = [
            (await upload_call(pdf))[0],  # 200
            (await upload_call(pdf))[0],  # 502
            (await upload_call(make_pdf(31)))[0],  # 400 파일 오류
        ]
        started = time.perf_counter()
        await asgi_call(main.EXTRACT_PATH, leaves_after(0.3), scope_headers)  # AI 호출 중 떠남
        assert time.perf_counter() - started < 3  # AI 호출(30초)을 기다리지 않고 취소했다
        statuses.append((await asgi_call(main.EXTRACT_PATH, stalls, scope_headers))[0])  # 408 본문이 멈춤
        return statuses, main.upload_slots()._value, main.ai_slots()._value

    statuses, free_upload, free_ai = run(scenario())
    assert statuses == [200, 502, 400, 408]
    assert (free_upload, free_ai) == (main.UPLOAD_SLOTS, main.AI_SLOTS)


def test_deadline_counts_from_request_start(monkeypatch):
    # AI 자리를 기다린 시간도 마감에 들어간다 (화면의 90초 시계보다 먼저 끝나야 한다)
    monkeypatch.setenv("EXTRACT_DEADLINE_SECONDS", "2")
    monkeypatch.setattr(main, "AI_SLOTS", 1)

    async def handler(kwargs, n):
        await asyncio.sleep(1.2 if n == 1 else 30)  # 첫 요청은 1.2초, 둘째 요청은 끝나지 않는다
        return make_response(REGISTRY_OK)

    monkeypatch.setattr(extract, "_client", FakeClient(handler))
    pdf = make_pdf(1)

    async def second():
        await asyncio.sleep(0.05)
        started = time.perf_counter()
        result = await upload_call(pdf)
        return result, time.perf_counter() - started

    async def scenario():
        return await asyncio.gather(upload_call(pdf), second())

    first, ((status, _, body), took) = run(scenario())
    assert first[0] == 200
    assert status == 502 and json.loads(body)["error"]["code"] == "AI_FAILED"
    assert took < 2.8  # 요청 시작부터 2초 (대기 ~1.3초 + AI 2초를 기다리지 않는다)


def test_busy_error_contract():
    error = extract.ApiError.busy("ai")
    assert (error.code, error.status, error.message) == ("BUSY", 503, "지금 서류를 읽는 사람이 많아요. 잠시 후 다시 시도해 주세요.")
    assert error.document is None


def test_with_deadline_uses_start_time():
    async def never(deadline):
        await asyncio.sleep(30)

    async def scenario():
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        with pytest.raises(extract.ApiError) as e:
            await extract._with_deadline(never, started_at=loop.time() - extract.deadline_seconds() + 0.2)
        return e.value, time.perf_counter() - started

    error, took = run(scenario())
    assert (error.code, error.status) == ("AI_FAILED", 502)
    assert took < 1


# ---------------------------------------------------------------------------
# 422 형식과 HTTP 오류 형식
# ---------------------------------------------------------------------------


def test_validation_error_is_short_and_does_not_echo_input(client):
    secret = "김비밀 850315-1234567 서울시 비밀구 비밀로 1"
    entry = {"rank": 1, "purpose": secret, "holders": secret, "received_at": secret}  # 항목마다 오류 여러 개
    body = {"registry": {"gapgu": [entry] * 400, secret: 1}, "today": secret}
    started = time.perf_counter()
    r = client.post("/api/check", json=body)
    assert time.perf_counter() - started < 2
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert 0 < len(detail) <= main.MAX_VALIDATION_ERRORS
    for item in detail:
        assert set(item) == {"loc", "msg", "type"}
    for part in ("김비밀", "850315", "비밀구"):
        assert part not in r.text
    assert len(r.content) < 10_000


def test_unknown_key_is_not_echoed_in_loc(client):
    r = client.post("/api/check", json={"registry": REGISTRY_OK, "김비밀 850315-1234567": 1})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "?"]
    assert "김비밀" not in r.text


def test_invalid_json_is_422_without_body(client):
    r = client.post("/api/check", content=b'{"registry": "\xea\xb9\x80\xeb\xb9\x84\xeb\xb0\x80', headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert "김비밀" not in r.text


def test_multipart_errors_use_standard_shape(client):
    # boundary 없음
    r = client.post("/api/extract", content=b"--x\r\n", headers={"content-type": "multipart/form-data"})
    assert_error(r, 400, "UNSUPPORTED_FILE")
    # 조각 1000개 초과
    parts = "".join(f'--b\r\nContent-Disposition: form-data; name="f{i}"\r\n\r\nv\r\n' for i in range(1001))
    r = client.post(
        "/api/extract/contract",
        content=(parts + "--b--\r\n").encode(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    assert_error(r, 400, "UNSUPPORTED_FILE")
    # 파일이 아닌 칸이 1MB 초과
    big = '--b\r\nContent-Disposition: form-data; name="registry"\r\n\r\n' + "a" * (1024 * 1024 + 10) + "\r\n--b--\r\n"
    r = client.post("/api/extract", content=big.encode(), headers={"content-type": "multipart/form-data; boundary=b"})
    assert_error(r, 400, "UNSUPPORTED_FILE")


def test_unknown_path_and_wrong_method_use_standard_shape(client):
    assert_error(client.get("/api/nope"), 404, "INVALID_REQUEST", document=None)
    r = client.get("/api/check")
    assert_error(r, 405, "INVALID_REQUEST")
    assert "POST" in r.headers["allow"]


def test_file_errors_say_which_document(client, monkeypatch):
    install_ai(monkeypatch)
    assert_error(client.post("/api/extract", files=registry_file(PNG)), 400, "UNSUPPORTED_FILE", document="registry")
    gif = {**registry_file(), "contract": ("c.gif", b"GIF89a" + b"\x00" * 32, "image/gif")}
    assert_error(client.post("/api/extract", files=gif), 400, "UNSUPPORTED_FILE", document="contract")
    assert_error(client.post("/api/extract"), 400, "UNSUPPORTED_FILE", document="registry")  # 등기부 칸이 없다
    huge = registry_file(b"%PDF" + b"0" * (uploads.MAX_REQUEST_BYTES + 1))
    assert_error(client.post("/api/extract", files=huge), 400, "UNSUPPORTED_FILE", document=None)

    install_ai(monkeypatch, registry=make_response({**REGISTRY_OK, "is_registry": False}))
    assert_error(client.post("/api/extract", files=registry_file()), 422, "NOT_REGISTRY", document="registry")
    install_ai(
        monkeypatch, registry=make_response(REGISTRY_OK), contract=make_response({**CONTRACT_OK, "is_contract": False})
    )
    with_contract = {**registry_file(), "contract": ("c.png", PNG, "image/png")}
    assert_error(client.post("/api/extract", files=with_contract), 422, "NOT_CONTRACT", document="contract")
    # AI 실패는 파일 문제가 아니다
    install_ai(monkeypatch, registry=make_response(None, stop_reason="refusal"))
    assert_error(client.post("/api/extract", files=registry_file()), 502, "AI_FAILED", document=None)


# ---------------------------------------------------------------------------
# 입력 모델 상한
# ---------------------------------------------------------------------------


def contract_with(**changes):
    return {**CONTRACT_OK, **changes}


@pytest.mark.parametrize(
    "body",
    [
        {"registry": REGISTRY_OK, "today": "9999-12-31"},
        {"registry": REGISTRY_OK, "today": "0001-01-01"},
        {"registry": {**REGISTRY_OK, "viewed_at": "9999-12-31T23:59:59-12:00"}},
        {"registry": {**REGISTRY_OK, "viewed_at": "0001-01-01T00:00:00+14:00"}},
        {"registry": REGISTRY_OK, "contract": contract_with(lease_end="9999-12-31")},
        {"registry": REGISTRY_OK, "manual": {"contract_date": "1899-12-31"}},
        {"registry": {**REGISTRY_OK, "address_jibun": "가" * 501}},
        {"registry": {**REGISTRY_OK, "gapgu": [REGISTRY_OK["gapgu"][0]] * 501}},
        {"registry": {**REGISTRY_OK, "gapgu": [{**REGISTRY_OK["gapgu"][0], "source_text": "가" * 2001}]}},
        {"registry": {**REGISTRY_OK, "gapgu": [{**REGISTRY_OK["gapgu"][0], "holders": ["김"] * 51}]}},
        {"registry": REGISTRY_OK, "contract": contract_with(special_terms=["특약"] * 101)},
        {"registry": REGISTRY_OK, "contract": contract_with(landlord_names=["김" * 201])},
        {"registry": REGISTRY_OK, "contract": contract_with(deposit=10**16)},
        {"registry": {**REGISTRY_OK, "unit": {"area_m2": "NaN"}}},
    ],
    ids=["today-9999", "today-0001", "viewed-9999", "viewed-0001", "lease-end-9999", "manual-1899", "long-address",
         "501-entries", "long-source", "51-holders", "101-terms", "long-name", "huge-deposit", "nan-area"],
)
def test_check_input_limits_are_422_not_500(client, monkeypatch, body):
    monkeypatch.setattr(main, "build_report", lambda req: pytest.fail("규칙 엔진까지 오면 안 된다"))
    assert client.post("/api/check", json=body).status_code == 422


@pytest.mark.parametrize(
    "viewed_at", ["9999-12-31T20:00:00Z", "9999-12-31T23:59:59-12:00", "0001-01-01T00:00:00+14:00"]
)
def test_recheck_out_of_range_baseline_is_422(client, viewed_at):
    body = {"registry": REGISTRY_OK, "contract": CONTRACT_OK, "baseline_viewed_at": viewed_at, "today": "2026-11-29"}
    assert client.post("/api/recheck", json=body).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"checklist": [{"when": "잔금일", "date": "9999-12-31", "title": "잔금"}]},
        {"checklist": [{"when": "잔금일", "date": "0001-01-01", "title": "잔금"}]},
        {"checklist": [{"when": "잔금일", "date": None, "title": "잔금"}] * 301},
        {"checklist": [], "address": "가" * 501},
    ],
    ids=["date-9999", "date-0001", "301-items", "long-address"],
)
def test_ics_input_limits_are_422(client, body):
    assert client.post("/api/checklist.ics", json=body).status_code == 422


def test_limits_allow_boundary_values(client, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "build_report", lambda req: seen.append(req) or make_report(req))
    body = {
        "registry": {**REGISTRY_OK, "address_jibun": "가" * 500, "viewed_at": "2100-12-31T23:59:59-12:00"},
        "contract": contract_with(special_terms=["특약"] * 100, lease_end="1900-01-01", deposit=10**15),
        "today": "2100-12-31",
    }
    r = client.post("/api/check", json=body)
    assert r.status_code == 200, r.text
    assert seen[0].registry.viewed_at.year == 2100


# ---------------------------------------------------------------------------
# .ics 보호
# ---------------------------------------------------------------------------


def test_ics_strips_control_and_line_separator_chars():
    req = IcsRequest.model_validate(
        {
            "checklist": [{"when": "잔금일", "date": "2026-12-31", "title": "a b c\x85d\x00e\x1bf\x7fg\x0bh"}],
            "address": "주소 DTSTART:20000101",
        }
    )
    text = ics.build_ics(req, now=NOW)
    for ch in "  \x85\x00\x1b\x7f\x0b":
        assert ch not in text
    lines = unfold(text)
    assert "SUMMARY:[보증금 지킴이] 잔금일: abcdefgh" in lines
    assert "DESCRIPTION:주소: 주소DTSTART:20000101" in lines  # 새 줄(속성)로 끼어들지 못한다
    assert "DTSTART:20000101" not in lines


def test_ics_dates_are_zero_padded_and_overflow_safe():
    # 입력 모델이 막는 범위지만, ics 자체도 넘치지 않게 한다
    req = IcsRequest.model_construct(
        checklist=[
            ChecklistItem.model_construct(when="잔금일", date=dt.date(999, 1, 2), title="옛날"),
            ChecklistItem.model_construct(when="입주일", date=dt.date.max, title="끝"),
        ],
        address=None,
    )
    lines = unfold(ics.build_ics(req, now=NOW))
    assert "DTSTART;VALUE=DATE:09990102" in lines and "DTEND;VALUE=DATE:09990103" in lines
    assert lines.count("BEGIN:VEVENT") == 1  # 다음 날을 쓸 수 없는 9999-12-31은 건너뛴다


def test_ics_masks_ids_and_phone_numbers(client):
    body = {
        "checklist": [{"when": "잔금일", "date": "2026-12-31", "title": "임대인 010-1234-5678 연락, 6208301234567 확인"}],
        "address": "서울 620830-1234567 (02-123-4567)",
    }
    r = client.post("/api/checklist.ics", json=body)
    assert r.status_code == 200
    text = "\n".join(unfold(r.text))
    for part in ("1234-5678", "620830", "123-4567"):
        assert part not in text
    assert "010-****-****" in text and "******-*******" in text


# ---------------------------------------------------------------------------
# 주민등록번호·전화번호 가리기
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rrn",
    [
        "6208301234567",
        "620830 1234567",
        "620830-1 234567",
        "620830ㅡ1234567",
        "620830⁃1234567",
        "620830﹣1234567",
        "620830―1234567",
        "620830-1######",
        "620830-1■■■■■■",
        "620830-1●●●●●●",
        "620830 1******",
        "0101014123456",  # 2001년생 (7번째 자리 3·4)
        "620830.1234567",
        "620830/1234567",
        "620830~1234567",
        "620830_1234567",
        "620830‧1234567",
        "620830ㅣ1234567",
        "620830ｰ1234567",
        "620830 . 1234567",
        "620830-1･･････",
        "620830-1∙∙∙∙∙∙",
        "620830-1······",
        "６２０８３０１２３４５６７",  # 전각 숫자
        "６２０８３０－１２３４５６７",
        "620830   1234567",  # 띄어쓰기 3칸
        "620830\n1234567",  # 줄바꿈 하나
        "620830 \n 1******",
    ],
)
def test_more_resident_id_shapes_are_masked(rrn):
    assert privacy.mask_text(f"소유자 김민수 {rrn} 서울") == "소유자 김민수 ******-******* 서울"
    assert privacy.RESIDENT_ID.search(rrn)


@pytest.mark.parametrize(
    "text",
    [
        "계좌 1002345678901",  # 13자리지만 생년월일이 아니다 (34일)
        "계좌 3333-01-2345678",
        "6208301234567890",  # 16자리
        "6208309234567",  # 7번째 자리 9
        "1588-1234",
        "0212345678",  # 지역번호는 구분 글자가 있을 때만
        "02-12-31",
        "계좌 02-123-4567-89",
        "2026-11-14 ~ 2027-11-13",
        "사업자번호 123-45-67890",
        "제12345호",
        "1144-2005-012345",
        "계좌 110-123-456789",
        "계좌 1002-123-456789",
        "123456-12-123456",
        "3020123456781",
        "금120,000,000원 (₩10,000,000)",
        "보증금 1,000,000,000원",
        "2026.11.14",
        "2026/11/14",
        "20261114",
        "2026.11.14 10:30",
        "26.11.14",
        "123101.1234567",  # 생년월일이 아니다 (31월)
        "620830    1234567",  # 띄어쓰기 4칸
        "620830\n\n1234567",  # 줄바꿈 둘
        "동·호 302·303호",
    ],
)
def test_other_numbers_are_left_alone(text):
    assert privacy.mask_text(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("010-1234-5678", "010-****-****"),
        ("01012345678", "010********"),
        ("010 1234 5678", "010 **** ****"),
        ("010.1234.5678", "010.****.****"),
        ("011-123-4567", "011-***-****"),
        ("02-123-4567", "02-***-****"),
        ("02-1234-5678", "02-****-****"),
        ("031-123-4567", "031-***-****"),
        ("(031)123-4567", "(031)***-****"),
        ("070-1234-5678", "070-****-****"),
        ("연락처:010-1234-5678.", "연락처:010-****-****."),
        ("010ㅡ1234ㅡ5678", "010ㅡ****ㅡ****"),
        ("+82-10-1234-5678", "+82-10-****-****"),
        ("+82 10 1234 5678", "+82 10 **** ****"),
        ("+821012345678", "+8210********"),
        ("+82-2-123-4567", "+82-2-***-****"),
        ("０１０-１２３４-５６７８", "０１０-****-****"),
        ("０１０１２３４５６７８", "０１０********"),
    ],
)
def test_phone_numbers_keep_only_the_prefix(text, expected):
    masked = privacy.mask_text(text)
    assert masked == expected
    assert len(masked) == len(text)  # 길이를 바꾸지 않는다 (글자 수 상한을 넘기지 않게)


def test_masking_is_idempotent():
    text = "김민수 6208301234567 010-1234-5678 02-123-4567"
    once = privacy.mask_text(text)
    assert privacy.mask_text(once) == once


def test_check_response_is_masked(client, monkeypatch):
    def echo_report(req):
        report = make_report(req)
        quote = Evidence(doc="contract", text=req.contract.special_terms[0])
        result = RuleResult(id="R12", name="보호 특약 없음", level="yellow", evidence=[quote])
        return report.model_copy(update={"results": [result], "request_message": req.contract.special_terms[0]})

    monkeypatch.setattr(main, "build_report", echo_report)
    term = "임대인 김민수(6208301234567, 010-1234-5678)은 담보를 설정하지 않는다."
    r = client.post("/api/check", json={"registry": REGISTRY_OK, "contract": contract_with(special_terms=[term])})
    assert r.status_code == 200, r.text
    assert "620830" not in r.text and "1234-5678" not in r.text
    report = Report.model_validate(r.json())
    assert report.request_message == "임대인 김민수(******-*******, 010-****-****)은 담보를 설정하지 않는다."


# ---------------------------------------------------------------------------
# AI 응답 처리
# ---------------------------------------------------------------------------


def bad_body():
    return json.JSONDecodeError("Expecting value", "", 0)  # 200 응답의 본문이 비었을 때 SDK가 내는 오류


def test_empty_ai_body_is_retried_then_ai_failed(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=[bad_body(), bad_body()])
    assert_error(client.post("/api/extract", files=registry_file()), 502, "AI_FAILED")
    assert len(fake.messages.calls) == 2


def test_empty_ai_body_retry_can_succeed(client, monkeypatch):
    fake = install_ai(monkeypatch, registry=[bad_body(), make_response(REGISTRY_OK)])
    assert client.post("/api/extract", files=registry_file()).status_code == 200
    assert len(fake.messages.calls) == 2


def test_openai_empty_body_is_retried():
    client = openai_client(bad_body(), make_reply(REGISTRY_OK))
    result = run(extract.extract_registry(client, PDF_DOC))
    assert result.is_registry and len(client.sdk.responses.calls) == 2


def test_openai_output_text_parts_are_joined():
    text = json.dumps(REGISTRY_OK, ensure_ascii=False)
    reply = make_reply(REGISTRY_OK)
    half = len(text) // 2
    reply.output[1].content = [
        SimpleNamespace(type="output_text", text=text[:half]),
        SimpleNamespace(type="output_text", text=text[half:]),
    ]
    result = run(extract.extract_registry(openai_client(reply), PDF_DOC))
    assert result.building_name == REGISTRY_OK["building_name"]


def test_impossible_dates_are_emptied_instead_of_failing(client, monkeypatch):
    registry = copy.deepcopy(REGISTRY_OK)
    registry["viewed_at"] = "2026-02-30T10:00:00+09:00"
    registry["gapgu"][0]["received_at"] = "2019-04-31"
    registry["unreadable"] = ["2쪽 하단이 흐림"]
    contract = contract_with(lease_end="2027-02-29", balance_date="9999-12-31")
    install_ai(monkeypatch, registry=make_response(registry), contract=make_response(contract))
    r = client.post("/api/extract", files={**registry_file(), "contract": ("c.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    reg, con = r.json()["registry"], r.json()["contract"]
    assert reg["viewed_at"] is None and reg["gapgu"][0]["received_at"] is None
    assert reg["gapgu"][0]["holders"] == ["김민수"]  # 나머지는 그대로
    assert reg["unreadable"] == ["2쪽 하단이 흐림", "갑구 2번 접수일을 읽지 못함", "열람 일시를 읽지 못함"]
    assert con["lease_end"] is None and con["balance_date"] is None
    assert con["contract_date"] == "2026-11-14" and con["deposit"] == 10_000_000


@pytest.mark.parametrize(
    ("viewed_at", "expected", "note"),
    [
        ("2100-12-31T23:30:00-12:00", None, True),  # 한국 시간으로 바꾸면 2101년
        ("1900-01-01T05:00:00+14:00", "1900-01-01T00:00:00+09:00", False),
        ("2026-11-14T10:31:22", "2026-11-14T10:31:22+09:00", False),  # 시간대가 없으면 한국 시간
    ],
)
def test_viewed_at_is_checked_after_kst_conversion(client, monkeypatch, viewed_at, expected, note):
    install_ai(monkeypatch, registry=make_response({**REGISTRY_OK, "viewed_at": viewed_at}))
    r = client.post("/api/extract", files=registry_file())
    assert r.status_code == 200, r.text
    registry = r.json()["registry"]
    assert registry["viewed_at"] == expected
    assert ("열람 일시를 읽지 못함" in registry["unreadable"]) is note


def test_cut_values_are_noted_in_unreadable():
    registry = copy.deepcopy(REGISTRY_OK)
    entry = registry["gapgu"][0]
    registry["gapgu"] = [dict(entry, rank=str(i + 1)) for i in range(600)]
    registry["gapgu"][1]["holders"] = [f"권리자{i}" for i in range(80)]
    registry["gapgu"][2]["source_text"] = "가" * 3000
    registry["address_jibun"] = "나" * 600
    result = run(extract.extract_registry(openai_client(make_reply(registry)), PDF_DOC))
    assert len(result.gapgu) == 500 and len(result.gapgu[1].holders) == 50
    assert set(result.unreadable) == {
        "갑구 2번 권리자가 많아 앞의 50개만 옮김",
        "갑구 3번 원문이 길어 앞부분만 옮김",
        "지번 주소가 길어 앞부분만 옮김",
        "갑구 항목이 많아 앞의 500개만 옮김",
    }


def test_notes_fit_into_a_full_unreadable_list():
    registry = copy.deepcopy(REGISTRY_OK)
    registry["unreadable"] = [f"흐림 {i}" for i in range(150)]
    registry["gapgu"][0]["received_at"] = "2019-02-30"
    result = run(extract.extract_registry(openai_client(make_reply(registry)), PDF_DOC))
    assert len(result.unreadable) == 100
    assert result.unreadable[-1] == "갑구 2번 접수일을 읽지 못함"  # 상한이 차 있어도 메모가 남는다
    assert result.unreadable[0] == "흐림 0"


def test_overlong_ai_values_are_trimmed():
    registry = copy.deepcopy(REGISTRY_OK)
    registry["gapgu"][0]["source_text"] = "가" * 3000
    registry["gapgu"][0]["holders"] = ["김민수"] * 80
    registry["unreadable"] = ["흐림"] * 150
    client = openai_client(make_reply(registry))
    result = run(extract.extract_registry(client, PDF_DOC))
    assert len(result.gapgu[0].source_text) == 2000
    assert len(result.gapgu[0].holders) == 50
    assert len(result.unreadable) == 100
    assert set(result.unreadable[-2:]) == {"갑구 2번 원문이 길어 앞부분만 옮김", "갑구 2번 권리자가 많아 앞의 50개만 옮김"}


def test_ai_values_are_masked_before_validation():
    contract = contract_with(special_terms=["연락처 01012345678, 주민번호 6208301234567"])
    result = run(extract.extract_contract(openai_client(make_reply(contract)), PNG_DOC))
    assert result.special_terms == ["연락처 010********, 주민번호 ******-*******"]


@pytest.mark.parametrize(
    "registry",
    [
        {**REGISTRY_OK, "extra": 1},
        {**REGISTRY_OK, "is_registry": "maybe"},
        {**REGISTRY_OK, "gapgu": [{"rank": "1"}]},  # 등기목적 없음
        ["not", "an", "object"],
    ],
    ids=["extra-field", "bad-bool", "missing-field", "not-object"],
)
def test_unfixable_ai_output_still_fails(registry):
    with pytest.raises(extract.ApiError) as e:
        run(extract.extract_registry(openai_client(make_reply(registry)), PDF_DOC))
    assert e.value.reason == "registry:schema_mismatch"


@pytest.mark.parametrize(
    "mark", ["해당사항 없음", "N/A", "n/a", "없습니다", "특약사항: 없음", "특약사항 : 없음.", "1. 없음", "이하 여백", "(없음)"]
)
def test_more_no_term_marks_are_dropped(mark):
    real = "반려동물 없음을 확인한다."
    payload = contract_with(special_terms=[mark, real])
    result = run(extract.extract_contract(openai_client(make_reply(payload)), PNG_DOC))
    assert result.special_terms == [real]


# ---------------------------------------------------------------------------
# AI 설정
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"), [("gpt", "openai"), (" GPT ", "openai"), ("claude", "anthropic"), ("Claude", "anthropic")]
)
def test_provider_aliases(monkeypatch, value, expected):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("AI_PROVIDER", value)
    assert extract.ai_provider() == expected


def test_unknown_provider_warns_once_without_value(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AI_PROVIDER", "gemini-secret")
    assert extract.ai_provider() == "openai"
    assert extract.ai_provider() == "openai"
    warnings = [r for r in caplog.records if "AI_PROVIDER" in r.getMessage()]
    assert len(warnings) == 1
    assert "gemini-secret" not in caplog.text


@pytest.mark.parametrize(("value", "expected"), [("turbo", "low"), ("HIGH", "high"), ("", "low"), ("minimal", "minimal")])
def test_reasoning_effort_is_checked_against_sdk_values(monkeypatch, caplog, value, expected):
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", value)
    client = extract.OpenAIClient(SimpleNamespace())
    assert client.effort == expected
    assert ("invalid OPENAI_REASONING_EFFORT" in caplog.text) is (value == "turbo")
    assert {"low", "medium", "high"} <= extract.OPENAI_EFFORTS


def test_startup_log_names_provider_model_and_effort(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "medium")
    with TestClient(main.app):
        pass
    assert "ai_ready=True provider=openai model=gpt-test-model effort=medium" in caplog.text
    assert "sk-test-secret" not in caplog.text


def test_startup_log_without_key(caplog):
    caplog.set_level(logging.INFO)
    with TestClient(main.app):
        pass
    assert "ai_ready=False provider=- model=- effort=-" in caplog.text
