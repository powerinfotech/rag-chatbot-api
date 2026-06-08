"""벡터 검색 + 풀텍스트 검색 (Chunk 노드 대상)."""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.core.embeddings import embed_query
from app.db.neo4j_client import run_query
from app.schema import FULLTEXT_INDEX, VECTOR_INDEX
from app.types import RetrievedChunk

logger = logging.getLogger(__name__)

# Lucene 예약 문자 — 풀텍스트 질의에서 제거해 파싱 오류 방지.
_LUCENE_SPECIAL = re.compile(r'[+\-&|!(){}\[\]^"~*?:\\/]')


def vector_search(
    query: str, k: int | None = None, min_score: float | None = None
) -> list[RetrievedChunk]:
    emb = embed_query(query)
    k = k or settings.retrieval_top_k
    min_score = settings.retrieval_min_score if min_score is None else min_score

    # 코사인 유사도가 임계값(min_score) 미만인 청크는 '근거 없음'으로 버린다.
    # → 무관한 질문에 억지로 끌려온 청크를 차단해 할루시네이션을 막는다.
    cypher = """
    CALL db.index.vector.queryNodes($index, $k, $embedding) YIELD node, score
    WHERE score >= $min_score
    MATCH (d:Document)-[:HAS_CHUNK]->(node)
    RETURN node.chunk_id AS chunk_id, node.doc_id AS doc_id, d.filename AS filename,
           node.text AS text, node.index AS chunk_index, node.section AS section,
           score AS score
    """
    rows = run_query(
        cypher,
        {"index": VECTOR_INDEX, "k": k, "embedding": emb, "min_score": min_score},
    )
    if not rows:
        logger.info("벡터 검색: 임계값 %.2f 이상 청크 없음 (query=%r)", min_score, query[:50])
    return [
        RetrievedChunk(
            chunk_id=r["chunk_id"],
            doc_id=r.get("doc_id") or "",
            filename=r.get("filename") or "",
            text=r.get("text") or "",
            score=float(r.get("score") or 0.0),
            chunk_index=r.get("chunk_index"),
            section=r.get("section") or "",
            source="vector",
        )
        for r in rows
    ]


def _sanitize_lucene(query: str) -> str:
    cleaned = _LUCENE_SPECIAL.sub(" ", query)
    return " ".join(cleaned.split())


def fulltext_search(query: str, k: int | None = None) -> list[RetrievedChunk]:
    k = k or settings.retrieval_top_k
    safe = _sanitize_lucene(query)
    if not safe:
        return []

    cypher = """
    CALL db.index.fulltext.queryNodes($index, $query) YIELD node, score
    MATCH (d:Document)-[:HAS_CHUNK]->(node)
    RETURN node.chunk_id AS chunk_id, node.doc_id AS doc_id, d.filename AS filename,
           node.text AS text, node.index AS chunk_index, node.section AS section,
           score AS score
    LIMIT $k
    """
    try:
        rows = run_query(cypher, {"index": FULLTEXT_INDEX, "query": safe, "k": k})
    except Exception as exc:  # noqa: BLE001 - 한국어 토큰화로 결과 없을 수 있음
        logger.warning("풀텍스트 검색 실패: %s", exc)
        return []
    return [
        RetrievedChunk(
            chunk_id=r["chunk_id"],
            doc_id=r.get("doc_id") or "",
            filename=r.get("filename") or "",
            text=r.get("text") or "",
            score=float(r.get("score") or 0.0),
            chunk_index=r.get("chunk_index"),
            section=r.get("section") or "",
            source="fulltext",
        )
        for r in rows
    ]
