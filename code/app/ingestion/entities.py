"""LLM 기반 엔티티·관계 추출. 실패 시 항상 ([], [])."""

from __future__ import annotations

import json
import logging

from app.core.llm import generate
from app.core.prompts import ENTITY_EXTRACTION_PROMPT
from app.schema import canonical_entity_type, entity_key
from app.types import Entity, Relation

logger = logging.getLogger(__name__)


def _extract_json_object(raw: str) -> str | None:
    """코드펜스 제거 후 첫 번째 균형 잡힌 {...} 객체를 추출."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_entities_relations(text: str) -> tuple[list[Entity], list[Relation]]:
    try:
        raw = generate(ENTITY_EXTRACTION_PROMPT + text[:4000])
        blob = _extract_json_object(raw)
        if not blob:
            return [], []
        data = json.loads(blob)

        entities: list[Entity] = []
        seen: set[str] = set()
        for item in data.get("entities", []) or []:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            type_ = canonical_entity_type(item.get("type", ""))
            key = entity_key(name, type_)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                Entity(name=name, type=type_, description=str(item.get("description", "") or ""))
            )

        relations: list[Relation] = []
        for item in data.get("relations", []) or []:
            source = str(item.get("source", "")).strip()
            target = str(item.get("target", "")).strip()
            rel_type = str(item.get("type", "") or "관련").strip() or "관련"
            if not source or not target:
                continue
            relations.append(
                Relation(
                    source=source,
                    target=target,
                    type=rel_type,
                    description=str(item.get("description", "") or ""),
                )
            )
        return entities, relations
    except Exception as exc:  # noqa: BLE001
        logger.warning("엔티티 추출 실패: %s", exc)
        return [], []
