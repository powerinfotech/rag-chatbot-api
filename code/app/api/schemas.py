from __future__ import annotations

from pydantic import BaseModel, Field

from app.types import ChatResult, SourceRef


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceRef] = Field(default_factory=list)
    retrieved: int = 0

    @classmethod
    def from_result(cls, result: ChatResult) -> "ChatResponse":
        return cls(
            answer=result.answer,
            sources=result.sources,
            retrieved=result.retrieved,
        )


class HealthResponse(BaseModel):
    status: str
    neo4j: bool
    ollama: bool
    llm_model: str
    embed_model: str
