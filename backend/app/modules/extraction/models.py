from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BlockType = Literal["heading", "paragraph", "table"]


@dataclass
class Block:
    type: BlockType
    text: str  # for tables: a plain-text rendering (rows joined by newlines, cells by " | ")
    level: int | None = None  # headings: 1 (largest) .. 3
    bbox: list[float] | None = None  # PDF only: [x0, y0, x1, y1] in page points
    rows: list[list[str]] | None = None  # tables only


@dataclass
class Page:
    number: int  # 1-based. For DOCX/TXT this is a *virtual* page (see ExtractedDocument.page_basis)
    blocks: list[Block] = field(default_factory=list)
    ocr: bool = False
    width: float | None = None
    height: float | None = None

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.text)


@dataclass
class ExtractedDocument:
    pages: list[Page]
    # "physical": real PDF pages. "virtual": DOCX/TXT have no fixed pages; numbers come from explicit
    # page breaks or ~3000-character groups and must not be presented as true page numbers.
    page_basis: Literal["physical", "virtual"]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(p.text) for p in self.pages)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "ExtractedDocument":
        pages = [
            Page(
                number=p["number"],
                ocr=p.get("ocr", False),
                width=p.get("width"),
                height=p.get("height"),
                blocks=[Block(**b) for b in p["blocks"]],
            )  # fmt: skip
            for p in d["pages"]
        ]
        return cls(pages, d["page_basis"], d.get("metadata", {}), d.get("warnings", []))
