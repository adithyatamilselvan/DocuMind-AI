import re

from app.modules.extraction.models import Block, ExtractedDocument
from app.modules.extraction.normalize import clean_text
from app.modules.extraction.word import group_into_virtual_pages
from app.modules.ingestion.errors import PermanentError

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace")


def extract_text(path: str) -> ExtractedDocument:
    with open(path, "rb") as f:
        raw = decode_text(f.read())
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    blocks: list[Block] = []
    breaks: set[int] = set()
    for chunk_index, form_page in enumerate(raw.split("\f")):
        if chunk_index > 0 and blocks:
            breaks.add(len(blocks))
        for para in re.split(r"\n\s*\n", form_page):
            lines = para.strip("\n").split("\n")
            if not lines or not "".join(lines).strip():
                continue
            m = _MD_HEADING.match(lines[0]) if len(lines) == 1 else None
            if m:
                blocks.append(Block("heading", clean_text(m.group(2)), min(len(m.group(1)), 3)))
            elif len(lines) == 2 and re.fullmatch(r"[=\-]{3,}", lines[1].strip()):
                blocks.append(Block("heading", clean_text(lines[0]), 1 if "=" in lines[1] else 2))
            else:
                text = clean_text(para)
                if text:
                    blocks.append(Block("paragraph", text))
    if not blocks:
        raise PermanentError("The document contains no text")
    pages = group_into_virtual_pages(blocks, breaks)
    return ExtractedDocument(pages, "virtual", {"page_count": len(pages)})
