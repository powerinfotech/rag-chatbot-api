"""텍스트 청킹: 한국 판례의 '구조(섹션)'를 인식해 분할 + 섹션 라벨 부착.

전략
1) 문서의 섹션 경계에서 1차 분할 (각 섹션에 라벨을 매긴다)
   - 형식 A(판례공보): 【판시사항】【판결요지】【참조조문】【주 문】【이 유】 … 같은 【…】 헤드노트
   - 형식 B(판결문/결정문): 한 줄에 단독으로 오는 '주문 / 이유 / 청구취지 …' 헤더(탭·전각공백 허용)
2) 아주 짧은 인접 섹션(머리말·판시사항·참조조문 등)은 한 청크로 합쳐 미세 청크를 막는다.
3) 각 섹션이 chunk_size보다 길면 '그 섹션 안에서만' RecursiveCharacterTextSplitter로 크기 캡
4) 구조 마커가 사실상 없는 문서는 기존처럼 전체를 RecursiveCharacterTextSplitter로 폴백

산출물은 TextChunk(text, section) — section은 출처 표기/필터용 라벨(판시사항/이유/머리말 등).
텍스트는 원문 그대로 유지(verbatim) — 잘라내기·이어붙이기만 하고 고쳐 쓰지 않는다(인용/출처 무결성).
"""

from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.types import TextChunk

_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# 형식 A: 판례공보 헤드노트 — 한 줄 안에서 닫히는 【…】 토큰(섹션 헤더).
_BRACKET_MARKER = re.compile(r"【[^】\n]{1,30}】")

# 형식 B: 판결문/결정문 — 한 줄에 단독으로 오는 섹션 헤더(글자 사이 탭/공백/전각공백 허용).
_SP = r"[ \t　]*"
_BLOCK_HEADERS = (
    "주" + _SP + "문",
    "이" + _SP + "유",
    "청" + _SP + "구" + _SP + "취" + _SP + "지",
    "신" + _SP + "청" + _SP + "취" + _SP + "지",
    "항" + _SP + "소" + _SP + "취" + _SP + "지",
    "반" + _SP + "소" + _SP + "청" + _SP + "구" + _SP + "취" + _SP + "지",
    "별" + _SP + "지",
)
_BLOCK_MARKER = re.compile(
    r"(?m)^" + _SP + r"(?:" + "|".join(_BLOCK_HEADERS) + r")" + _SP + r"$"
)

# 형식 B 헤더의 공백 제거형(라벨 매칭용)과 마커 없는 선두 섹션의 기본 라벨.
_BLOCK_LABELS = {"주문", "이유", "청구취지", "신청취지", "항소취지", "반소청구취지", "별지"}
_PREAMBLE_LABEL = "머리말"


def _recursive_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=_SEPARATORS,
    )
    return [c for c in splitter.split_text(text) if c.strip()]


def _cap_section(segment: str, chunk_size: int, overlap: int, min_chunk: int) -> list[str]:
    """긴 섹션을 크기 캡으로 자르되, 위치(처음·중간·끝)와 무관하게 미세 조각을 이웃과 병합.

    1) RecursiveCharacterTextSplitter로 1차 분할.
    2) 각 조각의 '원문 내 시작 오프셋'을 순차 탐색 → [start_i, start_{i+1}) 의
       '겹침 없는 연속 구간'으로 재구성(overlap 중복 제거).
    3) min_chunk 미만 조각을 인접 구간(앞 우선, 첫 조각은 뒤)에 흡수.

    모든 조각이 '원문 연속 슬라이스'라 verbatim이 유지되고 중복도 생기지 않는다.
    조각 위치를 못 찾으면(드묾) 1차 분할 결과를 그대로 돌려준다(안전 폴백).
    """
    pieces = _recursive_split(segment, chunk_size, overlap)
    if len(pieces) <= 1:
        return pieces

    # 2) 시작 오프셋 → 겹침 없는 연속 구간.
    starts: list[int] = []
    frm = 0
    for p in pieces:
        i = segment.find(p, frm)
        if i == -1:
            i = segment.find(p)
        if i == -1:
            return pieces  # 위치를 못 찾으면 안전 폴백
        starts.append(i)
        frm = i + 1
    bounds = sorted(set(starts)) + [len(segment)]
    segs = [segment[bounds[j] : bounds[j + 1]].strip() for j in range(len(bounds) - 1)]
    segs = [s for s in segs if s]
    if not segs:
        return pieces

    # 3) 미세 조각 흡수: 앞 조각에 붙이되 결과가 캡+여유 이내일 때.
    cap = chunk_size + min_chunk
    out: list[str] = []
    for s in segs:
        if out and len(s) < min_chunk and len(out[-1]) + 2 + len(s) <= cap:
            out[-1] = out[-1] + "\n\n" + s
        else:
            out.append(s)
    # 첫 조각이 짧으면 다음 조각 앞에 붙인다.
    if len(out) >= 2 and len(out[0]) < min_chunk and len(out[0]) + 2 + len(out[1]) <= cap:
        out = [out[0] + "\n\n" + out[1], *out[2:]]
    return out


