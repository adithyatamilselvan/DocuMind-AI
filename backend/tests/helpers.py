"""Builders for real test documents (PDF, scanned PDF, DOCX, TXT) generated at test time."""

import io

import pymupdf
from docx import Document

LOREM = (
    "The quarterly revenue grew by twelve percent compared with the previous year, driven mainly "
    "by strong demand in the European market and by the successful launch of the new product line. "
)


def make_pdf(pages: list[dict], encrypt: str | None = None) -> bytes:
    """pages: [{"heading": str, "body": str, "header": str, "footer": str, "table": [[...]]}]"""
    doc = pymupdf.open()
    for spec in pages:
        page = doc.new_page()
        y = 90
        if spec.get("header"):
            page.insert_text((72, 40), spec["header"], fontsize=9)
        if spec.get("footer"):
            page.insert_text((72, 810), spec["footer"], fontsize=9)
        if spec.get("heading"):
            page.insert_text((72, y), spec["heading"], fontsize=22)
            y += 30
        if spec.get("body"):
            page.insert_textbox(pymupdf.Rect(72, y, 520, y + 200), spec["body"], fontsize=11)
            y += 210
        if spec.get("table"):
            rows = spec["table"]
            cw, rh = 140, 24
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    rect = pymupdf.Rect(
                        72 + c * cw, y + r * rh, 72 + (c + 1) * cw, y + (r + 1) * rh
                    )
                    page.draw_rect(rect, color=(0, 0, 0), width=0.8)
                    page.insert_text((rect.x0 + 4, rect.y0 + 16), cell, fontsize=10)
    kwargs = {}
    if encrypt:
        kwargs = {
            "encryption": pymupdf.PDF_ENCRYPT_AES_256,
            "user_pw": encrypt,
            "owner_pw": encrypt,
        }
    return doc.tobytes(**kwargs)


def make_scanned_pdf(text_lines: list[str], text_pages: list[dict] | None = None) -> bytes:
    """A PDF whose first page is only an image (no text layer); optional real-text pages follow."""
    src = pymupdf.open()
    sp = src.new_page()
    for i, line in enumerate(text_lines):
        sp.insert_text((72, 100 + i * 40), line, fontsize=26)
    pix = sp.get_pixmap(dpi=110, colorspace=pymupdf.csGRAY)
    out = pymupdf.open()
    page = out.new_page()
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    for spec in text_pages or []:
        p = out.new_page()
        p.insert_textbox(pymupdf.Rect(72, 90, 520, 400), spec["body"], fontsize=11)
    return out.tobytes(deflate=True, garbage=3)


def make_docx(
    paragraphs: list[tuple[str, str]],
    table: list[list[str]] | None = None,
    page_break_after: int | None = None,
) -> bytes:
    """paragraphs: [(style, text)] where style is 'Heading 1', 'Normal', ..."""
    d = Document()
    for i, (style, text) in enumerate(paragraphs):
        if style.startswith("Heading"):
            d.add_heading(text, level=int(style.split()[-1]))
        else:
            d.add_paragraph(text)
        if page_break_after is not None and i == page_break_after:
            d.add_page_break()
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                t.cell(r, c).text = cell
    d.core_properties.title = "Test Title"
    d.core_properties.author = "Tester"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class FakeOCR:
    def __init__(
        self,
        text: str = "Scanned page text recognised by OCR.\n\nSecond paragraph.",
        ok: bool = True,
    ):
        self.text, self.ok, self.calls = text, ok, 0

    def available(self) -> bool:
        return self.ok

    def recognize(self, png_bytes: bytes) -> str:
        assert png_bytes[:4] == b"\x89PNG"  # a real rendered page image is passed in
        self.calls += 1
        return self.text
