"""DOCX extraction with python-docx. DOCX has no fixed pages: virtual pages are built from
explicit page breaks, or from ~3000-character groups of blocks."""

import re

from docx import Document as load_docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.modules.extraction.models import Block, ExtractedDocument, Page
from app.modules.extraction.normalize import clean_cell, clean_text
from app.modules.ingestion.errors import PermanentError

VIRTUAL_PAGE_CHARS = 3000
_HEADING = re.compile(r"^heading\s*(\d)", re.I)


def _heading_level(p: Paragraph) -> int | None:
    name = (p.style.name if p.style is not None else "") or ""
    if name.lower() == "title":
        return 1
    m = _HEADING.match(name)
    return min(int(m.group(1)), 3) if m else None


def _has_page_break(p: Paragraph) -> bool:
    xml = p._p.xml
    return 'w:type="page"' in xml or "lastRenderedPageBreak" in xml


def group_into_virtual_pages(blocks: list[Block], breaks_before: set[int]) -> list[Page]:
    """Split a block sequence into pages at forced breaks, else every ~3000 chars."""
    pages: list[Page] = [Page(number=1)]
    size = 0
    for i, b in enumerate(blocks):
        if pages[-1].blocks and (
            i in breaks_before or size + len(b.text) > VIRTUAL_PAGE_CHARS * 1.3
        ):
            pages.append(Page(number=len(pages) + 1))
            size = 0
        pages[-1].blocks.append(b)
        size += len(b.text)
    return pages


def extract_docx(path: str) -> ExtractedDocument:
    try:
        doc = load_docx(path)
    except Exception as e:
        raise PermanentError("The DOCX file is corrupt or could not be opened") from e

    blocks: list[Block] = []
    breaks: set[int] = set()
    explicit_breaks = False
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            if _has_page_break(p) and blocks:
                breaks.add(len(blocks))
                explicit_breaks = True
            text = clean_text(p.text)
            if not text:
                continue
            level = _heading_level(p)
            blocks.append(Block("heading" if level else "paragraph", text, level))
        elif tag == "tbl":
            t = Table(child, doc)
            rows = [[clean_cell(c.text) for c in r.cells] for r in t.rows]
            # merged cells repeat; collapse consecutive duplicates in a row
            rows = [[c for i, c in enumerate(r) if i == 0 or c != r[i - 1]] for r in rows]
            rows = [r for r in rows if any(r)]
            if rows:
                blocks.append(Block("table", "\n".join(" | ".join(r) for r in rows), rows=rows))
    if not blocks:
        raise PermanentError("The document contains no text")

    pages = group_into_virtual_pages(blocks, breaks if explicit_breaks else set())
    cp = doc.core_properties
    meta = {
        k: v
        for k, v in {
            "title": cp.title, "author": cp.author, "subject": cp.subject, "keywords": cp.keywords,
            "creationDate": cp.created.isoformat() if cp.created else None,
        }.items()
        if v
    }  # fmt: skip
    meta["page_count"] = len(pages)
    return ExtractedDocument(pages, "virtual", meta)