def _label_of(section: str) -> str:
    """섹션 첫머리에서 라벨을 뽑는다. 【…】 토큰 > 단독 헤더 > '머리말' 순."""
    s = section.lstrip()
    if s.startswith("【"):
        m = _BRACKET_MARKER.match(s)
        if m:
            return re.sub(r"\s+", "", m.group(0)[1:-1])
    first_line = s.split("\n", 1)[0]
    compact = re.sub(r"\s+", "", first_line)
    if compact in _BLOCK_LABELS:
        return compact
    return _PREAMBLE_LABEL


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """섹션 마커의 '시작 위치'에서 원문을 그대로 잘라 (라벨, 원문조각) 목록을 만든다.

    마커가 하나도 없으면 [("", text)] 한 덩어리를 돌려준다(폴백 신호).
    조각들은 연속한 원문 슬라이스라, 인접 조각을 이어붙여도 원문 연속성이 유지된다.
    """
    cuts = {m.start() for m in _BRACKET_MARKER.finditer(text)}
    cuts |= {m.start() for m in _BLOCK_MARKER.finditer(text)}
    if not cuts:
        return [("", text)]
    bounds = sorted({0, *cuts, len(text)})
    out: list[tuple[str, str]] = []
    for i in range(len(bounds) - 1):
        seg = text[bounds[i] : bounds[i + 1]]
        if not seg.strip():
            continue
        out.append((_label_of(seg), seg))
    return out


def _join_labels(labels: list[str]) -> str:
    """합쳐진 청크의 섹션 라벨: 중복 제거 후 '·'로 연결(4개 이상이면 3개+…)."""
    uniq: list[str] = []
    for x in labels:
        if x and x not in uniq:
            uniq.append(x)
    if not uniq:
        return ""
    if len(uniq) > 3:
        return "·".join(uniq[:3]) + "·…"
    return "·".join(uniq)


def _coalesce_micro(chunks: list[TextChunk], min_chunk: int, cap: int) -> list[TextChunk]:
    """min_chunk 미만 청크를 인접 청크에 흡수(앞 우선, 첫 청크는 뒤) — 섹션 경계 포함.

    모든 청크는 원문을 순서대로 타일링한 연속 슬라이스라, 인접 청크끼리 이어붙여도
    원문 연속성(verbatim)이 유지된다. 캡(cap)을 넘기면 병합하지 않는다(드묾).
    섹션 라벨은 양쪽을 합쳐 중복 제거(_join_labels 규칙) 후 다시 매긴다.
    """
    if len(chunks) <= 1:
        return chunks

    def _merge(a: TextChunk, b: TextChunk) -> TextChunk:
        labels = [x for x in (a.section.split("·") + b.section.split("·")) if x and x != "…"]
        return TextChunk(text=a.text + "\n\n" + b.text, section=_join_labels(labels))

    out: list[TextChunk] = []
    for c in chunks:
        if out and len(c.text) < min_chunk and len(out[-1].text) + 2 + len(c.text) <= cap:
            out[-1] = _merge(out[-1], c)
        else:
            out.append(c)
    # 첫 청크가 짧으면 다음 청크 앞에 붙인다.
    if len(out) >= 2 and len(out[0].text) < min_chunk and len(out[0].text) + 2 + len(out[1].text) <= cap:
        out = [_merge(out[0], out[1]), *out[2:]]
    return out


def chunk_text(
    text: str,
    *,
    chunk_size: int = settings.chunk_size,
    overlap: int = settings.chunk_overlap,
    min_section: int | None = None,
) -> list[TextChunk]:
    if not text or not text.strip():
        return []

    sections = _split_into_sections(text)
    # 구조 마커가 사실상 없으면(섹션 1개) 기존 크기 기반 분할로 폴백(라벨 없음).
    if len(sections) <= 1:
        return [TextChunk(text=c) for c in _recursive_split(text, chunk_size, overlap)]

    # 이 길이에 못 미치는 인접 섹션은 모아서 한 청크로(미세 청크 방지).
    if min_section is None:
        min_section = max(150, chunk_size // 6)

    chunks: list[TextChunk] = []
    pending: list[str] = []  # flush 대기 중인(이미 strip된) 본문 조각들
    pending_labels: list[str] = []

    def pending_len() -> int:
        # "\n\n".join(pending) 의 길이.
        return sum(len(b) for b in pending) + 2 * max(0, len(pending) - 1)

    def flush() -> None:
        if pending:
            body = "\n\n".join(pending).strip()
            if body:
                chunks.append(TextChunk(text=body, section=_join_labels(pending_labels)))
        pending.clear()
        pending_labels.clear()

    for label, segment in sections:
        body = segment.strip()
        if not body:
            continue
        if len(body) > chunk_size:
            # 큰 섹션(주로 '이유'): 그 섹션 내부에서만 크기 캡(+전 위치 미세 조각 흡수).
            pieces = _cap_section(segment, chunk_size, overlap, min_section)
            if not pieces:
                continue
            # 앞에 모아둔 짧은 섹션이 첫 조각에 무리 없이 붙으면 함께 묶는다.
            if pending and pending_len() + 2 + len(pieces[0]) <= chunk_size:
                pending.append(pieces[0])
                pending_labels.append(label)
                flush()
                rest = pieces[1:]
            else:
                flush()
                rest = pieces
            chunks.extend(TextChunk(text=p, section=label) for p in rest)
        else:
            # 짧은/보통 섹션: 버퍼에 모아 두고 임계 길이를 넘으면 flush.
            pending.append(body)
            pending_labels.append(label)
            if pending_len() >= min_section:
                flush()

    flush()
    # 마지막 안전망: 섹션 경계에서 생긴 미세 청크(예: '청구취지: 주문과 같다')를 이웃에 흡수.
    chunks = _coalesce_micro(chunks, min_section, chunk_size + min_section)
    return [c for c in chunks if c.text.strip()]
