import json
import shutil

import pytest
from bson import ObjectId

from app.modules.documents.states import DocumentStatus as S
from app.modules.extraction import pdf as pdfx
from app.modules.extraction import service as ex
from app.modules.extraction import text as textx
from app.modules.extraction import word
from app.modules.extraction.normalize import clean_text
from app.modules.extraction.ocr import TesseractOCR
from app.modules.ingestion import orchestrator as o
from app.modules.ingestion import stages
from app.modules.ingestion.errors import PermanentError

from .conftest import enable_ai, first_workspace, register
from .helpers import LOREM, FakeOCR, make_docx, make_pdf, make_scanned_pdf


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# ---------- normalization ----------


def test_clean_text():
    assert clean_text("exam-\nple of ﬁnancial ﬂow") == "example of financial flow"
    assert clean_text("a­b\x00c   d e\nf") == "abc d e f"
    assert clean_text("  \n ") == ""


# ---------- PDF ----------


def test_pdf_headings_paragraphs_and_reading_order(tmp_path):
    path = write(tmp_path, "a.pdf", make_pdf([
        {"heading": "Annual Report", "body": LOREM * 3},
        {"heading": "Methodology", "body": LOREM * 2},
    ]))  # fmt: skip
    doc, ocr = pdfx.extract_text_layer(path, 100)
    assert ocr == [] and doc.page_basis == "physical" and len(doc.pages) == 2
    p1 = doc.pages[0].blocks
    assert p1[0].type == "heading" and p1[0].text == "Annual Report" and p1[0].level in (1, 2)
    assert (
        p1[1].type == "paragraph" and "quarterly revenue" in p1[1].text and "\n" not in p1[1].text
    )
    assert doc.pages[1].blocks[0].text == "Methodology"
    assert doc.pages[0].number == 1 and doc.pages[1].number == 2
    assert all(b.bbox for p in doc.pages for b in p.blocks)


def test_pdf_table_extracted_as_structured_block(tmp_path):
    table = [["Region", "Revenue", "Growth"], ["EMEA", "120", "12%"], ["APAC", "80", "9%"]]
    path = write(
        tmp_path, "t.pdf", make_pdf([{"heading": "Results", "body": LOREM, "table": table}])
    )
    doc, _ = pdfx.extract_text_layer(path, 100)
    tables = [b for b in doc.pages[0].blocks if b.type == "table"]
    assert len(tables) == 1 and tables[0].rows[1] == ["EMEA", "120", "12%"]
    assert "EMEA | 120 | 12%" in tables[0].text
    # table text must not also appear as paragraph text
    assert not any("EMEA" in b.text for b in doc.pages[0].blocks if b.type != "table")


def test_running_headers_footers_removed(tmp_path):
    pages = [
        {
            "header": "ACME Confidential",
            "footer": f"Page {i + 1}",
            "heading": f"Chapter {i + 1}",
            "body": LOREM * 2,
        }
        for i in range(6)
    ]
    doc, _ = pdfx.extract_text_layer(write(tmp_path, "h.pdf", make_pdf(pages)), 100)
    ex.finalize(doc)
    all_text = " ".join(p.text for p in doc.pages)
    assert "ACME Confidential" not in all_text and "Page 3" not in all_text
    assert "Chapter 3" in all_text and doc.metadata["removed_header_footer_blocks"] >= 12


def test_scanned_page_detected_and_ocr_applied(tmp_path):
    path = write(tmp_path, "s.pdf", make_scanned_pdf(["INVOICE 2024"], [{"body": LOREM}]))
    doc, ocr_pages = pdfx.extract_text_layer(path, 100)
    assert ocr_pages == [1] and doc.pages[0].blocks == []
    engine = FakeOCR()
    n = pdfx.ocr_pages(path, doc, ocr_pages, engine, max_pages=10)
    assert n == 1 and engine.calls == 1 and doc.pages[0].ocr is True
    assert [b.text for b in doc.pages[0].blocks] == [
        "Scanned page text recognised by OCR.",
        "Second paragraph.",
    ]
    assert doc.pages[1].ocr is False  # the real-text page is untouched


