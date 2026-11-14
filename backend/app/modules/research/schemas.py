from typing import Literal

from pydantic import BaseModel, Field

from app.modules.insights.schemas import Finding

SCHEMA_VERSION = 1
MethodCategory = Literal[
    "experimental", "observational", "survey", "case_study", "simulation",
    "theoretical", "review", "qualitative", "mixed", "other",
]  # fmt: skip


class Gap(BaseModel):
    """A potential research gap. ALWAYS AI-inferred: shown to users as a suggestion, never as fact."""

    text: str = Field(max_length=500)
    rationale: str = Field(
        max_length=500, description="Why this looks like a gap, based on the document"
    )
    evidence: list[Finding] = Field(default_factory=list, max_length=4)


class Methodology(BaseModel):
    category: MethodCategory = "other"
    description: str = Field("", max_length=600)
    evidence: list[Finding] = Field(default_factory=list, max_length=4)


class PaperAnalysis(BaseModel):
    is_research_paper: bool = Field(description="False if the document is not a research paper")
    objective: Finding | None = None
    research_questions: list[Finding] = Field(default_factory=list, max_length=8)
    hypotheses: list[Finding] = Field(default_factory=list, max_length=8)
    methodology: Methodology = Field(default_factory=Methodology)
    datasets: list[Finding] = Field(default_factory=list, max_length=8)
    sample_size: Finding | None = None
    results: list[Finding] = Field(default_factory=list, max_length=10)
    conclusions: list[Finding] = Field(default_factory=list, max_length=8)
    limitations: list[Finding] = Field(default_factory=list, max_length=8)
    future_work: list[Finding] = Field(default_factory=list, max_length=8)
    potential_gaps: list[Gap] = Field(default_factory=list, max_length=6)


class PaperItem(BaseModel):
    """A claim tied to one paper (1-based index into the input list) with verifiable evidence."""

    text: str = Field(max_length=500)
    paper: int = Field(ge=1)
    page: int | None = None
    quote: str | None = Field(None, max_length=300)


class Theme(BaseModel):
    title: str = Field(max_length=120)
    summary: str = Field(max_length=900)
    items: list[PaperItem] = Field(default_factory=list, max_length=10)


class TableRow(BaseModel):
    paper: int = Field(ge=1)
    methodology: str = Field("", max_length=200)
    datasets: str = Field("", max_length=200)
    sample_size: str = Field("", max_length=100)
    key_result: str = Field("", max_length=300)


class Contradiction(BaseModel):
    topic: str = Field(max_length=200)
    explanation: str = Field(max_length=600)
    positions: list[PaperItem] = Field(default_factory=list, max_length=6)


class SynthGap(BaseModel):
    text: str = Field(max_length=500)
    rationale: str = Field(max_length=500)
    papers: list[int] = Field(default_factory=list, max_length=10)


class Synthesis(BaseModel):
    overview: str = Field(
        max_length=2500, description="Literature-review style overview of all papers"
    )
    themes: list[Theme] = Field(default_factory=list, max_length=8)
    comparison_table: list[TableRow] = Field(default_factory=list, max_length=10)
    contradictions: list[Contradiction] = Field(default_factory=list, max_length=8)
    trends: list[PaperItem] = Field(default_factory=list, max_length=8)
    research_gaps: list[SynthGap] = Field(default_factory=list, max_length=8)
