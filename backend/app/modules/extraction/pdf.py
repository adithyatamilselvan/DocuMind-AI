"""PDF extraction with PyMuPDF: reading-order text blocks, heading detection from font
statistics, tables, and detection of pages that need OCR."""

import re
from collections import Counter
from collections.abc import Callable

import pymupdf

from app.modules.extraction.models import Block, ExtractedDocument, Page
from app.modules.extraction.normalize import clean_cell, clean_text
from app.modules.extraction.ocr import OCREngine
from app.modules.ingestion.errors import PermanentError

MIN_TEXT_CHARS = 25  # a page with fewer characters than this and large images is treated as scanned
_BULLET = re.compile(r"^\s*([•·▪◦\-–*]|\d{1,3}[.)])\s+")


def open_pdf(path: str) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise PermanentError("The PDF is corrupt or could not be opened") from e
    if doc.needs_pass or doc.is_encrypted:
        doc.close()
        raise PermanentError("The PDF is password protected")
    if doc.page_count == 0:
        doc.close()
        raise PermanentError("The PDF has no pages")
    return doc


def _body_font_size(doc: pymupdf.Document) -> float:
    """Most common font size weighted by characters, sampled across the document."""
    n = doc.page_count
    sample = range(n) if n <= 40 else sorted({int(i * (n - 1) / 39) for i in range(40)})
    weights: Counter[float] = Counter()
    for i in sample:
        for b in doc[i].get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for s in line["spans"]:
                    weights[round(s["size"], 1)] += len(s["text"].strip())
    return weights.most_common(1)[0][0] if weights else 11.0


def _block_to_text_and_style(block: dict) -> tuple[str, float, bool, int]:
    parts: list[str] = []
    max_size, bold_chars, total_chars = 0.0, 0, 0
    for line in block["lines"]:
        text = "".join(s["text"] for s in line["spans"])
        parts.append(text)
        for s in line["spans"]:
            n = len(s["text"].strip())
            total_chars += n
            if n:
                max_size = max(max_size, s["size"])
            if s["flags"] & 16 or "bold" in s["font"].lower():
                bold_chars += n
    return (
        "\n".join(parts),
        max_size,
        (total_chars > 0 and bold_chars / total_chars > 0.8),
        len(parts),
    )


def _heading_level(text: str, size: float, bold: bool, lines: int, body: float) -> int | None:
    if not text or len(text) > 160 or lines > 3 or _BULLET.match(text):
        return None
    ratio = size / body if body else 1.0
    if ratio >= 1.8:
        return 1
    if ratio >= 1.4:
        return 2
    if ratio >= 1.15 and not text.endswith((".", ",", ";")):
        return 3
    if bold and ratio >= 0.98 and len(text) <= 100 and not text.endswith((".", ",", ";", ":")):
        return 3
    return None


def _inside(bbox: tuple[float, float, float, float], tables: list[tuple[float, ...]]) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return any(t[0] <= cx <= t[2] and t[1] <= cy <= t[3] for t in tables)


def _extract_page(page: pymupdf.Page, body: float) -> tuple[Page, bool]:
    """Returns (page, needs_ocr)."""
    out = Page(number=page.number + 1, width=page.rect.width, height=page.rect.height)
    table_boxes: list[tuple[float, ...]] = []
    table_blocks: list[Block] = []
    try:
        for t in page.find_tables().tables:
            rows = [[clean_cell(c) for c in row] for row in t.extract() if row]
            rows = [r for r in rows if any(r)]
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                table_boxes.append(tuple(t.bbox))
                text = "\n".join(" | ".join(r) for r in rows)
                table_blocks.append(Block("table", text, bbox=list(t.bbox), rows=rows))
    except Exception:  # noqa: S110  (table detection is best-effort; text is still extracted)
        pass

    image_area = 0.0
    blocks: list[Block] = []
    for b in page.get_text("dict", sort=True)["blocks"]:
        bbox = tuple(b["bbox"])
        if b["type"] == 1:
            image_area += max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
            continue
        if _inside(bbox, table_boxes):
            continue
        raw, size, bold, n_lines = _block_to_text_and_style(b)
        text = clean_text(raw)
        if not text:
            continue
        level = _heading_level(text, size, bold, n_lines, body)
        blocks.append(Block("heading" if level else "paragraph", text, level, list(bbox)))

    out.blocks = sorted(blocks + table_blocks, key=lambda x: (round(x.bbox[1] / 4), x.bbox[0]))
    page_area = page.rect.width * page.rect.height
    chars = sum(len(b.text) for b in out.blocks)
    needs_ocr = chars < MIN_TEXT_CHARS and page_area > 0 and image_area / page_area > 0.4
    return out, needs_ocr


def extract_text_layer(
    path: str, max_pages: int, progress: Callable[[float], None] | None = None
) -> tuple[ExtractedDocument, list[int]]:
    """Extract the embedded text layer. Returns (document, 1-based page numbers needing OCR)."""
    doc = open_pdf(path)
    try:
        if doc.page_count > max_pages:
            raise PermanentError(
                f"The document has {doc.page_count} pages; the limit is {max_pages}"
            )
        body = _body_font_size(doc)
        pages: list[Page] = []
        ocr_needed: list[int] = []
        for i in range(doc.page_count):
            try:
                page, needs = _extract_page(doc[i], body)
            except Exception as e:
                raise PermanentError(f"Could not read page {i + 1} of the PDF") from e
            pages.append(page)
            if needs:
                ocr_needed.append(page.number)
            if progress and i % 10 == 0:
                progress((i + 1) / doc.page_count)
        meta = {
            k: v
            for k, v in (doc.metadata or {}).items()
            if v and k in {"title", "author", "subject", "keywords", "creationDate", "producer"}
        }
        meta["page_count"] = doc.page_count
        meta["body_font_size"] = body
        return ExtractedDocument(pages, "physical", meta), ocr_needed
    finally:
        doc.close()


def ocr_pages(
    path: str,
    result: ExtractedDocument,
    page_numbers: list[int],
    engine: OCREngine,
    max_pages: int,
    dpi: int = 200,
    progress: Callable[[float], None] | None = None,
) -> int:
    """OCR the given pages in place. Returns the number of pages recognised."""
    doc = open_pdf(path)
    done = 0
    try:
        todo = page_numbers[:max_pages]
        if len(page_numbers) > max_pages:
            result.warnings.append(
                f"OCR limited to the first {max_pages} of {len(page_numbers)} scanned pages"
            )
        for k, number in enumerate(todo):
            png = doc[number - 1].get_pixmap(dpi=dpi).tobytes("png")
            raw = engine.recognize(png)
            paragraphs = [clean_text(p) for p in re.split(r"\n\s*\n", raw)]
            page = result.pages[number - 1]
            page.blocks = [Block("paragraph", p) for p in paragraphs if p]
            page.ocr = True
            done += 1
            if progress:
                progress((k + 1) / len(todo))
        return done
    finally:
        doc.close()
