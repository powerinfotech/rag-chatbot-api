"""인제스션 파이프라인: doc/docx → chunk → embed → Neo4j 그래프."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core.embeddings import embed_texts
from app.db.neo4j_client import execute_write, init_schema, reset_graph
from app.ingestion.chunking import chunk_text
from app.ingestion.entities import extract_entities_relations
from app.ingestion.loaders import iter_document_paths, load_text
from app.schema import entity_key, normalize_text
from app.types import Entity, IngestResult, Relation

logger = logging.getLogger(__name__)

_SOURCE = "판례"
_ENTITY_TEXT_LIMIT = 6000

_WRITE_DOC_CHUNKS = """
MERGE (d:Document {doc_id: $doc_id})
SET d.filename = $filename, d.path = $path, d.source = $source,
    d.created_at = coalesce(d.created_at, $created_at)
WITH d
UNWIND $chunks AS ch
MERGE (c:Chunk {chunk_id: ch.chunk_id})
SET c.doc_id = $doc_id, c.index = ch.index, c.text = ch.text,
    c.section = ch.section, c.embedding = ch.embedding
MERGE (d)-[:HAS_CHUNK]->(c)
"""

_LINK_NEXT = """
UNWIND $pairs AS p
MATCH (a:Chunk {chunk_id: p.prev})
MATCH (b:Chunk {chunk_id: p.next})
MERGE (a)-[:NEXT_CHUNK]->(b)
"""

_MERGE_ENTITIES = """
UNWIND $entities AS e
MERGE (n:Entity {key: e.key})
SET n.name = e.name, n.type = e.type,
    n.description = coalesce(n.description, '') + CASE
        WHEN e.description <> '' AND NOT coalesce(n.description, '') CONTAINS e.description
        THEN e.description ELSE '' END
"""

_LINK_MENTIONS = """
UNWIND $mentions AS m
MATCH (c:Chunk {chunk_id: m.chunk_id})
MATCH (n:Entity {key: m.key})
MERGE (c)-[:MENTIONS]->(n)
"""

_MERGE_RELATIONS = """
UNWIND $relations AS r
MERGE (s:Entity {key: r.source_key})
ON CREATE SET s.name = r.source_name, s.type = r.rel_node_type, s.description = ''
MERGE (t:Entity {key: r.target_key})
ON CREATE SET t.name = r.target_name, t.type = r.rel_node_type, t.description = ''
MERGE (s)-[rel:RELATED_TO {type: r.type}]->(t)
SET rel.description = r.description
"""


def _doc_id(abspath: str) -> str:
    return hashlib.sha1(abspath.encode("utf-8")).hexdigest()[:16]


def _ingest_file(file: Path) -> IngestResult:
    text = load_text(file)
    chunks = chunk_text(text)
    if not chunks:
        logger.warning("청크가 없어 건너뜀: %s", file)
        return IngestResult(documents=0, chunks=0, entities=0, relations=0, files=[])

    abspath = str(file.resolve())
    doc_id = _doc_id(abspath)
    embeddings = embed_texts([c.text for c in chunks])

    chunk_rows = [
        {
            "chunk_id": f"{doc_id}::{i}",
            "index": i,
            "text": c.text,
            "section": c.section,
            "embedding": emb,
        }
        for i, (c, emb) in enumerate(zip(chunks, embeddings))
    ]

    # 1) Document + Chunk + HAS_CHUNK 먼저 커밋 → 엔티티 추출이 실패해도 벡터 검색 가능.
    execute_write(
        _WRITE_DOC_CHUNKS,
        {
            "doc_id": doc_id,
            "filename": file.name,
            "path": str(file),
            "source": _SOURCE,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "chunks": chunk_rows,
        },
    )
    if len(chunk_rows) > 1:
        pairs = [
            {"prev": chunk_rows[i]["chunk_id"], "next": chunk_rows[i + 1]["chunk_id"]}
            for i in range(len(chunk_rows) - 1)
        ]
        execute_write(_LINK_NEXT, {"pairs": pairs})

    entity_count = 0
    relation_count = 0
    # 2) 엔티티 그래프: 문서당 LLM 1회. 실패해도 파일 인제스션은 성공 처리.
    try:
        entities, relations = extract_entities_relations(text[:_ENTITY_TEXT_LIMIT])
        entity_count, relation_count = _write_entity_graph(
            doc_id, chunk_rows, entities, relations
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("엔티티 그래프 적재 실패 (%s): %s", file.name, exc)

    return IngestResult(
        documents=1,
        chunks=len(chunk_rows),
        entities=entity_count,
        relations=relation_count,
        files=[file.name],
    )


def _write_entity_graph(
    doc_id: str,
    chunk_rows: list[dict],
    entities: list[Entity],
    relations: list[Relation],
) -> tuple[int, int]:
    if not entities and not relations:
        return 0, 0

    entity_payload = [
        {"key": entity_key(e.name, e.type), "name": e.name, "type": e.type, "description": e.description}
        for e in entities
    ]
    if entity_payload:
        execute_write(_MERGE_ENTITIES, {"entities": entity_payload})

    # MENTIONS: 청크 텍스트에 엔티티 name이 부분 문자열로 등장하면 연결.
    # 어떤 청크에도 없으면 index 0 청크에 연결.
    mentions: list[dict] = []
    for e in entities:
        key = entity_key(e.name, e.type)
        matched = False
        for row in chunk_rows:
            if e.name and e.name in row["text"]:
                mentions.append({"chunk_id": row["chunk_id"], "key": key})
                matched = True
        if not matched:
            mentions.append({"chunk_id": f"{doc_id}::0", "key": key})
    if mentions:
        execute_write(_LINK_MENTIONS, {"mentions": mentions})

    # RELATED_TO: 관계의 source/target을 '정규화된 이름'으로 추출 엔티티에 매칭해 type을 물려받는다.
    # (표기 흔들림 흡수 → 진짜 엔티티 노드와 동일한 키로 병합) 매칭 실패 시에만 '기타'로 MERGE.
    norm_to_type = {normalize_text(e.name): e.type for e in entities}
    rel_payload = [
        {
            "source_key": entity_key(r.source, norm_to_type.get(normalize_text(r.source), "기타")),
            "source_name": r.source,
            "target_key": entity_key(r.target, norm_to_type.get(normalize_text(r.target), "기타")),
            "target_name": r.target,
            "rel_node_type": "기타",
            "type": r.type,
            "description": r.description,
        }
        for r in relations
    ]
    if rel_payload:
        execute_write(_MERGE_RELATIONS, {"relations": rel_payload})

    return len(entity_payload), len(rel_payload)


def _resolve_paths(path: str) -> list[Path]:
    p = Path(path)
    if p.is_dir():
        return iter_document_paths(p)
    return [p]


def ingest_path(path: str, *, reset: bool = False) -> IngestResult:
    init_schema()
    if reset:
        reset_graph()

    total = IngestResult()
    for file in _resolve_paths(path):
        try:
            result = _ingest_file(file)
        except Exception as exc:  # noqa: BLE001
            logger.error("파일 인제스션 실패 (%s): %s", file, exc)
            continue
        total.documents += result.documents
        total.chunks += result.chunks
        total.entities += result.entities
        total.relations += result.relations
        total.files.extend(result.files)
    return total
