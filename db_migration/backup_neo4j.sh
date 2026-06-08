#!/usr/bin/env bash
#
# backup_neo4j.sh — 로컬 Neo4j 데이터 볼륨을 tar.gz 파일로 백업한다.
#
#   - 적재된 노드/관계/임베딩은 Docker 볼륨(기본: code_neo4j_data)에 들어있다.
#   - 이 스크립트는 그 볼륨을 통째로 tar.gz 로 묶기만 한다. (서버 전송은 하지 않음)
#   - 데이터 일관성을 위해 기본적으로 백업 중 Neo4j 컨테이너를 잠깐 멈췄다 켠다.
#     (멈추기 싫으면 --no-stop — 읽기전용 마운트라 보통 안전하지만 콜드백업이 가장 안전)
#
# 사용법:
#   ./db_migration/backup_neo4j.sh                          # code_neo4j_data → neo4j_backup_<날짜>.tar.gz
#   ./db_migration/backup_neo4j.sh -o /path/dump.tar.gz     # 출력 경로 지정
#   ./db_migration/backup_neo4j.sh --no-stop                # 컨테이너 안 멈추고 핫백업
#   NEO4J_VOLUME=other_data ./db_migration/backup_neo4j.sh  # 볼륨명 환경변수로 지정
#
set -euo pipefail

VOLUME="${NEO4J_VOLUME:-code_neo4j_data}"
CONTAINER="${NEO4J_CONTAINER:-panrye-neo4j}"
STOP=1
OUT=""

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -o|--output)    OUT="$2"; shift 2 ;;
    --volume)       VOLUME="$2"; shift 2 ;;
    --container)    CONTAINER="$2"; shift 2 ;;
    --no-stop)      STOP=0; shift ;;
    -h|--help)      usage 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage 1 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker 가 필요합니다." >&2; exit 1; }

if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "ERROR: 볼륨 '$VOLUME' 을 찾을 수 없습니다." >&2
  echo "       현재 볼륨 목록: $(docker volume ls --format '{{.Name}}' | tr '\n' ' ')" >&2
  exit 1
fi

ts="$(date +%Y%m%d_%H%M%S)"
OUT="${OUT:-neo4j_backup_${ts}.tar.gz}"
OUT_DIR="$(cd "$(dirname "$OUT")" && pwd)"
OUT_BASE="$(basename "$OUT")"

# 데이터 일관성을 위해 컨테이너 정지 (떠 있고 --no-stop 아닐 때)
restarted=0
if [ "$STOP" -eq 1 ] && docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "→ 일관성을 위해 '$CONTAINER' 컨테이너를 정지합니다."
  docker stop "$CONTAINER" >/dev/null
  restarted=1
fi

echo "→ 백업 중: 볼륨 '$VOLUME'  →  ${OUT_DIR}/${OUT_BASE}"
docker run --rm \
  -v "$VOLUME":/data:ro \
  -v "$OUT_DIR":/backup \
  alpine sh -c "tar czf /backup/'${OUT_BASE}' -C /data ."

# 컨테이너 재시작 (정지했던 경우만)
if [ "$restarted" -eq 1 ]; then
  echo "→ '$CONTAINER' 컨테이너를 재시작합니다."
  docker start "$CONTAINER" >/dev/null
fi

size="$(du -h "${OUT_DIR}/${OUT_BASE}" | cut -f1)"
echo "✓ 백업 완료: ${OUT_DIR}/${OUT_BASE} (${size})"
echo "  이 파일을 서버로 옮긴 뒤 db_migration/restore_neo4j.sh 로 복원하세요."