def test_ocr_page_cap_adds_warning(tmp_path):
    path = write(tmp_path, "s.pdf", make_scanned_pdf(["X"]))
    doc, _ = pdfx.extract_text_layer(path, 100)
    doc.pages.append(doc.pages[0].__class__(number=2))
    n = pdfx.ocr_pages(path, doc, [1], FakeOCR(), max_pages=0)
    assert n == 0 and "OCR limited" in doc.warnings[0]


def test_encrypted_corrupt_and_oversized_pdfs(tmp_path):
    with pytest.raises(PermanentError, match="password protected"):
        pdfx.extract_text_layer(
            write(tmp_path, "e.pdf", make_pdf([{"body": LOREM}], encrypt="s3cret")), 100
        )
    with pytest.raises(PermanentError, match="corrupt"):
        pdfx.extract_text_layer(write(tmp_path, "c.pdf", b"%PDF-1.4\nthis is not a pdf"), 100)
    with pytest.raises(PermanentError, match="limit is 2"):
        pdfx.extract_text_layer(write(tmp_path, "big.pdf", make_pdf([{"body": LOREM}] * 3)), 2)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract binary not installed")
def test_real_tesseract_reads_a_scanned_page(tmp_path):
    path = write(tmp_path, "s.pdf", make_scanned_pdf(["INVOICE 2024 TOTAL"]))
    doc, pages = pdfx.extract_text_layer(path, 10)
    pdfx.ocr_pages(path, doc, pages, TesseractOCR(), max_pages=5)
    assert "INVOICE" in doc.pages[0].text.upper()


def test_tesseract_missing_is_reported():
    assert TesseractOCR(cmd="definitely-not-installed-tesseract").available() is False


# ---------- DOCX / TXT ----------


def test_docx_structure_tables_and_virtual_pages(tmp_path):
    data = make_docx(
        [("Heading 1", "Overview"), ("Normal", LOREM), ("Heading 2", "Details"), ("Normal", LOREM * 2)],
        table=[["Name", "Score"], ["A", "1"]], page_break_after=1,
    )  # fmt: skip
    doc = word.extract_docx(write(tmp_path, "a.docx", data))
    assert doc.page_basis == "virtual" and len(doc.pages) == 2  # explicit page break honoured
    assert doc.pages[0].blocks[0].type == "heading" and doc.pages[0].blocks[0].level == 1
    assert doc.pages[1].blocks[0].text == "Details" and doc.pages[1].blocks[0].level == 2
    tables = [b for p in doc.pages for b in p.blocks if b.type == "table"]
    assert tables[0].rows == [["Name", "Score"], ["A", "1"]]
    assert doc.metadata["title"] == "Test Title" and doc.metadata["author"] == "Tester"


def test_docx_without_breaks_uses_virtual_pages_by_size(tmp_path):
    data = make_docx([("Normal", LOREM * 3)] * 30)
    doc = word.extract_docx(write(tmp_path, "long.docx", data))
    assert len(doc.pages) > 3 and all(len(p.text) < 5000 for p in doc.pages)


def test_empty_docx_and_garbage_docx(tmp_path):
    with pytest.raises(PermanentError, match="no text"):
        word.extract_docx(write(tmp_path, "e.docx", make_docx([])))
    with pytest.raises(PermanentError, match="corrupt"):
        word.extract_docx(write(tmp_path, "g.docx", b"not a zip at all"))


def test_text_decoding_and_structure(tmp_path):
    md = "# Title\n\nFirst paragraph\nwrapped here.\n\nSecond one.\fAfter form feed.\n\nUnderlined\n=========\n\nbody"
    doc = textx.extract_text(write(tmp_path, "a.txt", md.encode()))
    texts = [(b.type, b.level, b.text) for p in doc.pages for b in p.blocks]
    assert ("heading", 1, "Title") in texts and (
        "paragraph",
        None,
        "First paragraph wrapped here.",
    ) in texts
    assert ("heading", 1, "Underlined") in texts and len(doc.pages) == 2
    assert textx.decode_text("héllo wörld".encode("utf-16")) == "héllo wörld"
    assert textx.decode_text("café".encode("cp1252")) == "café"
    assert textx.decode_text(b"\xef\xbb\xbfhello") == "hello"
    with pytest.raises(PermanentError):
        textx.extract_text(write(tmp_path, "blank.txt", b"  \n\n  "))


