"""그래프 노드: retrieve → build_context → generate."""

from __future__ import annotations

from app.agents.state import GraphState
from app.core.llm import get_llm
from app.core.prompts import QA_SYSTEM_PROMPT, build_qa_prompt, refusal_message_for
from app.retrieval.hybrid import hybrid_retrieve
from app.types import RetrievedChunk, SourceRef

_CONTEXT_CHAR_BUDGET = 8000


def retrieve_node(state: GraphState) -> dict:
    res = hybrid_retrieve(state["question"], top_k=state.get("top_k"))
    return {"retrieval": res}


def _source_rank(chunk: RetrievedChunk) -> tuple[bool, float]:
    """doc별 대표 출처 청크를 고르는 정렬 키.

    벡터 검색은 코사인 유사도(0~1)를, 그래프 확장은 공유 엔티티 수(정수)를
    같은 score 필드에 담는다. 척도가 달라 그대로 비교하면 그래프 청크의 큰
    정수(예: 6.0)가 더 관련 높은 벡터 청크(예: 0.87)를 눌러버린다.
    그래서 (1) 벡터 히트를 그래프 확장보다 항상 우선하고,
    (2) 같은 종류 안에서만 점수로 비교한다.
    """
    return (chunk.source == "vector", chunk.score)


def build_context_node(state: GraphState) -> dict:
    retrieval = state.get("retrieval")
    chunks = retrieval.chunks if retrieval else []

    parts: list[str] = []
    best_by_doc: dict[str, RetrievedChunk] = {}
    order: list[str] = []  # doc_id 등장 순서 보존
    used = 0

    for i, chunk in enumerate(chunks, start=1):
        label = f" · {chunk.section}" if chunk.section else ""
        block = f"[{i}] ({chunk.filename}{label})\n{chunk.text}"
        # 예산 초과 시 추가 중단 (단 첫 청크는 보장)
        if used and used + len(block) > _CONTEXT_CHAR_BUDGET:
            break
        parts.append(block)
        used += len(block)

        # 표시한 청크에 한해 doc 단위로 대표 출처를 집계.
        # 벡터(코사인) 히트를 그래프 확장(공유 엔티티 수)보다 우선해 고른다.
        doc_id = chunk.doc_id
        current = best_by_doc.get(doc_id)
        if current is None:
            order.append(doc_id)
            best_by_doc[doc_id] = chunk
        elif _source_rank(chunk) > _source_rank(current):
            best_by_doc[doc_id] = chunk

    ctx = "\n\n".join(parts)
    sources = [
        SourceRef(
            doc_id=chunk.doc_id,
            filename=chunk.filename,
            chunk_id=chunk.chunk_id,
            section=chunk.section,
            score=chunk.score,
        )
        for chunk in (best_by_doc[doc_id] for doc_id in order)
    ]
    return {"context": ctx, "sources": sources}


def generate_node(state: GraphState) -> dict:
    context = state.get("context", "")
    if not context.strip():
        # 검색 게이팅에서 임계값 통과 근거가 없으면 LLM을 호출하지 않고 즉시 거부(질문 언어에 맞춤).
        return {"answer": refusal_message_for(state["question"])}

    answer = (
        get_llm()
        .invoke(
            [
                ("system", QA_SYSTEM_PROMPT),
                ("human", build_qa_prompt(state["question"], context)),
            ]
        )
        .content
    )
    return {"answer": answer}
