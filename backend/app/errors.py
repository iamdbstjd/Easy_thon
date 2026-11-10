"""API 오류 형식.

모든 오류 응답은 {"error": {"code": "...", "message": "사용자에게 보여줄 문장"}} 이다.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")

# 사용자에게 보여 줄 오류 문구
ERROR_MESSAGES: dict[str, str] = {
    "UNSUPPORTED_FILE": "등기부는 PDF, 계약서는 사진이나 PDF로 10MB 이하만 올릴 수 있어요.",
    "NOT_REGISTRY": "등기부등본이 아닌 것 같아요. 인터넷등기소에서 받은 PDF를 올려주세요.",
    "LAND_REGISTRY": "토지 등기부예요. 건물(또는 집합건물) 등기부를 올려주세요.",
    "NOT_CONTRACT": "임대차 계약서가 아닌 것 같아요.",
    "AI_FAILED": "문서를 읽지 못했어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.",
    # 개발용 코드 (사용자 화면에는 거의 나오지 않는다)
    "NOT_FOUND": "예시 데이터를 찾지 못했어요. 예시는 A, B, C예요.",
    "INTERNAL_ERROR": "일시적인 오류가 생겼어요. 잠시 후 다시 시도하거나 예시 결과를 확인해 주세요.",
}

ERROR_STATUS: dict[str, int] = {
    "UNSUPPORTED_FILE": 400,
    "NOT_REGISTRY": 422,
    "LAND_REGISTRY": 422,
    "NOT_CONTRACT": 422,
    "AI_FAILED": 502,  # API 키가 없으면 503 (ApiError.ai_unavailable)
    "NOT_FOUND": 404,
    "INTERNAL_ERROR": 500,
}


class ApiError(Exception):
    """사용자에게 정해진 문구로 보여줄 오류.

    reason은 로그용 짧은 영문 사유다 (예: "too_many_pages"). 개인정보나 문서 내용을 넣지 않는다.
    """

    def __init__(self, code: str, *, status: int | None = None, reason: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.status = status if status is not None else ERROR_STATUS[code]
        self.message = ERROR_MESSAGES[code]
        self.reason = reason

    @classmethod
    def ai_unavailable(cls) -> "ApiError":
        """API 키가 설정되지 않았을 때 (AI를 부르지 않는다)."""
        return cls("AI_FAILED", status=503, reason="no_api_key")


def error_body(code: str) -> dict:
    return {"error": {"code": code, "message": ERROR_MESSAGES[code]}}


def error_response(code: str, status: int | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status if status is not None else ERROR_STATUS[code],
        content=error_body(code),
        headers=headers,
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    logger.info("error code=%s status=%d reason=%s", exc.code, exc.status, exc.reason or "-")
    return error_response(exc.code, exc.status)
