"""규칙 엔진.

외부에서 쓰는 함수는 build_report 하나다.

- common.py: 날짜, 이름·주소 정리, 층 찾기, 금액·비율 표시
- engine.py: R1–R13 판정과 판정에 쓰는 값
- crosscheck.py: 계약서·등기부 대조표, 계약서 수정 요청서
- content.py: 배너, 서류 요청 메시지, 추천 특약, 일정 체크리스트, 요청서 문안, 고지문
- report.py: 리포트 조립
"""

from __future__ import annotations

from .report import build_report

__all__ = ["build_report"]
