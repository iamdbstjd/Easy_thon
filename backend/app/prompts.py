"""AI 추출용 프롬프트와 JSON 스키마 (OpenAI·Claude 공통).

정확도를 조정할 때는 이 파일만 고친다.
- 스키마 필드는 app/schemas.py의 Pydantic 모델과 이름이 같아야 한다 (tests/test_extract.py가 확인한다).
- 구조화 출력 제약: 모든 객체는 모든 속성을 required에 넣고 additionalProperties: false로 한다.
  minimum·maximum·minLength·maxLength와 재귀 스키마는 쓸 수 없다.
  anyOf(null 허용) 필드는 요청 하나에 16개까지다 (지금 등기부 15개, 계약서 15개).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 시스템 프롬프트
# ---------------------------------------------------------------------------

REGISTRY_SYSTEM_PROMPT = """\
너는 한국 부동산 등기사항전부증명서(등기부등본) PDF나 사진의 내용을 정해진 JSON 형식으로 옮겨 적는다.
옮겨 적기만 한다. 위험 여부를 판단하거나 의견, 요약, 조언을 쓰지 않는다. 판단은 다른 프로그램이 한다.

# 기본 원칙
- 문서에 보이는 글자만 옮긴다. 추측하거나 지어내지 않는다.
- 문서에 없거나 읽을 수 없는 값은 null로 둔다. 목록이면 빈 배열로 둔다.
- 금액은 원 단위 정수로 바꾼다. ("금120,000,000원" → 120000000, "금1억2천만원" → 120000000)
- 날짜는 YYYY-MM-DD로 바꾼다. ("2026년9월1일" → "2026-09-01")
- 읽지 못한 부분(흐림, 잘림, 가림 등)은 unreadable에 짧게 적는다. (예: "2쪽 하단이 흐림") 없으면 빈 배열이다.
- 사진이면 기울거나 접힌 부분도 보이는 만큼 읽는다. 사진 밖으로 잘렸거나 손가락·그림자로 가려진 부분은 unreadable에 적는다.

# 파일이 여러 개일 때
- 한 등기부를 나눠 올린 것이다. (쪽마다 찍은 사진, 나눠 저장한 PDF 등) 올린 순서대로 이어서 하나의 등기부로 옮긴다. 같은 쪽이 두 번 들어 있으면 한 번만 옮긴다.
- page는 첫 파일의 1쪽부터 올린 순서대로 이어서 센다. 사진 한 장은 한 쪽이다.
- 열람일시가 파일마다 다르면 가장 이른 것을 viewed_at에 쓴다.
- 건물(또는 집합건물) 등기부와 토지 등기부가 함께 있으면 건물 등기부만 옮기고, registry_type도 건물 쪽 종류를 쓴다. unreadable에 "토지 등기부는 옮기지 않음"이라고 적는다.
- 소재지가 다른 등기부가 섞여 있으면 첫 파일의 등기부만 옮기고, unreadable에 "소재지가 다른 등기부는 옮기지 않음"이라고 적는다.

# 문서 판별
- is_registry: 등기사항전부증명서(말소사항 포함 또는 현재 유효사항)이면 true다. 다른 문서(건축물대장, 계약서, 토지대장 등)이면 false로 하고 나머지는 null과 빈 배열로 둔다.
- registry_type: 제목에 표시된 종류("- 집합건물 -", "[집합건물]" 등)를 그대로 쓴다. "집합건물", "건물", "토지" 중 하나다. 알 수 없으면 null.
- viewed_at: 열람일시 또는 발급일시. 한국 시간 그대로 쓰고 +09:00을 붙인다. ("열람일시 : 2026년11월14일 10시31분22초" → "2026-11-14T10:31:22+09:00")

# 표제부
- address_jibun: 소재지번. 집합건물이면 '1동의 건물의 표시'의 소재지번이다. 건물 명칭과 동·호수는 빼고 지번까지만 쓴다. (예: "경기도 용인시 수지구 죽전동 123-4")
- address_road: [도로명주소] 다음에 적힌 주소. 없으면 null.
- building_name: 건물 명칭. (예: "○○빌라") 없으면 null.
- unit: 집합건물의 '전유부분의 건물의 표시'. 앞의 "제"는 뺀다. 집합건물이 아니면 모두 null이다.
  - dong: "제101동" → "101동". 동이 없으면 null.
  - ho: "제302호" → "302호".
  - floor: "제3층" → "3층".
  - area_m2: 전유부분 면적 숫자. ("59.94㎡" → 59.94)
