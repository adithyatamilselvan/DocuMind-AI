"""Registers the real pipeline stages with the orchestrator.

Stages are added by the phases that implement them (extraction, chunking, embedding, indexing).
"""

from app.modules.ingestion.orchestrator import STAGES, Stage


def register_default_stages() -> list[Stage]:
    """Idempotently (re)build the default stage list."""
    STAGES.clear()
    return STAGES
