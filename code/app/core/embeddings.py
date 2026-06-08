from __future__ import annotations

from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from app.config import settings


@lru_cache
def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=settings.embed_model,
        base_url=settings.ollama_base_url,
    )


def embed_query(text: str) -> list[float]:
    return get_embeddings().embed_query(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return get_embeddings().embed_documents(texts)
