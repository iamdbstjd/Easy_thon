"""API 오류 형식.

오류 응답은 {"error": {"code": "...", "message": "사용자에게 보여줄 문장"}} 이다.
파일·문서 오류(UNSUPPORTED_FILE, NOT_REGISTRY, LAND_REGISTRY, NOT_CONTRACT)는 어느 파일이 문제인지 알 때
"document": "registry" | "contract"를 함께 보낸다 (사유 코드의 "registry:"·"contract:" 앞부분에서 정한다).

예외: JSON 입력 검사 실패(/api/check 등)는 422와 {"detail": [{"loc", "msg", "type"}, …]}이다 (main.py).
화면은 422 상태 코드만 본다. 업로드 경로의 입력 검사 실패는 위 형식의 UNSUPPORTED_FILE이다.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")

# 사용자에게 보여 줄 오류 문구
ERROR_MESSAGES: dict[str, str] = {
    "UNSUPPORTED_FILE": "PDF나 사진(JPG·PNG)만, 파일 하나 10MB·서류마다 30쪽 이하로 올릴 수 있어요.",
    "NOT_REGISTRY": "등기부등본이 아닌 것 같아요. 인터넷등기소에서 받은 PDF를 올려주세요.",
    "LAND_REGISTRY": "토지 등기부예요. 건물(또는 집합건물) 등기부를 올려주세요.",
    "NOT_CONTRACT": "임대차 계약서가 아닌 것 같아요.",
    "AI_FAILED": "문서를 읽지 못했어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.",
    "BUSY": "지금 서류를 읽는 사람이 많아요. 잠시 후 다시 시도해 주세요.",
    # 개발용 코드 (사용자 화면에는 거의 나오지 않는다)
    "NOT_FOUND": "예시 데이터를 찾지 못했어요. 예시는 A, B, C예요.",
    "INVALID_REQUEST": "요청을 처리하지 못했어요. 페이지를 새로 고친 뒤 다시 시도해 주세요.",
    "INTERNAL_ERROR": "일시적인 오류가 생겼어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.",
}

ERROR_STATUS: dict[str, int] = {
    "UNSUPPORTED_FILE": 400,
    "NOT_REGISTRY": 422,
    "LAND_REGISTRY": 422,
    "NOT_CONTRACT": 422,
    "AI_FAILED": 502,  # API 키가 없으면 503
    "BUSY": 503,  # 서류 읽기 자리를 마감 시간 안에 잡지 못했다
    "NOT_FOUND": 404,
    "INVALID_REQUEST": 400,  # 없는 경로(404), 허용하지 않는 메서드(405), 너무 큰 본문(413) 등은 그 상태 코드를 쓴다
    "INTERNAL_ERROR": 500,
}

# 어느 파일이 문제인지 알려 주는 오류 코드
DOCUMENT_ERROR_CODES = frozenset({"UNSUPPORTED_FILE", "NOT_REGISTRY", "LAND_REGISTRY", "NOT_CONTRACT"})
DOCUMENTS = ("registry", "contract")


def document_from_reason(code: str, reason: str) -> Optional[str]:
    """사유 코드 앞부분("registry:…"·"contract:…")으로 문제 파일을 정한다. 파일 오류가 아니거나 모르면 None."""
    if code not in DOCUMENT_ERROR_CODES:
        return None
    head = reason.split(":", 1)[0]
    return head if head in DOCUMENTS else None


class ApiError(Exception):
    """사용자에게 정해진 문구로 보여줄 오류.

    reason은 로그용 짧은 영문 사유다 (예: "registry:too_many_pages"). 개인정보나 문서 내용을 넣지 않는다.
    """

    def __init__(self, code: str, *, status: int | None = None, reason: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.status = status if status is not None else ERROR_STATUS[code]
        self.message = ERROR_MESSAGES[code]
        self.reason = reason

    @property
    def document(self) -> Optional[str]:
        return document_from_reason(self.code, self.reason)

    @classmethod
    def ai_unavailable(cls) -> "ApiError":
        """API 키가 설정되지 않았을 때 (AI를 부르지 않는다)."""
        return cls("AI_FAILED", status=503, reason="no_api_key")

    @classmethod
    def busy(cls, slot: str) -> "ApiError":
        """서류 읽기 요청이 몰려 자리(slot: "upload"·"ai")를 마감 시간 안에 잡지 못했을 때."""
        return cls("BUSY", reason=f"busy_{slot}")


def error_body(code: str, document: Optional[str] = None) -> dict:
    detail = {"code": code, "message": ERROR_MESSAGES[code]}
    if document is not None:
        detail["document"] = document
    return {"error": detail}


def error_response(
    code: str,
    status: int | None = None,
    headers: dict[str, str] | None = None,
    *,
    document: Optional[str] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status if status is not None else ERROR_STATUS[code],
        content=error_body(code, document),
        headers=headers,
    )


def api_error_response(exc: ApiError, headers: dict[str, str] | None = None) -> JSONResponse:
    """ApiError를 응답으로 바꾸고 사유 코드만 로그에 남긴다."""
    logger.info("error code=%s status=%d reason=%s", exc.code, exc.status, exc.reason or "-")
    return error_response(exc.code, exc.status, headers, document=exc.document)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return api_error_response(exc)
