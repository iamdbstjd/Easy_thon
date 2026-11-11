"""PDF 구조 검사(암호 풀기·쪽수 세기)를 메모리·CPU 상한이 걸린 별도 프로세스에서 한다.

pypdf는 순수 파이썬이라, 일부러 만든 PDF(압축 객체 폭탄, 끝없는 쪽 트리 등) 하나로 서버가 수십 초·수백 MB를
쓸 수 있다. 그래서 검사마다 새 파이썬 프로세스(-I, 격리 모드)를 띄운다.

- 부모는 WALL_TIMEOUT_SECONDS가 지나면 자식을 죽인다 (모든 운영체제).
- resource 모듈이 있는 곳(리눅스·macOS)에서는 자식에 주소 공간(RLIMIT_AS)·CPU 시간·파일 쓰기 0바이트·코어 파일 0
  상한을 건다. 운영체제가 받지 않는 상한은 건너뛴다 (윈도우에는 resource가 없다).
- PDF는 표준 입력(파이프)으로 넘기고 결과는 표준 출력으로 받는다. 디스크에는 아무것도 쓰지 않는다.
- 자식의 표준 오류(pypdf 경고)는 버린다. 경고에 문서 내용이 섞일 수 있어서다.
- 자식에는 운영체제·파이썬이 시작하는 데 필요한 환경변수(PATH, SYSTEMROOT 등)만 넘긴다. API 키는 넘기지 않는다.
  -I 모드는 PYTHONPATH를 무시하므로, pypdf를 찾을 수 있게 부모의 sys.path를 넘겨 뒤에 붙인다.
- 자식이 PDF를 받기 전 준비(파이썬 시작, pypdf 불러오기)에 실패하면 PDF 탓이 아니다. 그때는 오류 로그를 남기고
  같은 프로세스에서 검사한다 (시간·메모리 상한 없이 pypdf 자체 상한만). 시연 노트북에서 PDF가 모두 거절되는 것보다 낫다.
- 서버가 시작할 때 self_test()로 작은 PDF를 한 번 검사해 결과를 로그에 남긴다.

이 모듈은 자식 프로세스에서도 불러오므로 표준 라이브러리와 pypdf만 쓴다 (fastapi 등을 불러오지 않는다).
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple, Optional

MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
CPU_LIMIT_SECONDS = 10  # 부모의 시간 상한이 먼저 걸린다. 부모가 죽어도 자식이 끝나도록 둔 안전장치다.
WALL_TIMEOUT_SECONDS = 8.0
SETUP_EXIT = 3  # 자식이 준비 단계에서 실패했을 때의 종료 코드 (PDF 탓이 아니다)
READY = b"R"  # 자식이 준비를 마치고 PDF를 읽기 전에 보내는 1바이트

CHILD_FLAGS = ("-I",)  # 격리 모드: 환경변수·사용자 site·현재 폴더를 쓰지 않는다
# 자식에 넘기는 환경변수. 윈도우 파이썬은 SYSTEMROOT가 없으면 시작하지 못한다. 비밀 값은 넣지 않는다.
CHILD_ENV_NAMES = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE"})

BACKEND_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger("app.pdf_sandbox")

# 자식 프로세스를 쓸 수 없는 사유. None이면 자식 프로세스에서 검사한다.
_unavailable: Optional[str] = None


class PdfCheck(NamedTuple):
    """검사 결과. outcome이 "ok"가 아니면 거절 사유 코드다.

    plain은 소유자 암호를 풀어 다시 쓴 사본이다. 원본에 암호가 없으면 None (원본을 그대로 쓴다).
    """

    outcome: str
    pages: int = 0
    plain: Optional[bytes] = None


# ---------------------------------------------------------------------------
# 검사 본체 (자식 프로세스 안에서 돈다. 자식을 쓸 수 없으면 서버 프로세스에서 돈다)
# ---------------------------------------------------------------------------


def _declared_pages(reader) -> Optional[int]:
    """쪽 트리 맨 위의 /Count. 없거나 숫자가 아니면 None."""
    try:
        count = reader.trailer["/Root"]["/Pages"]["/Count"]
    except Exception:
        return None
    return count if isinstance(count, int) else None


def inspect(data: bytes, *, max_pages: int, max_plain_bytes: int) -> PdfCheck:
    """PDF를 열어 암호와 쪽수를 확인한다. 소유자 암호만 걸려 있으면 빈 열람 암호로 풀어 암호 없는 사본을 만든다."""
    from pypdf import PasswordType, PdfReader, PdfWriter
    from pypdf.errors import DependencyError

    try:
        reader = PdfReader(io.BytesIO(data))
        encrypted = reader.is_encrypted
        if encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            return PdfCheck("encrypted_pdf")  # 열람 암호가 있어야 열린다
        # 선언된 쪽수가 이미 상한을 넘으면 쪽 트리를 다 펼치지 않고 바로 거절한다.
        # (선언을 적게 속인 파일은 아래에서 실제로 세어 잡는다)
        declared = _declared_pages(reader)
        if declared is not None and declared > max_pages:
            return PdfCheck("ok", pages=declared)
        plain = None
        if encrypted:
            buf = io.BytesIO()
            PdfWriter(clone_from=reader).write(buf)  # 암호 설정 없이 다시 쓴다
            plain = buf.getvalue()
            if len(plain) > max_plain_bytes:
                return PdfCheck("too_large_after_decrypt")
            reader = PdfReader(io.BytesIO(plain))
            if reader.is_encrypted:
                return PdfCheck("encrypted_pdf")
        return PdfCheck("ok", pages=len(reader.pages), plain=plain)
    except DependencyError:  # AES 암호인데 cryptography가 설치되지 않았다
        return PdfCheck("encrypted_pdf_needs_cryptography")
    except MemoryError:
        return PdfCheck("pdf_too_complex")
    except Exception:  # 깨진 PDF (pypdf 예외 종류가 다양하다). RecursionError도 여기로 온다.
        return PdfCheck("broken_pdf")


def _set_limits(memory: int, cpu: int) -> bool:
    """자식 프로세스에 상한을 건다. 메모리·CPU 상한을 모두 걸었으면 True (윈도우 등에서는 False)."""
    try:
        import resource
    except ImportError:  # 윈도우: 부모의 시간 상한만 쓴다
        return False
    applied = True
    for name, soft, hard in (
        ("RLIMIT_AS", memory, memory),
        ("RLIMIT_CPU", cpu, cpu + 1),
        ("RLIMIT_FSIZE", 0, 0),  # 파일을 쓰지 못한다
        ("RLIMIT_CORE", 0, 0),  # 비정상 종료해도 코어 파일(문서 내용)을 남기지 않는다
    ):
        limit = getattr(resource, name, None)
        try:
            if limit is None:
                raise ValueError(name)
            resource.setrlimit(limit, (soft, hard))
        except (ValueError, OSError):  # 운영체제가 받지 않는 상한 (macOS의 RLIMIT_AS 등)
            if name in ("RLIMIT_AS", "RLIMIT_CPU"):
                applied = False
    return applied


def serve(stdin, stdout) -> None:
    """자식 프로세스의 일. stdin: JSON 한 줄(설정) + PDF. stdout: READY + JSON 한 줄(결과) + 사본.

    준비(설정 읽기, pypdf 불러오기, 상한 걸기)에 실패하면 SETUP_EXIT로 끝낸다. PDF는 그 뒤에 읽는다.
    """
    try:
        settings = json.loads(stdin.readline())
        for entry in settings["path"]:  # 부모가 pypdf를 찾은 경로 (자식 자신의 경로가 먼저다)
            if entry not in sys.path:
                sys.path.append(entry)
        import pypdf  # noqa: F401  설치 문제를 PDF 문제와 구분하려고 미리 불러온다

        max_pages, max_plain = int(settings["max_pages"]), int(settings["max_plain_bytes"])
        limited = _set_limits(int(settings["memory"]), int(settings["cpu"]))
    except Exception:
        sys.exit(SETUP_EXIT)
    stdout.write(READY)
    stdout.flush()
    data = stdin.read()
    result = inspect(data, max_pages=max_pages, max_plain_bytes=max_plain)
    del data
    header = {"outcome": result.outcome, "pages": result.pages, "plain": result.plain is not None, "limits": limited}
    stdout.write(json.dumps(header).encode("ascii") + b"\n")
    if result.plain is not None:
        stdout.write(result.plain)
    stdout.flush()


def child_main() -> None:
    serve(sys.stdin.buffer, sys.stdout.buffer)


# ---------------------------------------------------------------------------
# 부모 쪽: 자식 프로세스를 띄워 결과를 받는다
# ---------------------------------------------------------------------------

# 자식 시작 코드. app을 불러오지 못해도 SETUP_EXIT로 끝나도록 감싼다 (윈도우에서도 한 줄 인자로 넘어가게 exec를 쓴다).
_BOOTSTRAP = (
    "import sys\n"
    "try:\n"
    "    sys.path.insert(0, sys.argv.pop(1))\n"
    "    from app.pdf_sandbox import child_main\n"
    "except Exception:\n"
    f"    sys.exit({SETUP_EXIT})\n"
    "child_main()\n"
)
_CHILD_CODE = f"exec({_BOOTSTRAP!r})"


def _python() -> str:
    return sys.executable


def child_env() -> dict[str, str]:
    """자식에 넘길 환경변수: CHILD_ENV_NAMES만 (윈도우는 이름의 대소문자를 가리지 않는다)."""
    return {key: value for key, value in os.environ.items() if key.upper() in CHILD_ENV_NAMES}


def child_path() -> list[str]:
    """부모의 sys.path (빈 칸은 현재 폴더로). 자식은 자기 경로 뒤에 붙여 쓴다."""
    return [os.path.abspath(entry) for entry in sys.path if isinstance(entry, str)]


def _mark_unavailable(reason: str) -> None:
    global _unavailable
    if _unavailable is None:
        logger.error(
            "pdf sandbox unavailable reason=%s; checking PDFs in-process without time/memory limits", reason
        )
    _unavailable = reason


class _ChildRun(NamedTuple):
    result: PdfCheck
    limits: bool


def _run_child(data: bytes, settings: dict, timeout: float) -> Optional[_ChildRun]:
    """자식 프로세스에서 검사한다. 자식이 준비 단계에서 실패하면 None (자식을 쓸 수 없다고 표시한다)."""
    try:
        proc = subprocess.Popen(
            [_python(), *CHILD_FLAGS, "-c", _CHILD_CODE, str(BACKEND_DIR)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=child_env(),
        )
    except (OSError, ValueError):
        _mark_unavailable("spawn_failed")
        return None
    try:
        try:
            proc.stdin.write(json.dumps(settings).encode("ascii") + b"\n")  # type: ignore[union-attr]
        except OSError:  # 자식이 시작하자마자 끝났다. 아래에서 READY가 없으므로 준비 실패로 본다.
            pass
        out, _ = proc.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        if not out.startswith(READY):  # 준비도 끝내지 못했다 (아주 느린 시작 등)
            _mark_unavailable("child_start_timeout")
            return None
        return _ChildRun(PdfCheck("pdf_timeout"), True)
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    if not out.startswith(READY):
        # 파이썬이 시작하지 못했거나 pypdf·app을 불러오지 못했다. PDF를 읽기 전이라 PDF 탓이 아니다.
        _mark_unavailable("child_setup_failed" if proc.returncode == SETUP_EXIT else f"child_exit_{proc.returncode}")
        return None
    newline = out.find(b"\n", len(READY))
    if proc.returncode != 0 or newline < 0:
        # PDF를 읽다가 죽었다: 메모리 상한(MemoryError를 못 잡고 죽음)·CPU 상한(SIGXCPU) 등
        return _ChildRun(PdfCheck("pdf_too_complex"), True)
    try:
        header = json.loads(out[len(READY) : newline])
        outcome, pages, has_plain = str(header["outcome"]), int(header["pages"]), bool(header["plain"])
        limits = bool(header.get("limits"))
    except (ValueError, KeyError, TypeError):
        return _ChildRun(PdfCheck("pdf_too_complex"), True)
    plain = out[newline + 1 :] if has_plain else None
    return _ChildRun(PdfCheck(outcome, pages, plain), limits)


def inspect_isolated(
    data: bytes,
    *,
    max_pages: int,
    max_plain_bytes: int,
    timeout: float | None = None,
    memory: int | None = None,
    cpu: int | None = None,
) -> PdfCheck:
    """inspect를 상한이 걸린 자식 프로세스에서 돌린다. 시간·메모리를 넘기거나 PDF를 읽다 죽으면 거절 사유를 돌려준다.

    자식 프로세스를 쓸 수 없으면(준비 실패) 같은 프로세스에서 inspect를 부른다.
    """
    if _unavailable is None:
        settings = {
            "path": child_path(),
            "max_pages": max_pages,
            "max_plain_bytes": max_plain_bytes,
            "memory": MEMORY_LIMIT_BYTES if memory is None else memory,
            "cpu": CPU_LIMIT_SECONDS if cpu is None else cpu,
        }
        run = _run_child(data, settings, WALL_TIMEOUT_SECONDS if timeout is None else timeout)
        if run is not None:
            return run.result
    return inspect(data, max_pages=max_pages, max_plain_bytes=max_plain_bytes)


def tiny_pdf() -> bytes:
    """1쪽짜리 빈 PDF (시작할 때 자가 점검용)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 10 10] >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def self_test() -> bool:
    """작은 PDF를 자식 프로세스에서 검사해 본다. 실패하면 자식을 쓰지 않는다고 표시하고 False."""
    if _unavailable is not None:
        return False
    started = time.perf_counter()
    settings = {"path": child_path(), "max_pages": 1, "max_plain_bytes": 1 << 20, "memory": MEMORY_LIMIT_BYTES,
                "cpu": CPU_LIMIT_SECONDS}
    run = _run_child(tiny_pdf(), settings, WALL_TIMEOUT_SECONDS)
    if run is None:
        return False
    if run.result != PdfCheck("ok", 1):
        _mark_unavailable(f"self_test_{run.result.outcome}")
        return False
    took_ms = (time.perf_counter() - started) * 1000
    logger.info("pdf sandbox ok limits=%s took=%.0fms", "on" if run.limits else "off (wall clock only)", took_ms)
    return True
