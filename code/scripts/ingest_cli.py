from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db.neo4j_client import init_schema, verify_connectivity  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="판례 문서를 Neo4j에 적재")
    parser.add_argument("path", nargs="?", default=settings.docs_dir, help="파일 또는 디렉터리")
    parser.add_argument("--reset", action="store_true", help="기존 그래프 초기화 후 적재")
    args = parser.parse_args()

    if not verify_connectivity():
        print("Neo4j에 연결할 수 없습니다. Docker로 Neo4j를 먼저 실행하세요.", file=sys.stderr)
        return 1
    init_schema()

    from app.ingestion.pipeline import ingest_path

    result = ingest_path(args.path, reset=args.reset)
    print(
        f"적재 완료 → 문서 {result.documents}건, 청크 {result.chunks}개, "
        f"엔티티 {result.entities}개, 관계 {result.relations}개"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
