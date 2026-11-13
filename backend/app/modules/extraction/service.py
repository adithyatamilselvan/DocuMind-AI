from collections.abc import Callable

from langdetect import DetectorFactory, LangDetectException, detect

from app.core.config import Settings
from app.modules.documents.validation import DOCX, PDF, TXT
from app.modules.extraction import text, word
from app.modules.extraction.models import ExtractedDocument
from app.modules.extraction.normalize import strip_repeated_furniture
from app.modules.extraction.ocr import OCREngine, TesseractOCR

DetectorFactory.seed = 0


def build_ocr(settings: Settings) -> OCREngine | None:
    if not settings.ocr_enabled:
        return None
    return TesseractOCR(settings.tesseract_cmd, settings.ocr_langs)


def detect_language(doc: ExtractedDocument) -> str | None:
    sample = " ".join(p.text for p in doc.pages[:5])[:5000]
    if len(sample.strip()) < 40:
        return None
    try:
        return detect(sample)
    except LangDetectException:
        return None


def finalize(doc: ExtractedDocument) -> ExtractedDocument:
    removed = strip_repeated_furniture(doc)
    if removed:
        doc.metadata["removed_header_footer_blocks"] = removed
    doc.metadata["language"] = detect_language(doc)
    doc.metadata["ocr_pages"] = [p.number for p in doc.pages if p.ocr]
    doc.metadata["table_count"] = sum(1 for p in doc.pages for b in p.blocks if b.type == "table")
    return doc


def extract_non_pdf(path: str, mime: str) -> ExtractedDocument:
    if mime == DOCX:
        return word.extract_docx(path)
    if mime == TXT:
        return text.extract_text(path)
    raise ValueError(f"Unsupported mime type {mime}")


def is_pdf(mime: str) -> bool:
    return mime == PDF


ProgressFn = Callable[[float], None]
