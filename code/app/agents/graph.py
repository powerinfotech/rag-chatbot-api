"""LangGraph 오케스트레이션 + FastAPI 연동 진입점."""

from __future__ import annotations

import functools

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import build_context_node, generate_node, retrieve_node
from app.agents.state import GraphState
from app.types import ChatResult


@functools.lru_cache
def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("build_context", build_context_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "build_context")
    graph.add_edge("build_context", "generate")
    graph.add_edge("generate", END)

    return graph.compile()


def answer_question(question: str, top_k: int | None = None) -> ChatResult:
    final = build_graph().invoke({"question": question, "top_k": top_k})
    retrieval = final.get("retrieval")
    return ChatResult(
        answer=final.get("answer", ""),
        sources=final.get("sources", []),
        retrieved=len(retrieval.chunks) if retrieval else 0,
    )
