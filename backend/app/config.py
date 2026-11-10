"""경로, .env 읽기, 로그 설정.

로그 원칙 (PRD 10장): 이름·주소·문서 원문·파일 이름을 남기지 않는다.
상태, 걸린 시간, 요청 ID, 짧은 사유 코드만 남긴다.
"""

from __future__ import annotations

import contextvars
import logging
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

# 요청마다 붙는 ID. 미들웨어가 넣고 로그 필터가 읽는다.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def load_env_file(path: Path = ENV_FILE) -> list[str]:
    """KEY=VALUE 형식의 .env를 읽어 환경변수로 넣고, 넣은 키 이름 목록을 돌려준다.

    - 빈 줄과 #으로 시작하는 줄은 건너뛴다. 'export KEY=VALUE'와 따옴표로 감싼 값도 읽는다.
    - 이미 설정된 환경변수는 덮어쓰지 않는다. 값이 비어 있으면 넣지 않는다.
    """
    if not path.is_file():
        return []
    loaded: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:  # 따옴표 없는 값 뒤의 주석
            value = value.split(" #", 1)[0].rstrip()
        if not value or key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> logging.Logger:
    """'app' 로거에 요청 ID가 붙는 핸들러를 한 번만 단다."""
    logger = logging.getLogger("app")
    if not any(getattr(h, "_app_handler", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler._app_handler = True  # type: ignore[attr-defined]
        handler.addFilter(_RequestIdFilter())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
