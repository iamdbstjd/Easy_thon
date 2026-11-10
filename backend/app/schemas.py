"""데이터 형식 (Pydantic 모델).

백엔드, 프론트엔드, 데모 데이터가 주고받는 필드 이름과 타입은 이 파일이 기준이다.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Level = Literal["red", "yellow", "green", "unknown"]
OverallLevel = Literal["red", "yellow", "green"]
Mode = Literal["live", "demo"]


class Model(BaseModel):
    # 정의되지 않은 필드가 들어오면 거절한다. 오타나 형식 불일치를 빨리 드러내기 위해서다.
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 8.1 등기부 추출
# ---------------------------------------------------------------------------


class Entry(Model):
    """갑구·을구의 한 항목."""

    rank: str = Field(description="순위번호 (예: '3', '3-1')")
    purpose: str = Field(description="등기목적 원문 (예: 소유권이전, 근저당권설정, 가압류)")
    received_at: Optional[dt.date] = Field(default=None, description="접수일")
    cause: Optional[str] = Field(default=None, description="등기원인 (예: 매매, 신탁, 임차권등기명령)")
    holders: list[str] = Field(default_factory=list, description="권리자 이름 (역할어 제외)")
    amount: Optional[int] = Field(default=None, description="채권최고액·전세금·임차보증금 (원)")
    is_cancelled: bool = Field(default=False, description="말소 표시 여부")
    page: Optional[int] = Field(default=None, description="페이지 번호")
    source_text: str = Field(default="", description="원문 그대로")


class RegistryUnit(Model):
    """전유부분 (집합건물의 내 호실)."""

    dong: Optional[str] = None
    ho: Optional[str] = None
    floor: Optional[str] = None
    area_m2: Optional[float] = None


class RegistryExtract(Model):
    is_registry: bool = True
    registry_type: Optional[Literal["집합건물", "건물", "토지"]] = None
    viewed_at: Optional[dt.datetime] = None
    address_jibun: Optional[str] = None
    address_road: Optional[str] = None
    building_name: Optional[str] = None
    unit: RegistryUnit = Field(default_factory=RegistryUnit)
    building_use_lines: list[str] = Field(default_factory=list)
    gapgu: list[Entry] = Field(default_factory=list)
    eulgu: list[Entry] = Field(default_factory=list)
    unreadable: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 8.2 계약서 추출
# ---------------------------------------------------------------------------


class ContractUnit(Model):
    dong: Optional[str] = None
    ho: Optional[str] = None


class ContractSources(Model):
    """주요 값의 근거 원문."""

    landlord: Optional[str] = None
    address: Optional[str] = None
    deposit: Optional[str] = None
    special_terms: Optional[str] = None


class ContractExtract(Model):
    is_contract: bool = True
    landlord_names: list[str] = Field(default_factory=list)
    agent_name: Optional[str] = None
    address: Optional[str] = None
    unit: ContractUnit = Field(default_factory=ContractUnit)
    lease_type: Optional[Literal["전세", "월세"]] = None
    deposit: Optional[int] = None
    monthly_rent: Optional[int] = None
    contract_date: Optional[dt.date] = None
    balance_date: Optional[dt.date] = None
    move_in_date: Optional[dt.date] = None
    lease_end: Optional[dt.date] = None
    special_terms: list[str] = Field(default_factory=list)
    sources: ContractSources = Field(default_factory=ContractSources)


# ---------------------------------------------------------------------------
# 8.3 건축물대장 (P1) / 8.4 시세 (P1) / 8.5 직접 입력
# ---------------------------------------------------------------------------


class BuildingRegister(Model):
    main_use: Optional[str] = None
    unit_use: Optional[str] = None
    is_violating: Optional[bool] = None
    source: Literal["api", "pdf"] = "pdf"
    source_text: Optional[str] = None


class MarketPrice(Model):
    price: Optional[int] = None
    method: Literal["same_building", "same_dong", "manual"] = "manual"
    deals: int = 0
    period: Optional[str] = None


class ManualInput(Model):
    deposit: Optional[int] = None
    monthly_rent: Optional[int] = None
    contract_date: Optional[dt.date] = None
    landlord_name: Optional[str] = None
    prior_deposits: Optional[int] = None
    market_price: Optional[int] = None


# ---------------------------------------------------------------------------
# 9장 /api/check 입력
# ---------------------------------------------------------------------------


class CheckRequest(Model):
    registry: RegistryExtract
    contract: Optional[ContractExtract] = None
    manual: ManualInput = Field(default_factory=ManualInput)
    building: Optional[BuildingRegister] = None
    market: Optional[MarketPrice] = None
    today: Optional[dt.date] = None  # 없으면 서버가 현재 한국 날짜로 채운다
    mode: Mode = "live"


# ---------------------------------------------------------------------------
# 8.6 리포트
# ---------------------------------------------------------------------------


class Evidence(Model):
    doc: Literal["registry", "contract", "building", "market", "manual"]
    page: Optional[int] = None
    text: str


class RuleResult(Model):
    id: str  # "R1" ~ "R13"
    name: str  # 규칙 이름 (RULE_NAMES)
    level: Level
    title: str = ""
    summary: str = ""
    action: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    unknown_reason: Optional[str] = None


class Overall(Model):
    level: OverallLevel
    title: str
    message: str
    unknown_note: Optional[str] = None


class Counts(Model):
    red: int = 0
    yellow: int = 0
    unknown: int = 0
    green: int = 0


class ChecklistItem(Model):
    when: str  # "계약 전" · "계약일" · "잔금일" · "입주일" · "입주 후"
    date: Optional[dt.date] = None
    title: str


class ComparisonRow(Model):
    """계약서·등기부 대조표의 한 행. 등급은 rule_id 규칙의 등급과 같다."""

    item: str  # "임대인" · "소재지·호수" · "보증금" · "계약일" · "특약"
    rule_id: str  # "R1" · "R11" · "R5" · "R8" · "R12"
    contract: Optional[str] = None  # 계약서(또는 직접 입력) 쪽 값, 화면 표시용
    registry: Optional[str] = None  # 등기부·시세 쪽 값, 화면 표시용
    level: Level
    note: str = ""  # 짧은 결과 ("일치", "불일치", "90%", "80일 전 소유자 변경" …)


class AmendmentFix(Model):
    """계약서에서 고칠 곳 한 줄."""

    item: str  # "임대인" · "소재지"
    current: Optional[str] = None  # 계약서의 지금 값
    proposed: str  # 고칠 값
    reason: str


class Amendment(Model):
    """계약서 수정 요청서 (계약서가 없으면 계약 전 요청서)."""

    title: str  # "계약서 수정 요청서" · "계약 전 요청서"
    fixes: list[AmendmentFix] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)  # 넣어 주실 특약
    documents: list[str] = Field(default_factory=list)  # 계약 전에 받을 서류
    text: str  # 복사·인쇄용 전체 문안


class Report(Model):
    mode: Mode
    generated_at: dt.datetime
    today: dt.date
    overall: Overall
    counts: Counts
    results: list[RuleResult]
    comparison: list[ComparisonRow] = Field(default_factory=list)  # 계약서·등기부 대조표
    amendment: Optional[Amendment] = None  # 계약서 수정 요청서
    request_message: Optional[str] = None
    special_terms: list[str] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    disclaimer: str


# ---------------------------------------------------------------------------
# 9장 기타 응답과 오류
# ---------------------------------------------------------------------------


class ExtractResponse(Model):
    registry: RegistryExtract
    contract: Optional[ContractExtract] = None


class HealthResponse(Model):
    ai_ready: bool
    public_api_ready: bool


class IcsRequest(Model):
    """/api/checklist.ics 입력."""

    checklist: list[ChecklistItem]
    address: Optional[str] = None


ErrorCode = Literal[
    "UNSUPPORTED_FILE",
    "NOT_REGISTRY",
    "LAND_REGISTRY",
    "NOT_CONTRACT",
    "AI_FAILED",
    "NOT_FOUND",
    "INTERNAL_ERROR",
]


class ErrorDetail(Model):
    code: ErrorCode
    message: str


class ErrorResponse(Model):
    error: ErrorDetail


# 규칙 ID와 이름
RULE_NAMES: dict[str, str] = {
    "R1": "임대인·소유자 불일치",
    "R2": "신탁등기",
    "R3": "압류·경매 등 제한",
    "R4": "임차권등기",
    "R5": "시세 대비 보증금 비율",
    "R6": "먼저 잡힌 담보·전세권",
    "R7": "다가구·단독",
    "R8": "최근 소유권 변동",
    "R9": "위반건축물",
    "R10": "주거용이 아닌 용도",
    "R11": "주소·호수 불일치",
    "R12": "보호 특약 없음",
    "R13": "오래된 등기부",
}
