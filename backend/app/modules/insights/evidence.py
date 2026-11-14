"""Verify model-claimed evidence against the real extracted text. Used by insights, research and
comparison so no module ever shows an unverified quote or page as fact."""

import re
from dataclasses import dataclass, field

from app.modules.extraction.models import ExtractedDocument
from app.modules.insights.schemas import DatedItem, Finding

_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    return _WS.sub(" ", text).strip().lower()


@dataclass
class PageIndex:
    pages: dict[int, str]  # page number -> normalised text
    max_page: int
    dropped_quotes: int = field(default=0)
    dropped_pages: int = field(default=0)

    @classmethod
    def from_document(cls, doc: ExtractedDocument) -> "PageIndex":
        pages = {p.number: norm(p.text) for p in doc.pages}
        return cls(pages, max(pages) if pages else 0)

    def locate(self, quote: str) -> int | None:
        q = norm(quote).strip(" .,;:!?\"'")
        if len(q) < 8:
            return None
        for n, text in self.pages.items():
            if q in text:
                return n
        return None

    def verify(self, f: Finding) -> Finding:
        """Return the finding with an unverifiable quote removed and an impossible page cleared.
        A verified quote also fixes a wrong page number."""
        page, quote = f.page, f.quote
        if page is not None and not (1 <= page <= self.max_page):
            page = None
            self.dropped_pages += 1
        if quote:
            found = self.locate(quote)
            if found is None or (page is not None and q_not_on_page(self, quote, page)):
                if found is not None:
                    page = found  # quote is real but the page was wrong
                else:
                    quote = None
                    self.dropped_quotes += 1
            elif page is None:
                page = found
        return Finding(text=f.text, page=page, quote=quote)

    def verify_all(self, items: list[Finding]) -> list[Finding]:
        return [self.verify(f) for f in items]

    def verify_dates(self, items: list[DatedItem]) -> list[DatedItem]:
        out = []
        for d in items:
            page = d.page
            if page is not None and not (1 <= page <= self.max_page):
                page = None
                self.dropped_pages += 1
            out.append(DatedItem(date=d.date, description=d.description, page=page))
        return out


def q_not_on_page(index: PageIndex, quote: str, page: int) -> bool:
    q = norm(quote).strip(" .,;:!?\"'")
    return q not in index.pages.get(page, "")