def test_language_detection(tmp_path):
    en = textx.extract_text(write(tmp_path, "en.txt", (LOREM * 2).encode()))
    de = textx.extract_text(
        write(
            tmp_path,
            "de.txt",
            ("Der Umsatz stieg im vergangenen Quartal deutlich an, " * 4).encode(),
        )
    )
    assert ex.detect_language(en) == "en" and ex.detect_language(de) == "de"
    short = textx.extract_text(write(tmp_path, "s.txt", b"hi"))
    assert ex.detect_language(short) is None


# ---------- the real stage inside the pipeline ----------


async def _run_pipeline(client, app, fake_stages, filename, data, ocr=None, monkeypatch=None):
    fake_stages.set(
        o.Stage("extract", S.EXTRACTING, stages.extract_stage),
        fake_stages.make("chunk", S.CHUNKING), fake_stages.make("embed", S.EMBEDDING),
        fake_stages.make("index", S.INDEXING),
    )  # fmt: skip
    await register(client)
    ws = await first_workspace(client)
    await enable_ai(client, ws["id"])
    base = f"/api/v1/workspaces/{ws['id']}"
    r = await client.post(
        f"{base}/documents/upload", files=[("files", (filename, data, "application/octet-stream"))]
    )
    doc = r.json()["results"][0]["document"]
    await app.state.queue.drain()
    d = (await client.get(f"{base}/documents/{doc['id']}")).json()
    return d, doc["id"]


async def test_pipeline_extracts_pdf_and_stores_result(client, app, fake_stages):
    data = make_pdf(
        [{"heading": "Findings", "body": LOREM * 3}, {"heading": "Conclusion", "body": LOREM}]
    )
    d, doc_id = await _run_pipeline(client, app, fake_stages, "r.pdf", data)
    assert d["status"] == "COMPLETED" and d["page_count"] == 2 and d["language"] == "en"
    version = await app.state.db.document_versions.find_one({"document_id": ObjectId(doc_id)})
    stored = json.loads(
        await app.state.store.get_bytes(stages.extracted_key(version["storage_key"]))
    )
    assert (
        stored["page_basis"] == "physical" and stored["pages"][0]["blocks"][0]["text"] == "Findings"
    )
    assert version["extraction"]["page_basis"] == "physical"


async def test_pipeline_uses_ocr_and_enters_ocr_status(client, app, fake_stages, monkeypatch):
    engine = FakeOCR()
    monkeypatch.setattr(ex, "build_ocr", lambda settings: engine)
    seen: list[str] = []
    orig = o.StageContext.enter

    async def spy(self, status):
        seen.append(status.value)
        return await orig(self, status)

    monkeypatch.setattr(o.StageContext, "enter", spy)
    d, _ = await _run_pipeline(client, app, fake_stages, "scan.pdf", make_scanned_pdf(["INVOICE"]))
    assert d["status"] == "COMPLETED" and engine.calls == 1
    assert "OCR_PROCESSING" in seen


async def test_pipeline_scanned_without_ocr_fails_with_clear_message(
    client, app, fake_stages, monkeypatch
):
    monkeypatch.setattr(ex, "build_ocr", lambda settings: FakeOCR(ok=False))
    d, _ = await _run_pipeline(client, app, fake_stages, "scan.pdf", make_scanned_pdf(["INVOICE"]))
    assert d["status"] == "FAILED" and "OCR is not available" in d["error"]


async def test_pipeline_encrypted_pdf_fails_with_user_message(client, app, fake_stages):
    d, _ = await _run_pipeline(
        client, app, fake_stages, "e.pdf", make_pdf([{"body": LOREM}], encrypt="pw")
    )
    assert d["status"] == "FAILED" and d["error"] == "The PDF is password protected"


async def test_pipeline_docx_and_txt(client, app, fake_stages):
    d, _ = await _run_pipeline(
        client, app, fake_stages, "a.docx", make_docx([("Heading 1", "T"), ("Normal", LOREM)])
    )
    assert d["status"] == "COMPLETED" and d["page_count"] == 1
