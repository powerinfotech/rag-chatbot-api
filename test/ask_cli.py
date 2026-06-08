"""RAG 검색/게이팅/답변을 직접 눈으로 확인하는 테스트 CLI.

프롬프트나 소스 설정을 바꾸지 않고, 주어진 질문에 대해 다음을 한눈에 보여준다.
  [1] 벡터 검색 원점수와 임계값 통과/차단
  [2] 게이팅(근거 유무) 판정 — 근거 없으면 LLM 호출 없이 거부
  [3] 그래프 확장(공유 엔티티 기반) 결과와 엔티티
  [4] 최종 컨텍스트 후보 청크 수
  [5] 최종 답변과 출처

--min-score / --top-k 로 임계값을 즉석에서 실험할 수 있고,
대화형 모드에서는 :score / :topk 명령으로 실행 중에 바꿔볼 수 있다.

repo 루트에서 실행(conda 환경 활성화 필요: conda activate neo4j-gemma-rag).
실행(원샷):   python test/ask_cli.py "중재판정 취소 사유는?"
실행(대화형): python test/ask_cli.py
검색만(LLM 생략): python test/ask_cli.py "질문" --no-answer --show-text
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 이 스크립트는 repo 루트의 test/ 에 있으므로, 패키지(app)가 들어있는 code/ 를 경로에 추가.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

from app.config import settings  # noqa: E402
from app.db.neo4j_client import verify_connectivity  # noqa: E402

# 진단 출력만 보이도록 라이브러리 로그는 억제.
logging.getLogger("neo4j").setLevel(logging.ERROR)

_BAR = "=" * 64
_SUB = "-" * 64


def _is_korean(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def _dedup(chunks: list) -> list:
    """hybrid_retrieve 와 동일하게 chunk_id 기준 중복 제거(앞선 항목 우선)."""
    seen: set[str] = set()
    out = []
    for c in chunks:
        if c.chunk_id in seen:
            continue
        seen.add(c.chunk_id)
        out.append(c)
    return out


def diagnose(
    question: str, *, top_k: int, min_score: float, show_text: bool, with_answer: bool
) -> None:
    # 임계값 override 를 전체 파이프라인(answer_question 포함)에 일관 반영.
    settings.retrieval_min_score = min_score

    from app.retrieval.graph import entities_in_chunks, graph_expand
    from app.retrieval.vector import vector_search

    print(f"\n{_BAR}")
    print(f"질문: {question}")
    lang = "한국어" if _is_korean(question) else "영어/기타"
    print(f"min_score={min_score:.2f}  top_k={top_k}  질문언어={lang}")
    print(_BAR)

    # [1] 벡터 검색 원점수 — min_score=0 으로 전부 가져와 통과/차단을 직접 표시.
    raw = vector_search(question, top_k, min_score=0.0)
    print("\n[1] 벡터 검색 (원점수, 게이팅 전)")
    if not raw:
        print("  (결과 없음 — 색인이 비었거나 임베딩 호출 실패)")
    for i, c in enumerate(raw, start=1):
        mark = "통과" if c.score >= min_score else "차단"
        idx = "" if c.chunk_index is None else f" chunk#{c.chunk_index}"
        sec = f" · {c.section}" if c.section else ""
        print(f"  #{i}  score={c.score:.4f}  [{mark}]  {c.filename}{idx}{sec}")
        if show_text:
            snippet = " ".join(c.text.split())[:120]
            print(f"        {snippet}…")

    passing = [c for c in raw if c.score >= min_score]
    print(f"  → 통과 {len(passing)}개 / 조회 {len(raw)}개")

    # [2] 게이팅
    print("\n[2] 게이팅 (근거 유무)")
    if not passing:
        from app.core.prompts import refusal_message_for

        print("  근거 없음 → LLM 호출 없이 거부. 그래프 확장도 생략.")
        print(f"  예상 거부 답변: {refusal_message_for(question)}")
        return
    print(f"  근거 있음(통과 {len(passing)}개) → 컨텍스트 구성 진행")
    seeds = [c.chunk_id for c in passing]

    # [3] 그래프 확장
    expanded = graph_expand(seeds)
    entities = entities_in_chunks(seeds)
    print("\n[3] 그래프 확장 (공유 엔티티 기반)")
    if not expanded:
        print("  확장된 인접 청크 없음")
    for c in expanded:
        idx = "" if c.chunk_index is None else f" chunk#{c.chunk_index}"
        sec = f" · {c.section}" if c.section else ""
        print(f"  + 공유엔티티={int(c.score)}  {c.filename}{idx}{sec}")
    if entities:
        shown = ", ".join(entities[:15])
        more = f" 외 {len(entities) - 15}개" if len(entities) > 15 else ""
        print(f"  엔티티({len(entities)}): {shown}{more}")

    combined = _dedup([*passing, *expanded])
    print(
        f"\n[4] 최종 컨텍스트 후보: {len(combined)}개 청크 "
        f"(벡터 {len(passing)} + 그래프 {len(expanded)}, 중복 제거)"
    )

    # [5] 답변
    if not with_answer:
        print("\n[5] 답변: 생략(--no-answer). 검색/게이팅만 확인했습니다.")
        return

    from app.agents.graph import answer_question

    print("\n[5] 답변 생성 중… (Ollama LLM 호출)")
    result = answer_question(question, top_k)
    print(_SUB)
    print(result.answer)
    print(_SUB)
    if result.sources:
        print("[출처]")
        for s in result.sources:
            sec = f", {s.section}" if s.section else ""
            print(f"  - {s.filename}  ({s.chunk_id}{sec}, score={s.score:.4f})")
    print(f"(검색된 청크 {result.retrieved}개)")


def _print_help() -> None:
    print(
        "\n명령:\n"
        "  질문을 입력하면 검색/게이팅/답변을 보여줍니다.\n"
        "  :score <float>  임계값 변경 (예: :score 0.80)\n"
        "  :topk <int>     top_k 변경 (예: :topk 8)\n"
        "  :text           청크 본문 미리보기 토글\n"
        "  :answer         답변 생성(LLM) on/off 토글\n"
        "  :help           이 도움말\n"
        "  :q / 빈 줄      종료"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RAG 검색/게이팅/답변을 직접 테스트 (프롬프트·소스 변경 없음)",
    )
    parser.add_argument("question", nargs="?", help="질문 (생략 시 대화형 모드)")
    parser.add_argument(
        "--min-score",
        type=float,
        default=settings.retrieval_min_score,
        help=f"임계값 override (기본 {settings.retrieval_min_score})",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=settings.retrieval_top_k,
        help=f"벡터 top_k (기본 {settings.retrieval_top_k})",
    )
    parser.add_argument("--show-text", action="store_true", help="청크 본문 미리보기")
    parser.add_argument(
        "--no-answer", action="store_true", help="LLM 답변 생략(검색/게이팅만)"
    )
    args = parser.parse_args()

    if not verify_connectivity():
        print(
            "Neo4j에 연결할 수 없습니다. Docker로 Neo4j를 먼저 실행하세요.",
            file=sys.stderr,
        )
        return 1

    opts = {
        "top_k": args.top_k,
        "min_score": args.min_score,
        "show_text": args.show_text,
        "with_answer": not args.no_answer,
    }

    # 원샷 모드
    if args.question:
        diagnose(args.question, **opts)
        return 0

    # 대화형 모드
    print("RAG 테스트 콘솔 (프롬프트/소스 변경 없음).")
    _print_help()
    while True:
        prompt = (
            f"\n[min_score={opts['min_score']:.2f} top_k={opts['top_k']} "
            f"text={'on' if opts['show_text'] else 'off'} "
            f"answer={'on' if opts['with_answer'] else 'off'}] 질문> "
        )
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line or line in (":q", ":quit", ":exit"):
            break
        if line == ":help":
            _print_help()
            continue
        if line == ":text":
            opts["show_text"] = not opts["show_text"]
            continue
        if line == ":answer":
            opts["with_answer"] = not opts["with_answer"]
            continue
        if line.startswith(":score"):
            try:
                opts["min_score"] = float(line.split()[1])
            except (IndexError, ValueError):
                print("사용법: :score 0.80")
            continue
        if line.startswith(":topk"):
            try:
                opts["top_k"] = int(line.split()[1])
            except (IndexError, ValueError):
                print("사용법: :topk 8")
            continue

        diagnose(line, **opts)

    print("종료합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
