"""Context-aware chunking.

Rules:
- A chunk never crosses a page boundary, so a citation's page number is always exact.
- Headings are tracked as a stack; every chunk records its section path and nearest heading.
- Tables become their own chunk(s) (header row repeated when a table is split).
- Chunks target ~`target_tokens` tokens with a sentence-aligned overlap within a page/section.
- Token counts are an estimate (~4 characters per token), used only for sizing and budgeting.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.extraction.models import Block, ExtractedDocument

CHARS_PER_TOKEN = 4
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


@dataclass
class ChunkDraft:
    chunk_index: int
    content: str
    page_number: int
    section_heading: str | None
    section_path: list[str]
    type: str  # paragraph | table
    token_count: int
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkingConfig:
    target_tokens: int = 400
    max_tokens: int = 600
    overlap_tokens: int = 50
    min_tokens: int = 40  # tiny trailing fragments are merged into the previous chunk if possible


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split an oversized paragraph at sentence boundaries, then at word boundaries."""
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    cur = ""
    for sent in _SENTENCE.split(text):
        while len(sent) > max_chars:  # a single enormous sentence: hard split on whitespace
            cut = sent.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(sent[:cut].strip())
            sent = sent[cut:].strip()
        if cur and len(cur) + 1 + len(sent) > max_chars:
            parts.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    return [p for p in parts if p]


def _tail_overlap(text: str, overlap_chars: int) -> str:
    """The last sentence(s) of `text` totalling at most `overlap_chars`."""
    if overlap_chars <= 0:
        return ""
    sentences = _SENTENCE.split(text)
    tail = ""
    for s in reversed(sentences):
        if len(tail) + len(s) + 1 > overlap_chars:
            break
        tail = f"{s} {tail}".strip()
    return tail


def _table_chunks(block: Block, max_chars: int) -> list[str]:
    rows = block.rows or [r.split(" | ") for r in block.text.split("\n")]
    header = " | ".join(rows[0])
    out: list[str] = []
    cur: list[str] = []
    size = 0
    for row in rows[1:] if len(rows) > 1 else rows:
        line = " | ".join(row)
        if cur and size + len(line) + 1 > max_chars:
            out.append("\n".join([header, *cur]))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        out.append("\n".join([header, *cur]) if len(rows) > 1 else "\n".join(cur))
    return out


def chunk_document(
    doc: ExtractedDocument, cfg: ChunkingConfig = ChunkingConfig()
) -> list[ChunkDraft]:
    max_chars = cfg.max_tokens * CHARS_PER_TOKEN
    # A chunk (target text + the overlap carried over from the previous chunk) must fit in max_tokens.
    target_chars = (
        max(1, min(cfg.target_tokens, cfg.max_tokens - cfg.overlap_tokens)) * CHARS_PER_TOKEN
    )
    overlap_chars = cfg.overlap_tokens * CHARS_PER_TOKEN
    chunks: list[ChunkDraft] = []
    heading_stack: list[tuple[int, str]] = []

    def path() -> list[str]:
        return [t for _, t in heading_stack]

    def emit(content: str, page: int, kind: str, meta: dict[str, Any]) -> None:
        content = content.strip()
        if not content:
            return
        p = path()
        chunks.append(
            ChunkDraft(
                chunk_index=len(chunks), content=content, page_number=page,
                section_heading=p[-1] if p else None, section_path=p, type=kind,
                token_count=estimate_tokens(content),
                content_hash=hashlib.sha256(content.encode()).hexdigest(), metadata=meta,
            )
        )  # fmt: skip

    for page in doc.pages:
        buf: list[str] = []
        buf_len = 0
        prev_tail = ""
        meta = {"ocr": page.ocr, "page_basis": doc.page_basis}

        def flush(page=page, meta=meta) -> None:
            nonlocal buf, buf_len, prev_tail
            if not buf:
                return
            body = "\n\n".join(buf)
            emit(body, page.number, "paragraph", dict(meta))
            prev_tail = _tail_overlap(body, overlap_chars)
            buf, buf_len = [], 0

        for block in page.blocks:
            if block.type == "heading":
                flush()
                prev_tail = ""  # never carry overlap across a section boundary
                level = block.level or 3
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, block.text))
                continue
            if block.type == "table":
                flush()
                prev_tail = ""
                for part in _table_chunks(block, max_chars):
                    emit(part, page.number, "table", {**meta, "table": True})
                continue
            for piece in _split_long(block.text, max_chars - overlap_chars):
                if buf and buf_len + len(piece) > target_chars:
                    flush()
                if not buf and prev_tail:
                    buf.append(prev_tail)
                    buf_len += len(prev_tail)
                    prev_tail = ""
                buf.append(piece)
                buf_len += len(piece) + 2
        flush()

    return _merge_tiny(chunks, cfg)


def _merge_tiny(chunks: list[ChunkDraft], cfg: ChunkingConfig) -> list[ChunkDraft]:
    """Merge very small paragraph chunks into the previous chunk when they share page and section."""
    out: list[ChunkDraft] = []
    for c in chunks:
        prev = out[-1] if out else None
        if (
            prev and c.type == "paragraph" and prev.type == "paragraph"
            and c.token_count < cfg.min_tokens and c.page_number == prev.page_number
            and c.section_path == prev.section_path
            and prev.token_count + c.token_count <= cfg.max_tokens
        ):  # fmt: skip
            prev.content = f"{prev.content}\n\n{c.content}"
            prev.token_count = estimate_tokens(prev.content)
            prev.content_hash = hashlib.sha256(prev.content.encode()).hexdigest()
            continue
        out.append(c)
    for i, c in enumerate(out):
        c.chunk_index = i
    return out
