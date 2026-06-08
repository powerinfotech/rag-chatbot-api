# 서버 배포 가이드 (neo4j-gemma-rag) — Docker

이 프로젝트를 **NVIDIA GPU 서버에서 Docker로** 배포하는 방법을 정리한다.
세 컨테이너(**Neo4j · Ollama(GPU) · FastAPI 앱**)를 `docker compose` 로 함께 띄운다.

> - 로컬 개발(macOS)은 Docker로 말지 않고 conda + `uvicorn --reload` 로 따로 실행한다(맨 아래 "로컬 개발" 참고).
> - 서버는 문서를 파싱/적재하지 않는다 — 데이터는 로컬에서 만든 백업을 **볼륨 복원**으로 채운다.

---

## 0. 구성 요약

| 구성요소 | 실행 형태 | 포트 | 비고 |
|----------|-----------|------|------|
| **Neo4j** | Docker | 7474 / 7687 | 데이터 볼륨 `code_neo4j_data` |
| **Ollama** | Docker (GPU) | 11434(내부) | 모델 `gemma4:e2b-it-q4_K_M`, `bge-m3` · 볼륨 `code_ollama_models` |
| **FastAPI 앱** | Docker | 8008 | `app.main:app` (질의 전용 이미지) |

compose 파일 (둘 다 `code/` 에 있음):
- `docker-compose.yml` — Neo4j (로컬·서버 공통 베이스)
- `docker-compose.prod.yml` — app + ollama(GPU) 오버레이 (**서버 전용**)

데이터 흐름: `클라이언트 → app(8008) → neo4j(7687) 검색 + ollama(11434) 임베딩/생성`

> 컨테이너는 `restart: unless-stopped` 라 죽으면 자동 재시작되고 서버 재부팅 후에도 Docker가 다시 띄운다. (systemd 불필요)

---

## 1. 사전 요구사항 (서버에 1회)

```bash
# Docker Engine + compose 플러그인 설치 (Linux · 공식 편의 스크립트; Ubuntu/Debian/CentOS 등)
#   배포판별 수동 설치/문제 해결은 공식 문서: https://docs.docker.com/engine/install/
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"               # sudo 없이 docker 실행(다시 로그인해야 적용)
docker --version && docker compose version    # 설치 확인

# 부팅 시 도커 데몬 자동 시작 여부 확인(컨테이너 자동 복구의 전제) — 편의 스크립트는 보통 자동 enable
systemctl is-enabled docker || sudo systemctl enable --now docker

# NVIDIA 드라이버 + NVIDIA Container Toolkit (GPU 패스스루)
nvidia-smi                                   # 호스트 드라이버 확인
# Toolkit 설치 가이드:
#   https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi   # 컨테이너 GPU 인식 확인
```

> Ollama 컨테이너가 GPU를 쓰려면 **NVIDIA Container Toolkit**이 반드시 설치돼 있어야 한다.
> (GPU 컨테이너 대신 호스트 Ollama로 가는 대안은 `docker-compose.prod.yml` 하단 주석 참고)

> **systemd 커스텀 유닛은 만들 필요 없다.** 세 컨테이너 모두 `restart: unless-stopped` 라 크래시 시 자동 재시작되고,
> 서버 재부팅 후엔 위에서 enable 한 도커 데몬(`docker.service`, 그 자체가 systemd로 관리됨)이 부팅되면서 컨테이너를 함께 복구한다.
> 단, `docker compose down`/`stop` 으로 **수동 중지**한 컨테이너는 재부팅해도 다시 뜨지 않는다(의도된 동작).

---

## 2. 코드 가져오기

```bash
git clone <레포 URL> neo4j-gemma-rag
cd neo4j-gemma-rag             # 레포 루트 — 백업/복원은 여기서, compose 는 code/ 에서
```

---

## 3. 환경설정(.env)

```bash
cp code/.env.example code/.env   # code/.env 생성
```

`code/.env` 에서 최소한 아래만 맞추면 된다.

- `NEO4J_PASSWORD` → 원하는 비밀번호 (compose의 `NEO4J_AUTH`가 이 값을 사용)
- `LLM_MODEL` / `EMBED_MODEL` → 아래에서 pull 할 모델명과 일치 (`gemma4:e2b-it-q4_K_M` / `bge-m3`)
- `CORS_ALLOW_ORIGINS` → 브라우저 프론트가 직접 호출하면 그 도메인만 허용(쉼표 구분). 예: `https://panrye.example.com`. 미설정 시 `*`(전체 허용). compose에서 덮어쓰려면 `docker-compose.prod.yml` 의 `app.environment` 참고.

> `NEO4J_URI`, `OLLAMA_BASE_URL` 은 신경 쓰지 않아도 된다.
> `docker-compose.prod.yml` 이 컨테이너 네트워크용(`bolt://neo4j:7687`, `http://ollama:11434`)으로 **덮어쓴다**.
> `.env`(비밀번호 포함)는 절대 커밋 금지(`.gitignore` 처리됨).

---

## 4. 데이터 준비 (볼륨 복원)

서버는 문서를 적재하지 않는다. 로컬에서 만든 백업을 복원한다.

```bash
# (로컬 Mac · 레포 루트에서) 적재 완료 후 백업 생성
./db_migration/backup_neo4j.sh                    # → neo4j_backup_<날짜>.tar.gz

# 위 파일을 서버로 전송(scp 등) 후, 서버의 레포 루트에서 복원
./db_migration/restore_neo4j.sh neo4j_backup_YYYYMMDD.tar.gz --force
#   - 볼륨 code_neo4j_data 를 생성/덮어쓴다 (Neo4j 컨테이너가 아직 없어도 OK)
#   - compose 프로젝트명이 'code' 가 아니면 볼륨명이 달라짐 → --volume <name> 으로 지정
```

