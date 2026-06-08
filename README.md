# neo4j-gemma-rag

한국 법원 **판례(case law)** 전문 Q&A 챗봇.
LangGraph · Neo4j · Gemma4(Ollama) · FastAPI 기반의 **하이브리드 RAG**로,
법률 도구 특성상 **할루시네이션을 억제**(근거 없으면 "모른다")하도록 설계했다.

---

## 주요 특징

- **할루시네이션 방지** — 벡터 유사도 임계값으로 검색을 게이팅(근거 없으면 LLM 호출 없이 거부) + 프롬프트 제약. "참고 판례에 있는 내용만" 답한다.
- **하이브리드 검색** — 벡터 검색(코사인)으로 관련 청크를 찾고, 그래프 확장(공유 엔티티)으로 인접 근거를 보강.
- **한국어·영어 모두 지원** — `bge-m3` 교차언어 임베딩. 질문한 언어로 답하고, 법률 고유명사는 한국어 원문을 함께 표기.
- **출처 표기** — 답변 근거가 된 판례(파일명/사건번호)를 함께 반환.
- **Neo4j 단일 저장소** — 벡터 인덱스 + 그래프를 한 DB에서 운용.

---

## 아키텍처

```
            ┌─────────────────────────── FastAPI (app.main:app, :8008) ──────────────────────────┐
            │                                                                                     │
  질문 ──▶   │  LangGraph:  retrieve ──▶ build_context ──▶ generate                                │ ──▶ 답변 + 출처
            │                 │              │               │                                    │
            └─────────────────┼──────────────┼───────────────┼────────────────────────────────────┘
                              │              │               │
                   ┌──────────▼───┐   (게이팅: 근거    ┌──────▼────────┐
                   │   Neo4j      │    없으면 즉시     │   Ollama      │
                   │ :7687/:7474  │    거부)         │   :11434      │
                   │  벡터+그래프    │                 │gemma4 / bge-m3│
                   └──────────────┘                 └───────────────┘
```

**리트리벌 흐름** (`app/retrieval/hybrid.py`)
1. `vector_search` — `bge-m3`로 질문을 임베딩, `chunk_embedding_index`에서 코사인 검색.
   유사도가 `retrieval_min_score`(기본 0.76) 미만인 청크는 **버린다.**
2. 통과한 청크가 하나도 없으면 → **그래프 확장도 생략하고 빈 결과** → 답변 노드에서 거부 메시지 반환.
3. 통과한 청크가 있으면 → `graph_expand`로 공유 엔티티(`MENTIONS`)를 통해 인접 청크를 보강.
4. `build_context`에서 doc별 대표 출처를 고르고(벡터 코사인 우선), 컨텍스트를 구성해 LLM에 전달.

**Neo4j 그래프 스키마** (`app/schema.py`)
```
(:Document)-[:HAS_CHUNK]->(:Chunk)-[:NEXT_CHUNK]->(:Chunk)
                              └────[:MENTIONS]──▶(:Entity)-[:RELATED_TO {type}]->(:Entity)
인덱스:  chunk_embedding_index (vector, cosine, 1024d) · chunk_fulltext_index (fulltext)
```

---

## 디렉터리 구조

```
neo4j-gemma-rag/
├── code/                       # Python 프로젝트 루트
│   ├── app/
│   │   ├── main.py             # FastAPI 진입점 (+ lifespan: 스키마 초기화)
│   │   ├── config.py           # 설정(pydantic-settings, .env 로딩)
│   │   ├── schema.py           # Neo4j 노드/관계/인덱스 계약
│   │   ├── types.py            # 레이어 공용 데이터 계약
│   │   ├── agents/             # LangGraph (graph·nodes·state)
│   │   ├── api/                # FastAPI routes·schemas
│   │   ├── core/               # llm·embeddings·prompts
│   │   ├── db/                 # neo4j_client
│   │   ├── ingestion/          # loaders·chunking·entities·pipeline
│   │   └── retrieval/          # vector·graph·hybrid
│   ├── scripts/                # ingest_cli.py (적재 CLI)
│   ├── Dockerfile              # 질의 전용 앱 이미지
│   ├── requirements.txt
│   ├── docker-compose.yml      # Neo4j 5.26 (+APOC) — 로컬·서버 공통
│   ├── docker-compose.prod.yml # 서버용 오버레이: app + ollama(GPU)
│   ├── DEPLOY.md               # 서버 배포 가이드 (Docker)
│   └── .env.example
├── db_migration/               # backup/restore_neo4j.sh (Neo4j 볼륨 백업·복원, code 와 무관)
├── data/판례 국문/             # 원문 .doc 코퍼스
├── test/ask_cli.py             # 검색·게이팅·답변 테스트 CLI
└── README.md
```

---

## 빠른 시작 (로컬 개발)

