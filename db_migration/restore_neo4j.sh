#!/usr/bin/env bash
#
# restore_neo4j.sh — tar.gz 백업을 Neo4j 데이터 볼륨에 복원한다. (서버에서 실행)
#
#   - backup_neo4j.sh 로 만든 tar.gz 를 받아 대상 볼륨에 풀어넣는다. (파일 전송은 하지 않음)
#   - 대상 볼륨이 없으면 새로 만든다. 이미 데이터가 있으면 전부 지우고 덮어쓴다.
#   - docker CLI 만 있으면 동작한다 (docker compose 불필요).
#   - Neo4j 와 백업의 메이저 버전이 같아야 안전하다 (이 프로젝트는 neo4j:5.26).
#
# 사용법:
#   ./db_migration/restore_neo4j.sh neo4j_backup_20260605.tar.gz
#   ./db_migration/restore_neo4j.sh dump.tar.gz --volume my_neo4j_data   # 서버 볼륨명이 다를 때
#   ./db_migration/restore_neo4j.sh dump.tar.gz --force                  # 확인 프롬프트 생략
#
set -euo pipefail

VOLUME="${NEO4J_VOLUME:-code_neo4j_data}"
CONTAINER="${NEO4J_CONTAINER:-panrye-neo4j}"
IMAGE="${NEO4J_IMAGE:-neo4j:5.26}"
FORCE=0
ARCHIVE=""

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --volume)    VOLUME="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --force)     FORCE=1; shift ;;
    -h|--help)   usage 0 ;;
    -*) echo "알 수 없는 옵션: $1" >&2; usage 1 ;;
    *)  ARCHIVE="$1"; shift ;;
  esac
done

[ -n "$ARCHIVE" ] || { echo "ERROR: 복원할 tar.gz 경로를 지정하세요." >&2; usage 1; }
[ -f "$ARCHIVE" ] || { echo "ERROR: 파일을 찾을 수 없습니다: $ARCHIVE" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker 가 필요합니다." >&2; exit 1; }

ARCH_DIR="$(cd "$(dirname "$ARCHIVE")" && pwd)"
ARCH_BASE="$(basename "$ARCHIVE")"

# 대상 볼륨 준비
if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "⚠️  볼륨 '$VOLUME' 의 기존 내용을 모두 삭제하고 복원합니다."
else
  echo "→ 볼륨 '$VOLUME' 이 없어 새로 생성합니다."
  docker volume create "$VOLUME" >/dev/null
fi

# 덮어쓰기 확인
if [ "$FORCE" -ne 1 ]; then
  printf "계속하려면 'yes' 를 입력하세요: "
  read -r ans
  [ "$ans" = "yes" ] || { echo "취소되었습니다."; exit 1; }
fi

# 실행 중인 컨테이너가 해당 볼륨을 쓰고 있으면 정지
restarted=0
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "→ '$CONTAINER' 컨테이너를 정지합니다."
  docker stop "$CONTAINER" >/dev/null
  restarted=1
fi

echo "→ 복원 중: ${ARCH_DIR}/${ARCH_BASE}  →  볼륨 '$VOLUME'"
docker run --rm \
  -v "$VOLUME":/data \
  -v "$ARCH_DIR":/backup:ro \
  alpine sh -c "find /data -mindepth 1 -delete; tar xzf /backup/'${ARCH_BASE}' -C /data"

if [ "$restarted" -eq 1 ]; then
  echo "→ '$CONTAINER' 컨테이너를 재시작합니다."
  docker start "$CONTAINER" >/dev/null
  echo "✓ 복원 완료. (컨테이너 재시작됨)"
else
  echo "✓ 복원 완료. 아직 Neo4j 컨테이너가 없다면 아래처럼 기동하세요:"
  echo ""
  echo "    docker run -d --name $CONTAINER \\"
  echo "      -p 7474:7474 -p 7687:7687 \\"
  echo "      -e NEO4J_AUTH=neo4j/please_change_me \\"
  echo "      -e NEO4J_PLUGINS='[\"apoc\"]' \\"
  echo "      -v $VOLUME:/data \\"
  echo "      $IMAGE"
fi