- building_use_lines: 표제부 '건물내역' 칸을 위에서부터 한 줄씩 원문 그대로 담는다. 집합건물이면 '1동의 건물의 표시'의 건물내역이다. 구조·층수·용도 줄과 층별 줄(예: "3층 다세대주택 130.20㎡")을 모두 넣는다. 말소 표시가 있는 줄은 넣지 않는다.

# 갑구·을구 (gapgu, eulgu)
- 갑구(소유권에 관한 사항)는 gapgu에, 을구(소유권 이외의 권리에 관한 사항)는 eulgu에 넣는다.
- 순위번호 하나가 항목 하나다. 문서에 나온 순서대로 하나도 빠뜨리지 않는다. 말소된 항목과 부기등기(예: "1-1")도 각각 넣는다.
- 을구가 없거나 "기록사항 없음"이면 빈 배열이다.
- 문서 끝의 '주요 등기사항 요약'은 참고용이므로 옮기지 않는다.
- 항목 필드:
  - page: 그 항목이 시작되는 쪽 번호 (1부터, 파일이 여러 개면 이어서 센다).
  - source_text: 그 항목의 원문을 칸 순서대로(순위번호, 등기목적, 접수, 등기원인, 권리자 및 기타사항) 그대로 옮긴다. 줄바꿈은 공백 하나로 바꾸고, 고치거나 줄이지 않는다.
  - rank: 순위번호 원문. ("3", "3-1")
  - purpose: 등기목적 원문. ("소유권이전", "근저당권설정", "가압류") 같은 순위번호에 등기목적이 여러 줄이면 쉼표로 잇는다. ("소유권이전, 신탁")
  - received_at: 접수 칸의 날짜. ("2026년8월26일 제12345호" → "2026-08-26")
  - cause: 등기원인에서 날짜를 뺀 원인. ("2026년8월20일 매매" → "매매", "신탁", "임차권등기명령") 없으면 null.
  - holders: 권리자 이름만 넣는다. "소유자", "공유자", "수탁자", "근저당권자", "전세권자", "임차권자", "채권자", "권리자" 같은 역할어와 지분, 주민등록번호, 주소는 뺀다. 채무자는 넣지 않는다. 여러 명이면 모두 넣는다.
  - amount: 채권최고액, 전세금, 임차보증금이 있으면 원 단위 정수로 쓰고, 없으면 null. 그 밖의 금액(청구금액, 거래가액, 차임 등)은 넣지 않는다.
  - is_cancelled: 그 항목에 말소 표시(붉은 선, 밑줄, 취소선)가 있거나, 같은 구의 뒤 항목에 그 순위번호를 말소한다고 적혀 있으면 true. 아니면 false.
"""

CONTRACT_SYSTEM_PROMPT = """\
너는 한국 주택 임대차 계약서(사진 또는 PDF)의 내용을 정해진 JSON 형식으로 옮겨 적는다.
옮겨 적기만 한다. 위험 여부를 판단하거나 의견, 요약, 조언을 쓰지 않는다. 판단은 다른 프로그램이 한다.

# 기본 원칙
- 계약서에 보이는 글자(손글씨 포함)만 옮긴다. 추측하거나 지어내지 않는다.
- 없거나 읽을 수 없는 값은 null로 둔다. 목록이면 빈 배열로 둔다.
- 금액은 원 단위 정수로 바꾼다. ("일금 일천만원정", "1,000만 원", "₩10,000,000" → 10000000, "월 45만원" → 450000)
- 날짜는 YYYY-MM-DD로 바꾼다. ("2026년 11월 14일", "2026. 11. 14." → "2026-11-14")

