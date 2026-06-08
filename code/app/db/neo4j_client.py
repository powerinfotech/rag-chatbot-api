from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from neo4j import Driver, GraphDatabase

from app.config import settings
from app.schema import schema_statements

logger = logging.getLogger(__name__)


@lru_cache
def get_driver() -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )


def close_driver() -> None:
    if get_driver.cache_info().currsize:
        get_driver().close()
        get_driver.cache_clear()


def run_query(
    cypher: str,
    params: dict[str, Any] | None = None,
    database: str | None = None,
) -> list[dict[str, Any]]:
    driver = get_driver()
    with driver.session(database=database or settings.neo4j_database) as session:
        result = session.run(cypher, params or {})
        return [record.data() for record in result]


def execute_write(
    cypher: str,
    params: dict[str, Any] | None = None,
    database: str | None = None,
) -> list[dict[str, Any]]:
    """명시적 쓰기 트랜잭션. 배치 적재 시 사용."""
    driver = get_driver()
    with driver.session(database=database or settings.neo4j_database) as session:
        return session.execute_write(
            lambda tx: [r.data() for r in tx.run(cypher, params or {})]
        )


def verify_connectivity() -> bool:
    try:
        get_driver().verify_connectivity()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Neo4j 연결 실패: %s", exc)
        return False


def init_schema() -> None:
    for stmt in schema_statements(settings.embed_dim):
        run_query(stmt)
    logger.info("Neo4j 스키마/인덱스 적용 완료.")


def reset_graph() -> None:
    """모든 노드/관계 삭제 (인덱스/제약은 유지)."""
    run_query("MATCH (n) DETACH DELETE n")
    logger.info("그래프 데이터 초기화 완료.")
