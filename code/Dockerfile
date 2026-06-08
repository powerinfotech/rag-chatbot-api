# 배포(서버)용 이미지 — 질의 전용: FastAPI + 하이브리드 검색 + Ollama 호출.
# 문서 적재(.doc 파싱은 macOS 'textutil' 의존)는 로컬(Mac)에서만 수행하므로
# 서버 이미지에선 필요 없다. 데이터는 적재가 아니라 Neo4j 볼륨 복원으로 채운다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# 1) 의존성 먼저 설치 → 소스만 바뀔 때 이 레이어는 캐시 재사용.
#    requirements는 모두 manylinux 휠이 있어 빌드 도구(gcc) 불필요.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 2) 애플리케이션 소스(app 패키지만). data/.env 등은 .dockerignore로 제외.
COPY app ./app

# 3) 비루트 사용자로 실행(보안).
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8008

# lifespan에서 Neo4j 연결 확인 + 스키마 init(idempotent) 후 질의 서버 기동.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
