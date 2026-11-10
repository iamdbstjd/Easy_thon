# 자취방 보증금 지킴이 — 프론트엔드

React 19 + TypeScript + Vite. API 타입은 `../backend/app/schemas.py`가 기준이다. 프로젝트 소개는 [../README.md](../README.md)에 있다.

## 실행

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build → dist/
npm run lint       # oxlint
```

- 개발 서버는 `/api`를 `http://127.0.0.1:8000`(FastAPI)으로 넘긴다. 다른 주소의 백엔드를 쓰려면
  `API_TARGET=http://127.0.0.1:8011 npm run dev`.
- 글꼴은 npm 패키지에서 번들되어 인터넷 없이도 같은 모양으로 보인다: 본문 Pretendard, 리포트 제목·종합 판정 Noto Serif KR 700 (`@fontsource/noto-serif-kr`).

## 가짜 데이터 (`?mock=1`)

주소에 `?mock=1`을 붙였을 때만 백엔드 대신 `src/mocks/`의 데이터를 쓴다. 기본값은 항상 실제 백엔드다.
화면 오른쪽 위에 "모의 데이터" 표시가 붙는다.

- 예시 A·B·C: `backend/demo/`와 같은 시나리오의 입력과 리포트 (가짜 API는 규칙을 계산하지 않으므로, S4에서 값을 고쳐도 리포트는 그대로다.
  예외: 예시 A에서 임대인 이름을 지우고 검사하면 "확인 미완료" 리포트를 돌려준다)
- 서류 올리기: 4초 뒤 시나리오 C의 추출 결과를 돌려준다
- 개발용 추가 옵션: `mockError=AI_FAILED`(또는 `NOT_REGISTRY` 등), `mockExtractMs=95000`(90초 시간 초과 확인), `mockCheckMs=3000`

## 구조

```
src/
  App.tsx              화면 흐름 S1 → S2 → S3 → S4 → S5 (라우터 없음)
  api/types.ts         schemas.py를 옮긴 타입
  api/client.ts        health · extract · check · demo · checklistIcs
  api/normalize.ts     서버 응답을 타입에 맞추고 모르는 필드를 버린다 (백엔드가 extra 필드를 거절하므로)
  api/errors.ts        {"error": {code, message}} → 화면 문구
  screens/             StartScreen(S1) UploadScreen(S2) ProgressScreen·ErrorScreen(S3) ReviewScreen(S4) ReportScreen(S5)
  components/          등급 글자(Grade), 입력 줄(금액·날짜·주소), 파일 고르기, 접기·원문 상자, 복사 링크, 예시 결과 링크, 머리글
  state/               S2 입력값, S4 입력 칸 ↔ CheckRequest 변환
  lib/                 금액·날짜 형식, 계약서 사진 줄이기, 클립보드
  content/             등급 이름, "등기부만으로는 알 수 없는 것" 표, 고지·링크 문구
  mocks/               ?mock=1 전용 데이터 (동적 import라 평소에는 내려받지 않는다)
  styles.css           전역 스타일 ("검토서" 디자인: 선으로 짠 문서, 색은 등급 글자에만, 화면마다 주 버튼 하나)
```
