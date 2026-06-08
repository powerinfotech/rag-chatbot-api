from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException

from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
)
from app.config import settings
from app.db.neo4j_client import verify_connectivity

logger = logging.getLogger(__name__)
router = APIRouter()


def _ollama_up() -> bool:
    try:
        r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        neo4j=verify_connectivity(),
        ollama=_ollama_up(),
        llm_model=settings.llm_model,
        embed_model=settings.embed_model,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    from app.agents.graph import answer_question  # 지연 import (에이전트 구현)

    try:
        result = answer_question(req.question, top_k=req.top_k)
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat 실패")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse.from_result(result)
