from typing import Any, Literal

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    """Structured output of the query-understanding step (validated by Pydantic)."""

    standalone_question: str = Field(max_length=1000)
    search_queries: list[str] = Field(default_factory=list, max_length=3)
    intent: Literal["factual", "summary", "comparison", "other"] = "other"


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20000)


class Filters(BaseModel):
    document_ids: list[str] | None = Field(None, max_length=200)
    collection_ids: list[str] | None = Field(None, max_length=50)
    knowledge_base_ids: list[str] | None = Field(None, max_length=50)
    category: str | None = None
    tags: list[str] | None = None
    mime_type: str | None = None


class CitationOut(BaseModel):
    index: int
    chunk_id: str
    document_id: str
    document_title: str
    version_id: str
    page_number: int | None
    page_is_exact: bool  # False for DOCX/TXT, whose "pages" are virtual groupings
    section_heading: str | None
    snippet: str
    score: float


class AskOut(BaseModel):
    answer: str
    citations: list[CitationOut]
    grounded: bool
    insufficient_evidence: bool
    warnings: list[str]
    retrieval: dict[str, Any]
    usage: dict[str, Any]
    prompt_version: str
