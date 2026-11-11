"""모든 테스트 공통: 실제 AI를 부르지 않게 AI 키 환경변수를 지운다.

서버 모듈을 불러오면 backend/.env의 키가 환경변수로 들어온다. 키가 필요한 테스트는 가짜 값을 직접 넣는다.
"""

import pytest

AI_ENV_NAMES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "AI_PROVIDER", "OPENAI_MODEL", "OPENAI_REASONING_EFFORT")


@pytest.fixture(autouse=True)
def _no_real_ai_keys(monkeypatch):
    for name in AI_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
