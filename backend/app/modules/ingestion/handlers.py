"""Registry of non-ingestion job handlers (lazy imports avoid import cycles)."""

from collections.abc import Awaitable, Callable
from typing import Any

from bson import ObjectId

Handler = Callable[[Any, Any, Any, ObjectId], Awaitable[None]]


def handler_for(job_type: str) -> Handler:
    if job_type == "insights":
        from app.modules.insights.service import run_insights_job

        return run_insights_job
    if job_type == "research":
        from app.modules.research.service import run_research_job

        return run_research_job
    if job_type == "comparison":
        from app.modules.comparison.service import run_comparison_job

        return run_comparison_job
    if job_type == "report":
        from app.modules.reports.service import run_report_job

        return run_report_job
    raise ValueError(f"Unknown job type {job_type}")
