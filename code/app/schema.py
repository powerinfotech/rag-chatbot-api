"""Neo4j 그래프 스키마 계약 (인제스션/리트리벌 공용).

Node 속성 규약:
  (:Document)  doc_id(unique), filename, path, source, created_at
  (:Chunk)     chunk_id(unique, = f"{doc_id}::{index}"), doc_id, index, text, section, embedding(list[float])
  (:Entity)    key(unique, = entity_key(name, type)), name, type, description

Relationship:
  (Document)-[:HAS_CHUNK]->(Chunk)
  (Chunk)-[:NEXT_CHUNK]->(Chunk)        # 동일 문서 내 인접 청크
  (Chunk)-[:MENTIONS]->(Entity)
  (Entity)-[:RELATED_TO {type}]->(Entity)
"""

from __future__ import annotations

import re
import unicodedata

# Node labels
DOCUMENT = "Document"
CHUNK = "Chunk"
ENTITY = "Entity"

# Relationship types
HAS_CHUNK = "HAS_CHUNK"
NEXT_CHUNK = "NEXT_CHUNK"
MENTIONS = "MENTIONS"
RELATED_TO = "RELATED_TO"

# Index names
VECTOR_INDEX = "chunk_embedding_index"
FULLTEXT_INDEX = "chunk_fulltext_index"


# 엔티티 type 고정 목록 — LLM 추출 type의 흔들림을 막아 노드 파편화를 억제한다.
# 인제스션 추출(프롬프트)과 적재(클램프)가 동일한 어휘를 공유한다.
ENTITY_TYPES: tuple[str, ...] = (
    "법원",
    "사건번호",
    "당사자",
    "법조항",
    "법령",
    "쟁점",
    "날짜",
    "재판부",
    "기타",
)

# 자주 나오는 표기를 고정 목록으로 흡수(목록·별칭에 없으면 '기타'로 클램프).
_ENTITY_TYPE_ALIASES: dict[str, str] = {
    "원고": "당사자",
    "피고": "당사자",
    "신청인": "당사자",
    "피신청인": "당사자",
    "상고인": "당사자",
    "피상고인": "당사자",
    "항소인": "당사자",
    "피항소인": "당사자",
    "인물": "당사자",
    "회사": "당사자",
    "법인": "당사자",
    "법률": "법령",
    "법": "법령",
    "조항": "법조항",
    "조문": "법조항",
    "법조문": "법조항",
    "판례": "사건번호",
    "선고일": "날짜",
    "일자": "날짜",
    "판사": "재판부",
    "법관": "재판부",
    "이슈": "쟁점",
    "논점": "쟁점",
}


def normalize_text(text: str) -> str:
    """키 정규화 공통 규칙: NFKC(전각/반각 통일) → 소문자화 → 모든 공백 제거.

    같은 normalize_text 결과를 갖는 두 문자열은 키/이름 매칭에서 동일하게 취급된다.
    (엔티티 키 생성과 관계 끝점 매칭이 이 동일 규칙을 공유한다.)
    """
    norm = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", "", norm.strip().lower())


def canonical_entity_type(raw: str) -> str:
    """추출된 type을 고정 목록(ENTITY_TYPES)으로 클램프. 별칭은 흡수, 그 외는 '기타'."""
    t = re.sub(r"\s+", "", str(raw or "").strip())
    if t in ENTITY_TYPES:
        return t
    return _ENTITY_TYPE_ALIASES.get(t, "기타")


def entity_key(name: str, type_: str) -> str:
    """엔티티 MERGE에 쓰는 정규화 키 (인제스션/리트리벌 동일 규칙).

    NFKC 정규화 + 소문자화 + 공백 제거로 표기 흔들림을 흡수한다.
    예) '중재법 제35조' / '중재법제35조' / '중재법 제３５조'(전각 숫자) → 동일 키.
    """
    return f"{normalize_text(type_)}:{normalize_text(name)}"


def schema_statements(embed_dim: int) -> list[str]:
    """제약/인덱스 DDL. 모두 IF NOT EXISTS 라 반복 실행 안전."""
    return [
        f"CREATE CONSTRAINT document_id IF NOT EXISTS "
        f"FOR (d:{DOCUMENT}) REQUIRE d.doc_id IS UNIQUE",
        f"CREATE CONSTRAINT chunk_id IF NOT EXISTS "
        f"FOR (c:{CHUNK}) REQUIRE c.chunk_id IS UNIQUE",
        f"CREATE CONSTRAINT entity_key IF NOT EXISTS "
        f"FOR (e:{ENTITY}) REQUIRE e.key IS UNIQUE",
        f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS "
        f"FOR (c:{CHUNK}) ON (c.embedding) "
        f"OPTIONS {{ indexConfig: {{ "
        f"`vector.dimensions`: {embed_dim}, "
        f"`vector.similarity_function`: 'cosine' }} }}",
        f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS "
        f"FOR (c:{CHUNK}) ON EACH [c.text]",
    ]
