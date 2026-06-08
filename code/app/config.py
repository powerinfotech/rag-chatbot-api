from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
CODE_DIR = APP_DIR.parent
PROJECT_ROOT = CODE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", CODE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Neo4j (docker-compose.yml의 값과 일치해야 함) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "please_change_me"
    neo4j_database: str = "neo4j"

    # --- Ollama ---
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "gemma4:e2b-it-q4_K_M"
    llm_temperature: float = 0.2
    llm_num_ctx: int = 8192
    # 답변(출력) 토큰 상한(런어웨이 방지용 안전상한). -1이면 무제한.
    # 주의: 한국어는 토큰 효율이 낮아(1자≈2~3토큰) 너무 낮추면 답변이 중간에 잘린다(완결 답변 ≈900토큰).
    llm_num_predict: int = 1280
    request_timeout: float = 180.0

    # --- Embeddings (bge-m3 = 1024차원) ---
    embed_model: str = "bge-m3"
    embed_dim: int = 1024

    # --- Chunking / Retrieval ---
    chunk_size: int = 1200
    chunk_overlap: int = 200
    retrieval_top_k: int = 5
    graph_expand_limit: int = 10
    # 벡터 코사인 유사도 최소 점수. 이 값 미만의 청크는 '근거 없음'으로 버린다.
    # (실측 관련 질문 top: 한국어 0.85~0.88, 영어(교차언어) 0.80~0.82 / 무관 질문 top: 0.65~0.70)
    # 0.76는 한국어·영어 질문을 모두 통과시키면서 무관 질문(최고 0.70)은 차단하는 균형값.
    # 너무 높이면 정상 질문(특히 영어)도 거부, 너무 낮추면 환각이 통과하므로 도메인에 맞게 튜닝.
    retrieval_min_score: float = 0.76

    # --- CORS (쉼표로 구분; "*" 면 전체 허용. 운영에선 프론트 origin만 명시 권장) ---
    cors_allow_origins: str = "*"

    # --- Data ---
    docs_dir: str = str(PROJECT_ROOT / "data" / "판례 국문")

    @property
    def docs_path(self) -> Path:
        return Path(self.docs_dir)

    @property
    def cors_origins(self) -> list[str]:
        """CORS_ALLOW_ORIGINS 파싱: '*' 면 전체 허용, 아니면 쉼표 구분 origin 목록."""
        raw = self.cors_allow_origins.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
