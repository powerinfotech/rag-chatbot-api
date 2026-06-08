"""에이전트 간 공용 데이터 계약. 모든 레이어는 여기 타입을 import 해서 사용."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Entity(BaseModel):
    name: str
    type: str = "기타"
    description: str = ""


class Relation(BaseModel):
    source: str
    target: str
    type: str
    description: str = ""


class TextChunk(BaseModel):
    """인제스션 청킹 산출물 — 청크 본문과 출처 섹션 라벨."""

    text: str
    section: str = ""  # 판시사항 / 이유 / 머리말 등 (구조 미인식 시 "")


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str = ""
    filename: str = ""
    text: str = ""
    score: float = 0.0
    chunk_index: int | None = None
    section: str = ""  # 판시사항 / 이유 / 머리말 등 (구조 미인식 시 "")
    source: str = "vector"  # vector | graph | fulltext


class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    doc_id: str = ""
    filename: str = ""
    chunk_id: str = ""
    section: str = ""
    score: float = 0.0


class ChatResult(BaseModel):
    answer: str
    sources: list[SourceRef] = Field(default_factory=list)
    retrieved: int = 0


class IngestResult(BaseModel):
    documents: int = 0
    chunks: int = 0
    entities: int = 0
    relations: int = 0
    files: list[str] = Field(default_factory=list)