### 1) 사전 요구사항 (macOS)
- **Python 3.11** (conda 권장)
- **Docker Desktop for Mac** — Neo4j 컨테이너용. [공식 다운로드](https://www.docker.com/products/docker-desktop/) 또는 `brew install --cask docker` → 실행 후 `docker compose version` 으로 확인
- **[Ollama](https://ollama.com)** — macOS 네이티브 설치(Metal GPU). [다운로드](https://ollama.com) 또는 `brew install ollama`

```bash
# Ollama 모델 받기 (Ollama 설치 후)
ollama pull gemma4:e2b-it-q4_K_M     # LLM
ollama pull bge-m3                   # 임베딩(1024d)
```

### 2) 환경 + 의존성
```bash
conda create -n neo4j-gemma-rag python=3.11 -y && conda activate neo4j-gemma-rag
pip install -r code/requirements.txt
cp code/.env.example code/.env       # NEO4J_PASSWORD 를 compose 비밀번호와 일치
```

### 3) Neo4j 기동
```bash
cd code && docker compose up -d && cd ..   # 볼륨 code_neo4j_data
```

### 4) 판례 적재(인제스션)
```bash
cd code && PYTHONPATH=. python scripts/ingest_cli.py --reset && cd ..
```

### 5) 서버 실행
```bash
cd code && PYTHONPATH=. uvicorn app.main:app --reload --port 8008
# http://localhost:8008/docs
```

---

## 사용법

### API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET`  | `/health` | Neo4j·Ollama 연결 및 모델명 확인 |
| `POST` | `/chat` | 질문 → 답변 + 출처 |
| `GET`  | `/docs` | Swagger UI |

> 적재(ingest)는 API가 아니라 **로컬 `scripts/ingest_cli.py`** 로만 한다(서버는 질의 전용).
> `.doc` 파싱이 macOS `textutil` 에 의존하고, 인증 없는 적재/초기화 엔드포인트는 보안상 두지 않는다.

```bash
curl -s -X POST localhost:8008/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"중재판정 취소 사유는?"}' | python3 -m json.tool
```
응답: `{ "answer": "...", "sources": [{filename, chunk_id, section, score}], "retrieved": N }`

### 테스트 CLI

검색 점수·게이팅 통과/차단·그래프 확장·최종 답변을 한눈에 확인 (프롬프트/소스 변경 없음):
```bash
python test/ask_cli.py "중재판정 취소 사유는?"        # 원샷
python test/ask_cli.py                                # 대화형
python test/ask_cli.py "질문" --no-answer --show-text # 검색/게이팅만
# 임계값 실험:  --min-score 0.80 / 대화형에서 :score 0.80
```

---

## 할루시네이션 방지가 동작하는 방식

| 상황 | 동작 |
|------|------|
| 관련 판례 있음 (유사도 ≥ 0.76) | 통과 청크로 컨텍스트 구성 → LLM이 근거 기반 답변 |
| 무관한 질문 (유사도 < 0.76) | **모든 청크 차단 → LLM 호출 없이 거부 메시지** |
| 근거가 일부만 존재 | 확인된 부분만 답하고 나머지는 "확인되지 않음" 명시 |

거부 메시지는 질문 언어에 맞춰 출력된다(한국어/영어).

---

## 주요 설정 (`code/.env`)

| 키 | 기본값 | 설명 |
|----|--------|------|
| `NEO4J_PASSWORD` | `please_change_me` | **docker-compose의 `NEO4J_AUTH`와 일치 필수** |
| `LLM_MODEL` | `gemma4:e2b-it-q4_K_M` | Ollama LLM |
| `EMBED_MODEL` / `EMBED_DIM` | `bge-m3` / `1024` | 임베딩 모델/차원 |
| `RETRIEVAL_TOP_K` | `5` | 벡터 검색 상위 K |
| `RETRIEVAL_MIN_SCORE` | `0.76` | 게이팅 임계값(코사인). 무관 질문 차단 균형값 |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1200` / `200` | 청킹 |
| `GRAPH_EXPAND_LIMIT` | `10` | 그래프 확장 최대 청크 |

> `RETRIEVAL_MIN_SCORE`: 실측상 관련 질문(한국어 0.85~0.88, 영어 0.80~0.82) vs 무관 질문(≤0.70).
> 너무 높이면 정상 질문(특히 영어)도 거부, 너무 낮추면 환각이 통과 — 도메인에 맞게 튜닝.

---

## 데이터 관리

- **적재(로컬 전용)**: `scripts/ingest_cli.py` (`--reset` 이면 기존 그래프 초기화 후 적재). 서버는 적재 없이 볼륨 복원으로 채움.
- **백업/복원**: 서버 재적재 없이 Docker 볼륨을 통째로 이전
  ```bash
  ./db_migration/backup_neo4j.sh                       # → neo4j_backup_<날짜>.tar.gz
  ./db_migration/restore_neo4j.sh neo4j_backup_*.tar.gz   # 서버에서 복원
  ```

---

## 배포

서버에서 **Docker로 Neo4j·Ollama(GPU)·앱 기동 + 로그 회전/실시간 확인**까지의 전체 절차는
**[`code/DEPLOY.md`](code/DEPLOY.md)** 참고.

```bash
cd code   # compose 는 code/ 에서 (프로젝트명 code → 볼륨 code_neo4j_data)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build   # neo4j + ollama(GPU) + app
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f app     # 실시간 로그
```

---

## 기술 스택

LangGraph · LangChain · Neo4j 5.26(+APOC) · Ollama(gemma4 / bge-m3) · FastAPI · uvicorn · pydantic-settings · Python 3.11
