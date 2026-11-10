"""규칙 엔진.

외부에서 쓰는 함수는 build_report 하나다.

- common.py: 날짜, 이름·주소 정리, 층 찾기, 금액·비율 표시
- engine.py: R1–R13 판정, 종합 판정, 리포트 조립
- content.py: 배너, 서류 요청 메시지, 추천 특약, 일정 체크리스트, 고지문
"""

from __future__ import annotations

from .engine import build_report

__all__ = ["build_report"]
