"""Registers the real pipeline stages with the orchestrator."""

import asyncio
import json
import os
import tempfile

from app.modules.documents.states import DocumentStatus
from app.modules.extraction import pdf as pdf_extract
from app.modules.extraction import service as extraction
from app.modules.extraction.models import ExtractedDocument
from app.modules.extraction.ocr import OCRUnavailableError
from app.modules.ingestion.errors import PermanentError
from app.modules.ingestion.orchestrator import STAGES, Stage, StageContext
from app.storage.base import ObjectNotFoundError


def extracted_key(storage_key: str) -> str:
    """Extraction output lives next to the original, in the object store (not in Mongo)."""
    return storage_key.rsplit("/", 1)[0] + "/extracted.json"


async def load_extracted(ctx: StageContext) -> ExtractedDocument:
    try:
        raw = await ctx.store.get_bytes(extracted_key(ctx.version["storage_key"]))
    except ObjectNotFoundError as e:
        raise PermanentError("Extracted content is missing; retry processing") from e
    return ExtractedDocument.from_json(json.loads(raw))


async def extract_stage(ctx: StageContext) -> None:
    settings = ctx.settings
    mime = ctx.version["mime_type"]
    fd, path = tempfile.mkstemp(prefix="documind-extract-")
    os.close(fd)
    try:
        await ctx.store.download_to(ctx.version["storage_key"], path)
        loop = asyncio.get_running_loop()

        def progress(f: float) -> None:
            asyncio.run_coroutine_threadsafe(ctx.progress(f), loop)

        if extraction.is_pdf(mime):
            doc, ocr_needed = await asyncio.to_thread(
                pdf_extract.extract_text_layer, path, settings.max_pages_per_document, progress
            )
            if ocr_needed:
                engine = extraction.build_ocr(settings)
                if engine is None or not engine.available():
                    if doc.char_count == 0:
                        raise PermanentError(
                            "This looks like a scanned document but OCR is not available on the server"
                        )
                    doc.warnings.append(
                        f"{len(ocr_needed)} scanned page(s) were skipped because OCR is not available"
                    )
                else:
                    await ctx.enter(DocumentStatus.OCR_PROCESSING)
                    try:
                        await asyncio.to_thread(
                            pdf_extract.ocr_pages, path, doc, ocr_needed, engine,
                            settings.ocr_max_pages, 200, progress,
                        )  # fmt: skip
                    except OCRUnavailableError:
                        doc.warnings.append("OCR engine became unavailable; scanned pages skipped")
        else:
            doc = await asyncio.to_thread(extraction.extract_non_pdf, path, mime)

        extraction.finalize(doc)
        if doc.char_count == 0:
            raise PermanentError("No readable text was found in this document")

        key = extracted_key(ctx.version["storage_key"])
        payload = json.dumps(doc.to_json(), ensure_ascii=False).encode("utf-8")
        fd2, out = tempfile.mkstemp(prefix="documind-extracted-")
        try:
            with os.fdopen(fd2, "wb") as f:
                f.write(payload)
            await ctx.store.put_file(key, out, "application/json")
        finally:
            os.unlink(out)

        page_count = len(doc.pages)
        info = {
            "page_basis": doc.page_basis, "ocr_pages": doc.metadata.get("ocr_pages", []),
            "table_count": doc.metadata.get("table_count", 0), "warnings": doc.warnings,
            "char_count": doc.char_count, "title": doc.metadata.get("title"),
            "author": doc.metadata.get("author"),
        }  # fmt: skip
        await ctx.db.documents.update_one(
            {"_id": ctx.document["_id"]},
            {"$set": {
                "page_count": page_count, "language": doc.metadata.get("language"),
                "extraction": info,
            }},
        )  # fmt: skip
        await ctx.db.document_versions.update_one(
            {"_id": ctx.version["_id"]}, {"$set": {"page_count": page_count, "extraction": info}}
        )
    finally:
        os.unlink(path)


def register_default_stages() -> list[Stage]:
    """Idempotently (re)build the default stage list.

    Chunking, embedding and indexing stages are appended by Phase 8."""
    STAGES.clear()
    STAGES.append(Stage("extract", DocumentStatus.EXTRACTING, extract_stage))
    return STAGES
