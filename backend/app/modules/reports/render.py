"""Render structured report content to PDF (ReportLab) and DOCX (python-docx)."""

import io
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _refs_text(refs: list[int]) -> str:
    return " " + "".join(f"[{n}]" for n in refs) if refs else ""


def _ref_line(r: dict[str, Any]) -> str:
    page = f", page {r['page']}" if r.get("page") else ""
    quote = f': "{r["quote"][:250]}"' if r.get("quote") else ""
    return f"{r['document_title']}{page}{quote}"


def to_pdf(
    title: str,
    generated_at: datetime,
    subtitle: str,
    sections: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    disclaimer: str,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title,
        author="DocuMind",
    )
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["BodyText"], fontSize=8.5, textColor=colors.grey)
    cell = ParagraphStyle("cell", parent=ss["BodyText"], fontSize=8.5, leading=10)
    flow: list[Any] = [Paragraph(escape(title), ss["Title"]), Paragraph(escape(subtitle), ss["BodyText"]),
                       Paragraph(f"Generated {generated_at:%Y-%m-%d %H:%M} UTC", small), Spacer(1, 0.4 * cm)]  # fmt: skip
    for s in sections:
        flow.append(Paragraph(escape(s["title"]), ss["Heading2"]))
        for p in s["paragraphs"]:
            flow.append(Paragraph(escape(p), ss["BodyText"]))
        if s["bullets"]:
            flow.append(ListFlowable(
                [ListItem(Paragraph(escape(b["text"]) + escape(_refs_text(b["refs"])), ss["BodyText"])) for b in s["bullets"]],
                bulletType="bullet", leftIndent=14,
            ))  # fmt: skip
        if s["table"]:
            t = s["table"]
            data = [[Paragraph(f"<b>{escape(c)}</b>", cell) for c in t["columns"]]] + [
                [Paragraph(escape(str(v)), cell) for v in row] for row in t["rows"]
            ]
            tbl = Table(data, repeatRows=1)
            tbl.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            flow.append(tbl)
        flow.append(Spacer(1, 0.2 * cm))
    if refs:
        flow.append(Paragraph("References", ss["Heading2"]))
        for r in refs:
            flow.append(Paragraph(f"[{r['n']}] {escape(_ref_line(r))}", small))
    flow += [Spacer(1, 0.4 * cm), Paragraph(escape(disclaimer), small)]
    doc.build(flow)
    return buf.getvalue()


def to_docx(
    title: str,
    generated_at: datetime,
    subtitle: str,
    sections: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    disclaimer: str,
) -> bytes:
    d = Document()
    d.core_properties.title = title
    d.core_properties.author = "DocuMind"
    d.add_heading(title, level=0)
    d.add_paragraph(subtitle)
    d.add_paragraph(f"Generated {generated_at:%Y-%m-%d %H:%M} UTC").runs[0].font.size = Pt(9)
    for s in sections:
        d.add_heading(s["title"], level=2)
        for p in s["paragraphs"]:
            d.add_paragraph(p)
        for b in s["bullets"]:
            d.add_paragraph(b["text"] + _refs_text(b["refs"]), style="List Bullet")
        if s["table"]:
            t = s["table"]
            tbl = d.add_table(rows=1, cols=len(t["columns"]))
            tbl.style = "Table Grid"
            for i, c in enumerate(t["columns"]):
                tbl.rows[0].cells[i].text = c
                tbl.rows[0].cells[i].paragraphs[0].runs[0].bold = True
            for row in t["rows"]:
                cells = tbl.add_row().cells
                for i, v in enumerate(row):
                    cells[i].text = str(v)
    if refs:
        d.add_heading("References", level=2)
        for r in refs:
            para = d.add_paragraph(f"[{r['n']}] {_ref_line(r)}")
            para.runs[0].font.size = Pt(9)
    note = d.add_paragraph(disclaimer)
    note.runs[0].font.size = Pt(8)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
