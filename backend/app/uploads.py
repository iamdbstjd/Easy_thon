"""업로드 파일 검사.

- 파일은 디스크에 쓰지 않고 메모리의 bytes로만 다룬다.
- 형식은 확장자나 Content-Type이 아니라 파일 앞부분(매직 바이트)으로 판단한다.
  PDF는 PDF 뷰어처럼 앞 1024바이트 안의 "%PDF-"를 찾고(프론트엔드와 같은 기준), 그 위치부터 잘라 쓴다.
- 등기부와 계약서 모두 사진(JPEG·PNG·WEBP)이나 PDF를 받는다. 한 서류를 여러 파일로 나눠 올릴 수 있다
  (쪽마다 찍은 사진, 나눠 저장한 PDF). 파일 수와 쪽 수 합계에 상한을 둔다 (사진 한 장은 한 쪽).
- 어긋나면 모두 UNSUPPORTED_FILE이다. 로그에는 사유 코드만 남긴다.
- PDF 구조 검사(암호·쪽수)는 app/pdf_sandbox가 메모리·시간 상한이 걸린 별도 프로세스에서 한다.
  일부러 만든 PDF가 서버를 멈추지 못하게 하기 위해서다. 상한을 넘으면 UNSUPPORTED_FILE이다.
- 소유자 암호(권한 제한)만 걸린 PDF는 열람 암호가 비어 있으므로 메모리에서 풀어
  암호 없는 사본을 만들고, 그 사본으로 쪽수를 세고 AI에 보낸다.
  열람 암호가 필요한 PDF만 거절한다. AES 복호화에는 cryptography 패키지가 필요하다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Sequence

from app import pdf_sandbox
from app.errors import ApiError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 파일 하나당 10MB
MAX_FILES = 10  # 서류(등기부·계약서)마다 파일 수
MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 한 요청에 올리는 파일 전체 (등기부 + 계약서)
MAX_PDF_PAGES = 30  # 서류마다 쪽 수 합계. 넘으면 '현재 유효사항'으로 다시 열람하라고 안내한다
# 업로드 요청 전체 상한: 파일 전체 + multipart 여유분. 넘으면 본문을 읽지 않고 거절한다.
MAX_REQUEST_BYTES = MAX_TOTAL_BYTES + 1024 * 1024
# 소유자 암호를 풀어 다시 쓴 사본의 상한 (다시 쓰면 조금 커질 수 있다)
MAX_DECRYPTED_BYTES = MAX_UPLOAD_BYTES + MAX_UPLOAD_BYTES // 2

PDF_MEDIA_TYPE = "application/pdf"
PDF_HEADER = b"%PDF-"
PDF_HEADER_WINDOW = 1024  # 헤더 앞에 다른 바이트가 붙어 있어도 이 안에 헤더가 있으면 PDF로 본다

logger = logging.getLogger("app.uploads")


@dataclass(frozen=True)
class DocInput:
    """검사를 통과한 파일 하나. kind는 파일 종류다 (PDF는 document, 사진은 image)."""

    kind: Literal["document", "image"]
    media_type: str  # application/pdf, image/jpeg, image/png, image/webp
    data: bytes
    pages: int = 1  # PDF 쪽 수 (사진은 1)


def _reject(doc: str, reason: str) -> ApiError:
    return ApiError("UNSUPPORTED_FILE", reason=f"{doc}:{reason}")


def pdf_header_offset(data: bytes) -> int | None:
    """앞 1024바이트 안에 "%PDF-"가 통째로 있으면 그 위치, 없으면 None."""
    offset = data.find(PDF_HEADER, 0, PDF_HEADER_WINDOW)
    return None if offset < 0 else offset


def image_media_type(data: bytes) -> str | None:
    """JPEG·PNG·WEBP면 media type을, 아니면 None을 돌려준다."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _check_size(doc: str, data: bytes) -> None:
    if not data:
        raise _reject(doc, "empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise _reject(doc, "too_large")


# PDF 검사 함수. 테스트에서 같은 프로세스용(pdf_sandbox.inspect)으로 바꿔 끼울 수 있다.
inspect_pdf = pdf_sandbox.inspect_isolated


def _check_pdf(doc: str, data: bytes) -> DocInput:
    """PDF 구조를 읽어 암호와 쪽수를 확인한다. 돌려주는 data는 암호 없는 PDF다."""
    result = inspect_pdf(data, max_pages=MAX_PDF_PAGES, max_plain_bytes=MAX_DECRYPTED_BYTES)
    if result.outcome != "ok":
        raise _reject(doc, result.outcome)
    if result.pages == 0:
        raise _reject(doc, "no_pages")
    if result.pages > MAX_PDF_PAGES:
        raise _reject(doc, "too_many_pages")
    if result.plain is not None:
        logger.info("pdf owner password removed in memory doc=%s", doc)
        data = result.plain
    return DocInput(kind="document", media_type=PDF_MEDIA_TYPE, data=data, pages=result.pages)


def _from_header(data: bytes, offset: int) -> bytes:
    # 헤더 앞 바이트는 버린다. 헤더가 맨 앞이면 10MB를 다시 복사하지 않는다.
    return data if offset == 0 else data[offset:]


def _validate_file(doc: str, data: bytes) -> DocInput:
    """파일 하나: JPEG·PNG·WEBP 사진 또는 PDF, 10MB 이하. PDF는 30쪽 이하, 열람 암호 없음."""
    _check_size(doc, data)
    media_type = image_media_type(data)  # 사진의 매직 바이트는 0번 위치라 먼저 본다
    if media_type is not None:
        return DocInput(kind="image", media_type=media_type, data=data)
    offset = pdf_header_offset(data)
    if offset is None:
        raise _reject(doc, "unsupported_type")
    return _check_pdf(doc, _from_header(data, offset))


def validate_registry(data: bytes) -> DocInput:
    """등기부 파일 하나: 사진 또는 PDF (소유자 암호만 있으면 풀어서 쓴다)."""
    return _validate_file("registry", data)


def validate_contract(data: bytes) -> DocInput:
    """계약서 파일 하나: 사진 또는 PDF (등기부와 같은 검사)."""
    return _validate_file("contract", data)


def validate_files(doc: str, files: Sequence[bytes]) -> list[DocInput]:
    """한 서류를 이루는 파일들 (올린 순서 그대로). 1~MAX_FILES개, 쪽 수 합계 MAX_PDF_PAGES 이하."""
    if not files:
        raise _reject(doc, "empty")
    if len(files) > MAX_FILES:
        raise _reject(doc, "too_many_files")
    docs: list[DocInput] = []
    pages = 0
    for data in files:
        item = _validate_file(doc, data)
        pages += item.pages
        if pages > MAX_PDF_PAGES:
            raise _reject(doc, "too_many_pages")
        docs.append(item)
    return docs


def check_total_size(files: Sequence[bytes]) -> None:
    """한 요청에 올린 파일 전체 크기 (등기부 + 계약서). 어느 서류 탓인지 정하지 않는다."""
    if sum(len(data) for data in files) > MAX_TOTAL_BYTES:
        raise ApiError("UNSUPPORTED_FILE", reason="total_too_large")
