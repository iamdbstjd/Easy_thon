# 자취방 보증금 지킴이: 화면(React)과 서버(FastAPI)를 한 컨테이너로 배포한다.
# 서버가 /api와 빌드한 화면(/)을 같은 주소에서 내준다.
# API 키는 이미지에 넣지 않는다. 배포하는 곳의 환경변수로 넣는다:
#   OPENAI_API_KEY, DATA_GO_KR_SERVICE_KEY, JUSO_API_KEY

# 1) 화면 빌드
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) 서버
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVE_FRONTEND=1 \
    RATE_LIMIT=1 \
    FRONTEND_DIST=/app/frontend/dist
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/demo ./demo
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
# 배포하는 곳이 PORT를 정해 주면 그 값을 쓴다. 앞단 프록시가 넘긴 실제 접속 IP를 쓴다 (요청 수 제한).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