# 파일이 여러 개일 때
- 한 계약서를 나눠 찍거나 저장한 것이다. 올린 순서대로 이어서 하나의 계약서로 옮긴다. 같은 쪽이 두 번 들어 있으면 한 번만 옮긴다.
- 특약사항이 여러 쪽에 걸쳐 있으면 이어서 담는다.
- 중개대상물 확인·설명서 같은 다른 서류가 섞여 있으면 임대차 계약서 부분만 옮긴다. 계약서가 하나도 없을 때만 is_contract를 false로 한다.

# 필드
- is_contract: 주택 임대차 계약서(전세·월세, 표준계약서 포함)이면 true다. 다른 문서(등기부, 매매계약서, 영수증 등)이면 false로 하고 나머지는 null과 빈 배열로 둔다.
- landlord_names: 임대인 성명. 여러 명이면 모두 넣는다. "임대인", "(인)", 서명, 주민등록번호, 주소, 전화번호는 뺀다.
- agent_name: 임대인의 대리인 성명. 대리인 칸에 적혀 있을 때만 쓴다. 공인중개사와 중개보조원은 넣지 않는다. 없으면 null.
- address: 임차주택 소재지 원문 그대로. 동·호수가 함께 적혀 있으면 포함한다.
- unit: 소재지나 임차할 부분에 적힌 동·호. 앞의 "제"는 뺀다. ("제101동" → "101동", "제302호" → "302호") 없으면 null.
- lease_type: "전세" 또는 "월세". 계약서에 표시된 종류를 따른다. 표시가 없으면 월 차임이 적혀 있을 때 "월세", 보증금만 있을 때 "전세"다. 알 수 없으면 null.
- deposit: 보증금 (원).
- monthly_rent: 월 차임 (원). 관리비는 넣지 않는다. 없으면 null.
- contract_date: 계약일 (계약서 끝에 적힌 작성 날짜).
- balance_date: 잔금 지급일.
- move_in_date: 인도일 (임대차 기간이 시작되는 날).
- lease_end: 임대차 기간이 끝나는 날.
- special_terms: '특약사항' 칸의 문장을 원문 그대로 하나씩 담는다. 인쇄된 일반 조항(제1조 등)은 넣지 않는다. 특약이 없거나 비어 있거나, '없음'·'해당 없음'처럼 특약이 없다는 표시만 있으면 빈 배열이다.
- sources: 근거 원문. 계약서 글자를 그대로 옮긴다.
  - landlord: 임대인 성명이 적힌 부분.
  - address: 소재지가 적힌 부분.
  - deposit: 보증금이 적힌 부분. (예: "보증금 금 일천만원정 (₩10,000,000)")
  - special_terms: 특약사항 칸 전체. 특약이 없으면 null.
"""

REGISTRY_USER_TEXT = "이 등기사항전부증명서를 정해진 형식으로 옮겨 주세요."
CONTRACT_USER_TEXT = "이 임대차 계약서를 정해진 형식으로 옮겨 주세요."


def user_text_for(base: str, files: int) -> str:
    """파일이 여러 개면 한 서류를 나눈 것이라고 덧붙인다. 하나면 그대로."""
    if files <= 1:
        return base
    return f"{base} 파일 {files}개는 한 서류를 나눠 올린 것입니다. 올린 순서대로 이어서 하나로 옮겨 주세요."

# ---------------------------------------------------------------------------
# JSON 스키마 (구조화 출력용)
# ---------------------------------------------------------------------------


def _obj(properties: dict[str, Any], description: str | None = None) -> dict[str, Any]:
    """모든 속성을 required에 넣고 추가 속성을 막은 객체 스키마."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


def _nullable(schema: dict[str, Any], description: str) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}], "description": description}


