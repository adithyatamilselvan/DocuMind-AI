from typing import Any

from app.modules.extraction.models import ExtractedDocument


def build_structure(doc: ExtractedDocument) -> dict[str, Any]:
    """Deterministic outline and table inventory (no LLM): headings with levels/pages and tables."""
    outline: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for page in doc.pages:
        for b in page.blocks:
            if b.type == "heading" and len(outline) < 300:
                outline.append({"level": b.level or 3, "title": b.text, "page": page.number})
            elif b.type == "table" and len(tables) < 100:
                rows = b.rows or [r.split(" | ") for r in b.text.split("\n")]
                tables.append(
                    {"page": page.number, "rows": len(rows), "columns": max((len(r) for r in rows), default=0),
                     "preview": rows[:4]}
                )  # fmt: skip
    return {
        "page_basis": doc.page_basis, "page_count": len(doc.pages), "outline": outline, "tables": tables,
        "ocr_pages": [p.number for p in doc.pages if p.ocr],
    }  # fmt: skip
