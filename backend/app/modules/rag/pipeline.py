"""Question -> understanding -> permission-filtered scope -> hybrid retrieval -> rerank ->
context selection -> generation -> citation validation -> response (also as an event stream)."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.ai.errors import LLMError
from app.ai.prompts import rag as prompts
from app.ai.providers.embeddings import EmbeddingProvider
from app.ai.providers.llm import LLMProvider, LLMUsage, Message
from app.core.config import Settings
from app.modules.rag.citations import ValidatedAnswer, validate_answer
from app.modules.rag.context import select_context
from app.modules.rag.schemas import CitationOut, Filters, HistoryMessage, QueryPlan
from app.modules.retrieval.rerank import Reranker
from app.modules.retrieval.scope import resolve_scope
from app.modules.retrieval.service import retrieve
from app.modules.usage.service import record_usage
from app.modules.vector_search.base import VectorStore

log = logging.getLogger("documind.rag")
SNIPPET_CHARS = 500


def _usage_dict(*usages: LLMUsage) -> dict[str, Any]:
    return {
        "input_tokens": sum(u.input_tokens for u in usages),
        "output_tokens": sum(u.output_tokens for u in usages),
        "cache_read_tokens": sum(u.cache_read_tokens for u in usages),
        "llm_latency_ms": sum(u.latency_ms for u in usages),
    }


def _history_messages(history: list[HistoryMessage], turns: int) -> list[Message]:
    """Last `turns` messages, forced to alternate user/assistant and to start with a user turn."""
    out: list[Message] = []
    for m in history[-turns:]:
        if out and out[-1]["role"] == m.role:
            out[-1]["content"] += "\n\n" + m.content
        else:
            out.append({"role": m.role, "content": m.content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if out and out[-1]["role"] == "user":
        out.pop()  # the new question is appended as the final user turn
    return out


class RagPipeline:
    def __init__(
        self, *, db: AsyncDatabase, store: VectorStore, embedder: EmbeddingProvider,
        reranker: Reranker, llm: LLMProvider, settings: Settings,
    ) -> None:  # fmt: skip
        self.db, self.store, self.embedder = db, store, embedder
        self.reranker, self.llm, self.settings = reranker, llm, settings

    async def _plan(
        self,
        question: str,
        history: list[HistoryMessage],
        workspace_id: ObjectId,
        user_id: ObjectId | None,
    ) -> tuple[QueryPlan | None, LLMUsage | None]:
        """Query understanding. Failure never blocks answering: fall back to the raw question."""
        s = self.settings
        if not (history or s.rag_multi_query):
            return None, None
        convo = "\n".join(f"{m.role}: {m.content[:600]}" for m in history[-s.rag_history_turns :])
        user = (
            f"Conversation so far:\n{convo}\n\n" if convo else ""
        ) + f"Latest question: {question}"
        try:
            plan, usage = await self.llm.structured(
                prompts.PLAN_SYSTEM, [{"role": "user", "content": user}], QueryPlan, max_tokens=600
            )
        except LLMError as e:
            log.warning("Query planning failed (%s); using the raw question", e.message)
            return None, None
        await record_usage(
            self.db, workspace_id=workspace_id, user_id=user_id, kind="chat_plan",
            provider=self.llm.name, model=self.llm.model, tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens, latency_ms=usage.latency_ms,
        )  # fmt: skip
        return plan, usage

    async def run(
        self, *, workspace_id: ObjectId, user_id: ObjectId | None, question: str,
        history: list[HistoryMessage] | None = None, filters: Filters | None = None,
        top_k: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:  # fmt: skip
        s = self.settings
        history = history or []
        filters = filters or Filters()
        top_k = min(top_k or s.rag_top_k, 20)

        yield {"type": "status", "stage": "understanding"}
        plan, plan_usage = await self._plan(question, history, workspace_id, user_id)
        standalone = (
            plan.standalone_question if plan and plan.standalone_question.strip() else question
        )
        queries = [standalone, *(plan.search_queries if plan else [])][:4]

        yield {"type": "status", "stage": "searching"}
        scope = await resolve_scope(self.db, workspace_id, **filters.model_dump())
        result = await retrieve(
            db=self.db, store=self.store, embedder=self.embedder, reranker=self.reranker,
            settings=s, scope=scope, queries=queries, rerank_query=standalone,
        )  # fmt: skip
        sources = select_context(result.chunks, top_k=top_k, token_budget=s.rag_context_tokens)
        retrieval_info = {
            **result.debug,
            "selected": len(sources),
            "standalone_question": standalone,
            "intent": plan.intent if plan else None,
        }
        yield {
            "type": "retrieval", "retrieval": retrieval_info,
            "sources": [
                {"label": k, "document_id": str(c.document_id), "title": c.document_title,
                 "page": c.page_number, "score": round(c.score, 4)}
                for k, c in sources.items()
            ],
        }  # fmt: skip

        if not sources:
            yield self._final_insufficient(retrieval_info, plan_usage)
            return

        yield {"type": "status", "stage": "answering"}
        turn = prompts.render_user_turn(
            [{"label": k, "title": c.document_title, "page": c.page_number,
              "section": c.section_heading, "content": c.content} for k, c in sources.items()],
            standalone if history else question,
        )  # fmt: skip
        messages = [
            *_history_messages(history, s.rag_history_turns),
            {"role": "user", "content": turn},
        ]

        buffer, streaming, final = "", False, None
        async for item in self.llm.stream(prompts.ANSWER_SYSTEM, messages):
            if isinstance(item, str):
                buffer += item
                if streaming:
                    yield {"type": "token", "text": item}
                elif len(buffer) >= len(prompts.NO_EVIDENCE) + 1:
                    # Hold back the first few characters to detect the NO_EVIDENCE sentinel.
                    if not buffer.startswith(prompts.NO_EVIDENCE):
                        streaming = True
                        yield {"type": "token", "text": buffer}
            else:
                final = item
        assert final is not None
        raw = final.text

        await record_usage(
            self.db, workspace_id=workspace_id, user_id=user_id, kind="chat",
            provider=self.llm.name, model=self.llm.model, tokens_in=final.usage.input_tokens,
            tokens_out=final.usage.output_tokens, latency_ms=final.usage.latency_ms,
            meta={"prompt_version": prompts.PROMPT_VERSION, "sources": len(sources)},
        )  # fmt: skip

        usage = _usage_dict(final.usage, *([plan_usage] if plan_usage else []))
        if raw.strip().startswith(prompts.NO_EVIDENCE):
            missing = raw.strip()[len(prompts.NO_EVIDENCE) :].lstrip(": ").strip()
            msg = prompts.INSUFFICIENT_MESSAGE + (f"\n\nMissing: {missing}" if missing else "")
            yield self._final_insufficient(retrieval_info, plan_usage, usage, message=msg)
            return

        v = validate_answer(raw, sources)
        if not v.grounded:
            log.warning("Answer had no valid citations; replaced with insufficient-evidence reply")
            yield self._final_insufficient(
                retrieval_info, plan_usage, usage, raw=raw, ungrounded=True
            )
            return
        yield self._final(v, retrieval_info, usage)

    # ---- final-event builders ----

    def _final(
        self, v: ValidatedAnswer, retrieval: dict[str, Any], usage: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "type": "final", "answer": v.text, "grounded": True, "insufficient_evidence": False,
            "warnings": v.warnings, "retrieval": retrieval, "usage": usage,
            "prompt_version": prompts.PROMPT_VERSION,
            "citations": [
                CitationOut(
                    index=c.index, chunk_id=c.chunk.chunk_id, document_id=str(c.chunk.document_id),
                    document_title=c.chunk.document_title, version_id=str(c.chunk.version_id),
                    page_number=c.chunk.page_number,
                    page_is_exact=c.chunk.metadata.get("page_basis") == "physical",
                    section_heading=c.chunk.section_heading,
                    snippet=c.chunk.content[:SNIPPET_CHARS], score=round(c.chunk.score, 4),
                ).model_dump()
                for c in v.citations
            ],
        }  # fmt: skip

    def _final_insufficient(
        self, retrieval: dict[str, Any], plan_usage: LLMUsage | None, usage: dict[str, Any] | None = None,
        *, message: str | None = None, raw: str | None = None, ungrounded: bool = False,
    ) -> dict[str, Any]:  # fmt: skip
        warnings = (
            ["The model's answer had no verifiable citations, so it was withheld."]
            if ungrounded
            else []
        )
        return {
            "type": "final", "answer": message or prompts.INSUFFICIENT_MESSAGE, "citations": [],
            "grounded": False, "insufficient_evidence": True, "warnings": warnings,
            "retrieval": retrieval, "usage": usage or _usage_dict(*([plan_usage] if plan_usage else [])),
            "prompt_version": prompts.PROMPT_VERSION, "withheld_answer": raw,
        }  # fmt: skip

    async def answer(self, **kwargs: Any) -> dict[str, Any]:
        final: dict[str, Any] | None = None
        async for ev in self.run(**kwargs):
            if ev["type"] == "final":
                final = ev
        assert final is not None
        return final