> 백업/복원은 같은 Neo4j 메이저 버전(이 프로젝트는 `neo4j:5.26`)끼리만 안전하다.

---

## 5. 기동

```bash
cd code        # compose 는 code/ 에서 (프로젝트명 code → 볼륨 code_neo4j_data)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps        # 상태 확인
```

### 모델 받기 (최초 1회 — 볼륨 `code_ollama_models` 에 캐시되어 재배포에도 보존)

```bash
docker exec panrye-ollama ollama pull gemma4:e2b-it-q4_K_M
docker exec panrye-ollama ollama pull bge-m3
docker exec panrye-ollama nvidia-smi         # 컨테이너 GPU 인식 확인(선택)
```

> 매번 `-f ... -f ...` 치기 번거로우면 한 번만:
> `export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`
> 이후엔 `docker compose up -d` / `docker compose logs -f app` 처럼 짧게 쓸 수 있다.

---

## 6. 동작 확인

```bash
curl -s localhost:8008/health | python3 -m json.tool
#  → {"status":"ok","neo4j":true,"ollama":true, ...} 면 정상

curl -s -X POST localhost:8008/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"중재판정 취소 사유는?"}' | python3 -m json.tool
```

브라우저 문서: `http://<서버>:8008/docs`

---

## 7. 로그: 쌓기 & 실시간 보기

각 컨테이너의 stdout/stderr 를 Docker `json-file` 드라이버가 디스크에 저장한다.
**회전 정책은 compose에 설정돼 있다** — 서비스당 `max-size: 10m`, `max-file: 10` (최대 ~100MB, 무한 증가 방지).

```bash
# code/ 에서 (COMPOSE_FILE 설정 안 했다면 -f 두 개 붙여서)
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f app       # 앱 실시간
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f           # 전체
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --since 1h app

# 컨테이너명으로도 가능
docker logs -f panrye-app
```

회전량 조정: `docker-compose.yml`(neo4j) / `docker-compose.prod.yml`(app·ollama)의
`logging.options.max-size` · `max-file` 수정 후 `up -d` 로 재적용.

> 실제 로그 파일 위치(참고): `/var/lib/docker/containers/<id>/<id>-json.log`

---

## 8. 운영 명령 모음

```bash
# 컨테이너 (code/ 에서)
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app
docker compose -f docker-compose.yml -f docker-compose.prod.yml down         # 중지(볼륨/데이터는 유지)
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v       # ⚠️ 볼륨까지 삭제(데이터 소멸)

# 업데이트 배포 (코드 갱신 후)
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

---

## 9. 보안/네트워크 주의

- FastAPI 자체에는 **인증이 없다**. 8008 포트를 공개망에 그대로 열지 말 것.
  - 방화벽으로 내부만 허용하거나, **Nginx/Caddy 리버스 프록시 + 인증/TLS** 뒤에 둘 것.
- Neo4j 7474/7687 은 compose에서 호스트로 노출돼 있다(브라우저/복원용). 공개망 노출 주의.
  Ollama 11434 는 기본적으로 외부 미노출(컨테이너 내부 통신만).
- `.env`(비밀번호)와 Neo4j 백업 `*.tar.gz` 는 절대 커밋/공개 금지(`.gitignore` 처리됨).

---

## 로컬 개발 (macOS) — 참고

서버와 달리 로컬은 **따로따로** 띄운다 (맥은 Docker에서 GPU(Metal)/`.doc` 파싱용 `textutil` 사용 불가).

> 설치: **Docker Desktop for Mac**([다운로드](https://www.docker.com/products/docker-desktop/) 또는 `brew install --cask docker`) — Neo4j 컨테이너용.
> Ollama 는 **macOS 네이티브**([ollama.com](https://ollama.com))로 설치해 Metal GPU 를 쓴다. (설치 상세는 README "빠른 시작")

```bash
cd code
docker compose up -d                          # 1) Neo4j 만 (베이스 compose, prod.yml 안 씀)
ollama serve                                  # 2) Ollama 네이티브(Metal GPU)
conda activate neo4j-gemma-rag                # 3) 앱: conda
PYTHONPATH=. python scripts/ingest_cli.py --reset   # 적재(문서 파싱은 로컬에서만)
uvicorn app.main:app --reload --port 8008           # 질의 서버(--reload)
```

> 로컬에선 `-f docker-compose.prod.yml` 을 붙이지 말 것 — 앱·ollama 이미지까지 빌드하려다 Mac GPU에서 막힌다.

---

## 부록 — 빠른 배포 체크리스트

```
[ ] Docker + compose, NVIDIA 드라이버 + Container Toolkit (nvidia-smi, --gpus all 확인)
[ ] git clone && cd neo4j-gemma-rag
[ ] cp code/.env.example code/.env   (NEO4J_PASSWORD 설정, 모델명 일치)
[ ] (로컬 백업 전송 후) ./db_migration/restore_neo4j.sh neo4j_backup_*.tar.gz --force
[ ] cd code && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
[ ] docker exec panrye-ollama ollama pull gemma4:e2b-it-q4_K_M && (동일) bge-m3
[ ] curl localhost:8008/health → neo4j=true, ollama=true
[ ] docker compose ... logs -f app 로 로그 확인
```
