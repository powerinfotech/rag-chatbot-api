"""그래프 확장 검색: 공유 엔티티 기반으로 인접 Chunk 탐색."""

from __future__ import annotations

import logging

from app.config import settings
from app.db.neo4j_client import run_query
from app.types import RetrievedChunk

logger = logging.getLogger(__name__)


def graph_expand(
    chunk_ids: list[str], limit: int | None = None
) -> list[RetrievedChunk]:
    """시드 청크가 언급한 엔티티를 공유하는 다른 청크를 공유 엔티티 수 순으로 반환."""
    if not chunk_ids:
        return []
    limit = limit or settings.graph_expand_limit

    cypher = """
    MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(other:Chunk)
    WHERE c.chunk_id IN $chunk_ids AND NOT other.chunk_id IN $chunk_ids
    MATCH (d:Document)-[:HAS_CHUNK]->(other)
    WITH other, d, count(DISTINCT e) AS shared
    RETURN other.chunk_id AS chunk_id, other.doc_id AS doc_id, d.filename AS filename,
           other.text AS text, other.index AS chunk_index, other.section AS section,
           shared AS shared
    ORDER BY shared DESC LIMIT $limit
    """
    try:
        rows = run_query(cypher, {"chunk_ids": chunk_ids, "limit": limit})
    except Exception as exc:  # noqa: BLE001
        logger.warning("그래프 확장 실패: %s", exc)
        return []
    return [
        RetrievedChunk(
            chunk_id=r["chunk_id"],
            doc_id=r.get("doc_id") or "",
            filename=r.get("filename") or "",
            text=r.get("text") or "",
            score=float(r.get("shared") or 0.0),
            chunk_index=r.get("chunk_index"),
            section=r.get("section") or "",
            source="graph",
        )
        for r in rows
    ]


def entities_in_chunks(chunk_ids: list[str]) -> list[str]:
    """시드 청크가 언급한 엔티티 이름(중복 제거)."""
    if not chunk_ids:
        return []

    cypher = """
    MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)
    WHERE c.chunk_id IN $chunk_ids
    RETURN DISTINCT e.name AS name
    LIMIT 50
    """
    try:
        rows = run_query(cypher, {"chunk_ids": chunk_ids})
    except Exception as exc:  # noqa: BLE001
        logger.warning("엔티티 조회 실패: %s", exc)
        return []
    return [r["name"] for r in rows if r.get("name")]
