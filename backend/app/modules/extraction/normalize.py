import re
import unicodedata
from collections import Counter

from app.modules.extraction.models import ExtractedDocument

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​‎‏﻿]")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_SPACES = re.compile(r"[ \t ]+")
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}


def clean_text(text: str) -> str:
    """Normalize one block of text: unicode, control chars, ligatures, soft hyphens,
    line-break hyphenation and whitespace. Paragraph-internal newlines become spaces."""
    text = unicodedata.normalize("NFC", text)
    for k, v in _LIGATURES.items():
        text = text.replace(k, v)
    text = text.replace("­", "")  # soft hyphen
    text = _CTRL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"\s*\n\s*", " ", text)
    return _SPACES.sub(" ", text).strip()


def clean_cell(text: str | None) -> str:
    return clean_text(text or "")


def _signature(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def strip_repeated_furniture(doc: ExtractedDocument, min_pages: int = 4) -> int:
    """Remove running headers/footers/page numbers: short top/bottom blocks whose text (digits
    masked) repeats on at least half of the pages. Returns the number of blocks removed."""
    if doc.page_basis != "physical" or len(doc.pages) < min_pages:
        return 0
    counts: Counter[str] = Counter()
    for p in doc.pages:
        if not p.height:
            continue
        seen = set()
        for b in p.blocks:
            if b.type == "table" or not b.bbox or len(b.text) > 120:
                continue
            if b.bbox[3] < p.height * 0.1 or b.bbox[1] > p.height * 0.9:
                seen.add(_signature(b.text))
        counts.update(seen)
    threshold = max(3, len(doc.pages) // 2)
    furniture = {s for s, n in counts.items() if n >= threshold and s}
    removed = 0
    for p in doc.pages:
        if not p.height:
            continue
        kept = []
        for b in p.blocks:
            is_edge = b.bbox and (b.bbox[3] < p.height * 0.1 or b.bbox[1] > p.height * 0.9)
            if b.type != "table" and is_edge and _signature(b.text) in furniture:
                removed += 1
                continue
            kept.append(b)
        p.blocks = kept
    return removed
