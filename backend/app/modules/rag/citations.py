"""Citation validation. The model only ever sees opaque source ids (S1..Sn). Everything a user
sees about a citation (document, page, passage) comes from the retrieved chunk, never from
model text, and any id the model invents is removed."""

import re
from dataclasses import dataclass, field

from app.modules.retrieval.service import RetrievedChunk

_GROUP = re.compile(r"\[\s*S\d+(?:\s*[,;]?\s*S\d+)*\s*\]")
_LABEL = re.compile(r"S\d+")
_QUOTE = re.compile(r"[\"“]([^\"“”\n]{25,}?)[\"”]")
_CITED = re.compile(r"\[\d+\]")
_PUNCT = re.compile(r"[\s ]+")


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    return _PUNCT.sub(" ", text).strip().lower()


@dataclass
class Citation:
    index: int  # the [n] shown in the answer
    label: str  # original S-label
    chunk: RetrievedChunk


@dataclass
class ValidatedAnswer:
    text: str
    citations: list[Citation]
    invalid_labels: list[str] = field(default_factory=list)
    unverified_quotes: list[str] = field(default_factory=list)
    uncited_paragraphs: int = 0

    @property
    def grounded(self) -> bool:
        return bool(self.citations)

    @property
    def warnings(self) -> list[str]:
        w = []
        if self.invalid_labels:
            w.append(
                f"{len(self.invalid_labels)} citation(s) that did not match any source were removed."
            )
        if self.unverified_quotes:
            w.append(
                f"{len(self.unverified_quotes)} quotation(s) could not be verified in the sources."
            )
        if self.uncited_paragraphs:
            w.append(f"{self.uncited_paragraphs} paragraph(s) have no citation.")
        return w


def _quote_in_sources(quote: str, sources_norm: list[str]) -> bool:
    # A quotation may elide text with "..." / "…": each fragment must appear verbatim.
    fragments = [f for f in re.split(r"\.\.\.|…", quote) if len(f.strip()) >= 10]
    if not fragments:
        return True
    return all(any(_norm(f).strip(" .,;:!?") in s for s in sources_norm) for f in fragments)


def validate_answer(answer: str, sources: dict[str, RetrievedChunk]) -> ValidatedAnswer:
    """`sources` maps label (S1..) -> chunk actually shown to the model."""
    order: list[str] = []  # valid labels in order of first appearance
    invalid: list[str] = []

    def index_of(label: str) -> int:
        if label not in order:
            order.append(label)
        return order.index(label) + 1

    def replace_group(m: re.Match[str]) -> str:
        out = []
        for label in dict.fromkeys(_LABEL.findall(m.group(0))):
            if label in sources:
                out.append(f"[{index_of(label)}]")
            else:
                invalid.append(label)
        return "".join(out)

    text = _GROUP.sub(replace_group, answer)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)  # tidy spaces left by removed ids

    sources_norm = [_norm(c.content) for c in sources.values()]
    unverified: list[str] = []

    def check_quote(m: re.Match[str]) -> str:
        q = m.group(1)
        if _quote_in_sources(q, sources_norm):
            return m.group(0)
        unverified.append(q)
        return q  # keep the words but drop the quotation marks: it is not a verified quote

    text = _QUOTE.sub(check_quote, text)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    uncited = sum(1 for p in paragraphs if len(p) >= 80 and not _CITED.search(p))

    citations = [Citation(i + 1, label, sources[label]) for i, label in enumerate(order)]
    return ValidatedAnswer(text.strip(), citations, invalid, unverified, uncited)
