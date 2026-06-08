from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.routes import router
from app.config import settings
from app.db.neo4j_client import init_schema, verify_connectivity

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if verify_connectivity():
        try:
            init_schema()
        except Exception as exc:  # noqa: BLE001
            logger.warning("스키마 초기화 생략: %s", exc)
    else:
        logger.warning(
            "Neo4j에 연결할 수 없습니다. Docker로 Neo4j를 먼저 띄우세요"
            " (적재는 로컬 scripts/ingest_cli.py, 서버는 볼륨 복원)."
        )
    yield


app = FastAPI(
    title="판례 RAG (Neo4j + Gemma4 + LangGraph)",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — 브라우저 프론트엔드에서 직접 호출 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,   # .env CORS_ALLOW_ORIGINS (로컬=*, 운영=특정 origin)
    allow_credentials=False,   # 프론트가 withCredentials:false 라서 False면 충분
    allow_methods=["*"],       # OPTIONS(preflight) + POST 허용
    allow_headers=["*"],       # content-type, showLoading 등 허용
)

app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")
