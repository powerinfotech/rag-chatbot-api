"""LangGraph 그래프 상태 정의."""

from __future__ import annotations

from typing import Optional, TypedDict

from app.types import RetrievalResult, SourceRef


class GraphState(TypedDict, total=False):
    question: str
    top_k: Optional[int]
    retrieval: Optional[RetrievalResult]
    context: str
    answer: str
    sources: list[SourceRef]
