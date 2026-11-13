import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.ai.errors import LLMError, LLMNotConfiguredError, LLMRefusalError
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.modules.auth.deps import DB
from app.modules.documents.transfer_router import require_ai_consent
from app.modules.rag.deps import LLM, Embedder, RerankerDep, Vectors
from app.modules.rag.pipeline import RagPipeline
from app.modules.rag.schemas import AskOut, Filters, HistoryMessage
from app.modules.retrieval.scope import resolve_scope
from app.modules.retrieval.service import Mode, retrieve
from app.modules.workspaces.deps import WorkspaceContext, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["rag"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Config = Annotated[Settings, Depends(get_settings)]


def llm_http_error(e: LLMError) -> AppError:
    if isinstance(e, LLMNotConfiguredError):
        return AppError(503, "llm_not_configured", e.message)
    if isinstance(e, LLMRefusalError):
        return AppError(422, "model_refused", e.message, {"category": e.category})
    return AppError(503 if e.retryable else 502, "llm_unavailable", e.message)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=40)
    filters: Filters = Field(default_factory=Filters)
    top_k: int | None = Field(None, ge=1, le=20)


@router.post("/ask", response_model=AskOut)
async def ask(
    body: AskIn, ctx: Viewer, db: DB, settings: Config, vectors: Vectors, embedder: Embedder,
    reranker: RerankerDep, llm: LLM,
):  # fmt: skip
    """Stateless grounded question answering over the caller's documents."""
    require_ai_consent(ctx, settings)
    pipe = RagPipeline(
        db=db, store=vectors, embedder=embedder, reranker=reranker, llm=llm, settings=settings
    )
    try:
        final = await pipe.answer(
            workspace_id=ctx.workspace_id, user_id=ctx.user_id, question=body.question,
            history=body.history, filters=body.filters, top_k=body.top_k,
        )  # fmt: skip
    except LLMError as e:
        raise llm_http_error(e) from e
    return AskOut(**{k: final[k] for k in AskOut.model_fields})


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"
    filters: Filters = Field(default_factory=Filters)
    limit: int = Field(10, ge=1, le=50)


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    page_number: int | None
    section_heading: str | None
    snippet: str
    score: float
    vector_score: float | None
    keyword_score: float | None


class SearchOut(BaseModel):
    hits: list[SearchHit]
    terms: list[str]
    debug: dict


_WORD = re.compile(r"\w{3,}")


@router.post("/search", response_model=SearchOut)
async def search(
    body: SearchIn, ctx: Viewer, db: DB, settings: Config, vectors: Vectors, embedder: Embedder,
    reranker: RerankerDep,
):  # fmt: skip
    """Semantic, keyword or hybrid search over document passages."""
    if body.mode != "keyword":
        require_ai_consent(
            ctx, settings
        )  # semantic search sends the query to the embedding provider
    scope = await resolve_scope(db, ctx.workspace_id, **body.filters.model_dump())
    mode: Mode = body.mode
    res = await retrieve(
        db=db, store=vectors, embedder=embedder, reranker=reranker, settings=settings,
        scope=scope, queries=[body.query], mode=mode,
    )  # fmt: skip
    hits = [
        SearchHit(
            chunk_id=c.chunk_id,
            document_id=str(c.document_id),
            document_title=c.document_title,
            page_number=c.page_number,
            section_heading=c.section_heading,
            snippet=c.content[:600],
            score=round(c.score, 4),
            vector_score=c.vector_score,
            keyword_score=c.keyword_score,
        )  # fmt: skip
        for c in res.chunks[: body.limit]
    ]
    return SearchOut(
        hits=hits, terms=sorted(set(_WORD.findall(body.query.lower()))), debug=res.debug
    )