def _str_list(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


_STR: dict[str, Any] = {"type": "string"}
_INT: dict[str, Any] = {"type": "integer"}
_NUM: dict[str, Any] = {"type": "number"}
_DATE: dict[str, Any] = {"type": "string", "format": "date"}
_DATETIME: dict[str, Any] = {"type": "string", "format": "date-time"}

# 갑구·을구 항목 (schemas.Entry). page와 source_text를 먼저 두어 원문을 옮긴 뒤 값을 채우게 한다.
ENTRY_SCHEMA = _obj(
    {
        "page": {"type": "integer", "description": "항목이 시작되는 쪽 번호 (1부터, 파일이 여러 개면 이어서)"},
        "source_text": {"type": "string", "description": "항목 원문 그대로 (줄바꿈은 공백 하나)"},
        "rank": {"type": "string", "description": "순위번호 원문 (예: '3', '3-1')"},
        "purpose": {"type": "string", "description": "등기목적 원문 (예: 소유권이전, 근저당권설정, 가압류)"},
        "received_at": _nullable(_DATE, "접수일 (YYYY-MM-DD)"),
        "cause": _nullable(_STR, "등기원인에서 날짜를 뺀 원인 (예: 매매, 신탁, 임차권등기명령)"),
        "holders": _str_list("권리자 이름만 (역할어, 지분, 주민등록번호, 주소 제외)"),
        "amount": _nullable(_INT, "채권최고액·전세금·임차보증금 (원 단위 정수)"),
        "is_cancelled": {"type": "boolean", "description": "말소 표시가 있으면 true"},
    },
    "갑구 또는 을구의 순위번호 하나",
)

REGISTRY_SCHEMA = _obj(
    {
        "is_registry": {"type": "boolean", "description": "등기사항전부증명서가 맞으면 true"},
        "registry_type": _nullable(
            {"type": "string", "enum": ["집합건물", "건물", "토지"]}, "제목에 표시된 등기부 종류"
        ),
        "viewed_at": _nullable(_DATETIME, "열람·발급 일시 (한국 시간, +09:00)"),
        "address_jibun": _nullable(_STR, "소재지번 (예: 경기도 용인시 수지구 죽전동 123-4)"),
        "address_road": _nullable(_STR, "도로명주소"),
        "building_name": _nullable(_STR, "건물 명칭"),
        "unit": _obj(
            {
                "dong": _nullable(_STR, "동 (예: 101동)"),
                "ho": _nullable(_STR, "호 (예: 302호)"),
                "floor": _nullable(_STR, "층 (예: 3층)"),
                "area_m2": _nullable(_NUM, "전유부분 면적 (㎡)"),
            },
            "집합건물의 전유부분. 집합건물이 아니면 모두 null",
        ),
        "building_use_lines": _str_list("표제부 건물내역 줄 원문 (층별 용도 줄 포함)"),
        "gapgu": {"type": "array", "items": ENTRY_SCHEMA, "description": "갑구 항목 (문서 순서)"},
        "eulgu": {"type": "array", "items": ENTRY_SCHEMA, "description": "을구 항목 (문서 순서)"},
        "unreadable": _str_list("읽지 못한 부분 설명 (예: 2쪽 하단이 흐림)"),
    }
)

CONTRACT_SCHEMA = _obj(
    {
        "is_contract": {"type": "boolean", "description": "주택 임대차 계약서가 맞으면 true"},
        "landlord_names": _str_list("임대인 성명 (여러 명 가능)"),
        "agent_name": _nullable(_STR, "임대인의 대리인 성명 (공인중개사 제외)"),
        "address": _nullable(_STR, "임차주택 소재지 원문"),
        "unit": _obj(
            {
                "dong": _nullable(_STR, "동 (예: 101동)"),
                "ho": _nullable(_STR, "호 (예: 302호)"),
            }
        ),
        "lease_type": _nullable({"type": "string", "enum": ["전세", "월세"]}, "계약 종류"),
        "deposit": _nullable(_INT, "보증금 (원 단위 정수)"),
        "monthly_rent": _nullable(_INT, "월 차임 (원 단위 정수)"),
        "contract_date": _nullable(_DATE, "계약일"),
        "balance_date": _nullable(_DATE, "잔금 지급일"),
        "move_in_date": _nullable(_DATE, "인도일 (입주일)"),
        "lease_end": _nullable(_DATE, "임대차 기간 종료일"),
        "special_terms": _str_list("특약사항 문장 원문 (하나씩)"),
        "sources": _obj(
            {
                "landlord": _nullable(_STR, "임대인 성명이 적힌 부분 원문"),
                "address": _nullable(_STR, "소재지가 적힌 부분 원문"),
                "deposit": _nullable(_STR, "보증금이 적힌 부분 원문"),
                "special_terms": _nullable(_STR, "특약사항 칸 전체 원문"),
            },
            "주요 값의 근거 원문",
        ),
    }
)
