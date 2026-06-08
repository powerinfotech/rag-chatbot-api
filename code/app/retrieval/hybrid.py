"""하이브리드 리트리벌: 벡터 검색 + 그래프 확장 결합."""

from __future__ import annotations

from app.retrieval.graph import entities_in_chunks, graph_expand
from app.retrieval.vector import vector_search
from app.types import RetrievalResult, RetrievedChunk


def hybrid_retrieve(
    query: str,
    *,
    top_k: int | None = None,
    expand_limit: int | None = None,
) -> RetrievalResult:
    vec = vector_search(query, top_k)

    # 임계값을 통과한 벡터 근거가 하나도 없으면 '근거 없음'으로 보고 빈 결과 반환.
    # 무관한 seed에서 그래프를 확장하면 무관한 내용이 더 끌려오므로 확장도 하지 않는다.
    if not vec:
        return RetrievalResult(query=query, chunks=[], entities=[])

    seeds = [c.chunk_id for c in vec]

    expanded = graph_expand(seeds, expand_limit)
    entities = entities_in_chunks(seeds)

    # 벡터 결과(score순)를 먼저, 이어서 그래프 결과(shared순)를 append하며
    # chunk_id로 중복 제거 — 동일 청크는 벡터 히트를 유지.
    combined: list[RetrievedChunk] = []
    seen: set[str] = set()
    for chunk in (*vec, *expanded):
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        combined.append(chunk)

    return RetrievalResult(query=query, chunks=combined, entities=entities)
