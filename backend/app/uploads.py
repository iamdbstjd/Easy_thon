"""업로드 파일 검사.

- 파일은 디스크에 쓰지 않고 메모리의 bytes로만 다룬다.
- 형식은 확장자나 Content-Type이 아니라 파일 앞부분(매직 바이트)으로 판단한다.
  PDF는 PDF 뷰어처럼 앞 1024바이트 안의 "%PDF-"를 찾고(프론트엔드와 같은 기준), 그 위치부터 잘라 쓴다.
- 어긋나면 모두 UNSUPPORTED_FILE이다. 로그에는 사유 코드만 남긴다.
- 소유자 암호(권한 제한)만 걸린 PDF는 열람 암호가 비어 있으므로 메모리에서 풀어
  암호 없는 사본을 만들고, 그 사본으로 쪽수를 세고 Claude에 보낸다.
  열람 암호가 필요한 PDF만 거절한다. AES 복호화에는 cryptography 패키지가 필요하다.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Literal

from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.errors import DependencyError

from app.errors import ApiError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 파일 하나당 10MB
MAX_PDF_PAGES = 30  # 넘으면 '현재 유효사항'으로 다시 열람하라고 안내한다
# /api/extract 요청 전체 상한: 파일 2개 + multipart 여유분. 넘으면 본문을 읽지 않고 거절한다.
MAX_REQUEST_BYTES = 2 * MAX_UPLOAD_BYTES + 1024 * 1024
# /api/extract/contract 요청 상한: 파일 1개 + multipart 여유분
MAX_SINGLE_FILE_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024

PDF_MEDIA_TYPE = "application/pdf"
PDF_HEADER = b"%PDF-"
PDF_HEADER_WINDOW = 1024  # 헤더 앞에 다른 바이트가 붙어 있어도 이 안에 헤더가 있으면 PDF로 본다

logger = logging.getLogger("app.uploads")


@dataclass(frozen=True)
class DocInput:
    """검사를 통과한 문서. kind는 Claude에 보낼 블록 종류다."""

    kind: Literal["document", "image"]
    media_type: str  # application/pdf, image/jpeg, image/png, image/webp
    data: bytes


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


def _open_pdf(doc: str, data: bytes) -> tuple[PdfReader, bytes]:
    """PDF를 연다. 암호가 걸려 있으면 빈 열람 암호로 풀어 암호 없는 사본(bytes)을 메모리에 만든다."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if not reader.is_encrypted:
            return reader, data
        if reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            raise _reject(doc, "encrypted_pdf")  # 열람 암호가 있어야 열린다
        buf = io.BytesIO()
        PdfWriter(clone_from=reader).write(buf)  # 암호 설정 없이 다시 쓴다
        plain = buf.getvalue()
        reader = PdfReader(io.BytesIO(plain))
    except ApiError:
        raise
    except DependencyError:  # AES 암호인데 cryptography가 설치되지 않았다
        raise _reject(doc, "encrypted_pdf_needs_cryptography") from None
    except Exception:  # 깨진 PDF (pypdf 예외 종류가 다양하다)
        raise _reject(doc, "broken_pdf") from None
    if reader.is_encrypted:
        raise _reject(doc, "encrypted_pdf")
    logger.info("pdf owner password removed in memory doc=%s", doc)
    return reader, plain


def _check_pdf(doc: str, data: bytes) -> DocInput:
    """PDF 구조를 읽어 암호와 쪽수를 확인한다. 돌려주는 data는 암호 없는 PDF다."""
    reader, data = _open_pdf(doc, data)
    try:
        pages = len(reader.pages)
    except Exception:
        raise _reject(doc, "broken_pdf") from None
    if pages == 0:
        raise _reject(doc, "no_pages")
    if pages > MAX_PDF_PAGES:
        raise _reject(doc, "too_many_pages")
    return DocInput(kind="document", media_type=PDF_MEDIA_TYPE, data=data)


def validate_registry(data: bytes) -> DocInput:
    """등기부: PDF, 10MB 이하, 30쪽 이하, 열람 암호 없음 (소유자 암호만 있으면 풀어서 쓴다)."""
    _check_size("registry", data)
    offset = pdf_header_offset(data)
    if offset is None:
        raise _reject("registry", "not_pdf")
    return _check_pdf("registry", data[offset:])  # 헤더 앞 바이트는 버린다


def validate_contract(data: bytes) -> DocInput:
    """계약서: JPEG·PNG·WEBP 사진 또는 PDF(등기부와 같은 검사), 10MB 이하."""
    _check_size("contract", data)
    media_type = image_media_type(data)  # 사진의 매직 바이트는 0번 위치라 먼저 본다
    if media_type is not None:
        return DocInput(kind="image", media_type=media_type, data=data)
    offset = pdf_header_offset(data)
    if offset is None:
        raise _reject("contract", "unsupported_type")
    return _check_pdf("contract", data[offset:])
