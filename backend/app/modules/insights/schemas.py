"""Typed LLM output for document intelligence. Every claim that points at the document carries an
optional page and verbatim quote, which are VERIFIED against the extracted text after generation."""

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class Finding(BaseModel):
    text: str = Field(max_length=500)
    page: int | None = Field(
        None, description="Page (or section) number where the evidence appears"
    )
    quote: str | None = Field(
        None,
        max_length=300,
        description="Short verbatim quote from the document supporting the text",
    )


class Classification(BaseModel):
    document_type: str = Field(
        max_length=60, description="e.g. research paper, contract, report, invoice, letter"
    )
    category: str = Field(
        max_length=60, description="One or two words, e.g. Finance, Legal, Biology"
    )
    confidence: Literal["low", "medium", "high"] = "medium"


class Entities(BaseModel):
    people: list[str] = Field(default_factory=list, max_length=20)
    organizations: list[str] = Field(default_factory=list, max_length=20)
    locations: list[str] = Field(default_factory=list, max_length=15)


class DatedItem(BaseModel):
    date: str = Field(max_length=40, description="The date as written in the document")
    description: str = Field(max_length=200)
    page: int | None = None


class DocumentInsights(BaseModel):
    summary: str = Field(max_length=1500, description="Neutral summary of the whole document")
    executive_summary: str = Field(max_length=700, description="3-4 sentences for a busy reader")
    key_findings: list[Finding] = Field(default_factory=list, max_length=10)
    key_facts: list[Finding] = Field(default_factory=list, max_length=10)
    topics: list[str] = Field(default_factory=list, max_length=12)
    keywords: list[str] = Field(default_factory=list, max_length=15)
    classification: Classification
    entities: Entities = Field(default_factory=Entities)
    important_dates: list[DatedItem] = Field(default_factory=list, max_length=12)
    main_arguments: list[Finding] = Field(default_factory=list, max_length=8)
    conclusions: list[Finding] = Field(default_factory=list, max_length=8)
    limitations: list[Finding] = Field(default_factory=list, max_length=8)
    action_items: list[str] = Field(default_factory=list, max_length=10)
    suggested_questions: list[str] = Field(default_factory=list, max_length=6)


class SectionNotes(BaseModel):
    """Intermediate map-step output for long documents."""

    summary: str = Field(max_length=1500)
    points: list[Finding] = Field(default_factory=list, max_length=15)
