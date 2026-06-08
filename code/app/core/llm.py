from __future__ import annotations

from functools import lru_cache

from langchain_ollama import ChatOllama

from app.config import settings


@lru_cache
def get_llm() -> ChatOllama:
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        temperature=settings.llm_temperature,
        num_ctx=settings.llm_num_ctx,
        num_predict=settings.llm_num_predict,   # 출력 토큰 상한(런어웨이 답변 방지 → 디코드 지연 감소)
    )


def generate(prompt: str, system: str | None = None) -> str:
    messages: list[tuple[str, str]] = []
    if system:
        messages.append(("system", system))
    messages.append(("human", prompt))
    return get_llm().invoke(messages).content
