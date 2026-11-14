import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from app.ai.errors import LLMError
from app.core.errors import not_found
from app.core.ids import to_oid, utcnow
from app.modules.rag.pipeline import RagPipeline
from app.modules.rag.schemas import Filters, HistoryMessage

log = logging.getLogger("documind.chat")
_CITE = re.compile(r"\s*\[\d+\]")
_llm_slots: asyncio.Semaphore | None = None


def llm_slots(limit: int) -> asyncio.Semaphore:
    """Process-wide cap on concurrent answer generations."""
    global _llm_slots
    if _llm_slots is None:
        _llm_slots = asyncio.Semaphore(limit)
    return _llm_slots


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _scope_doc(f: Filters) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("document_ids", "collection_ids", "knowledge_base_ids"):
        vals = getattr(f, key)
        if vals:
            out[key] = [to_oid(v, "Scope item") for v in vals]
    for key in ("category", "mime_type"):
        if getattr(f, key):
            out[key] = getattr(f, key)
    if f.tags:
        out["tags"] = f.tags
    return out


def _own(workspace_id: ObjectId, user_id: ObjectId, conversation_id: str) -> dict[str, Any]:
    return {
        "_id": to_oid(conversation_id, "Conversation"),
        "workspace_id": workspace_id,
        "user_id": user_id,
    }


async def create_conversation(
    db: AsyncDatabase, workspace_id: ObjectId, user_id: ObjectId, title: str | None, scope: Filters
) -> dict[str, Any]:
    now = utcnow()
    doc = {
        "workspace_id": workspace_id, "user_id": user_id, "title": (title or "New conversation").strip(),
        "auto_title": not title, "scope": _scope_doc(scope), "message_count": 0,
        "created_at": now, "updated_at": now,
    }  # fmt: skip
    doc["_id"] = (await db.conversations.insert_one(doc)).inserted_id
    return doc


async def list_conversations(
    db: AsyncDatabase, workspace_id: ObjectId, user_id: ObjectId, q: str | None, limit: int = 100
) -> list[dict[str, Any]]:
    f: dict[str, Any] = {"workspace_id": workspace_id, "user_id": user_id}
    if q and q.strip():
        by_msg = await db.messages.distinct(
            "conversation_id",
            {"workspace_id": workspace_id, "user_id": user_id, "$text": {"$search": q}},
        )
        f["$or"] = [
            {"title": {"$regex": re.escape(q.strip()), "$options": "i"}},
            {"_id": {"$in": by_msg}},
        ]
    return [c async for c in db.conversations.find(f).sort("updated_at", -1).limit(limit)]


async def get_conversation(
    db: AsyncDatabase, workspace_id: ObjectId, user_id: ObjectId, conversation_id: str
) -> dict[str, Any]:
    c = await db.conversations.find_one(_own(workspace_id, user_id, conversation_id))
    if not c:
        raise not_found("Conversation not found")
    return c


async def update_conversation(
    db: AsyncDatabase, workspace_id: ObjectId, user_id: ObjectId, conversation_id: str,
    title: str | None, scope: Filters | None,
) -> dict[str, Any]:  # fmt: skip
    patch: dict[str, Any] = {"updated_at": utcnow()}
    if title is not None:
        patch.update(title=title.strip(), auto_title=False)
    if scope is not None:
        patch["scope"] = _scope_doc(scope)
    c = await db.conversations.find_one_and_update(
        _own(workspace_id, user_id, conversation_id),
        {"$set": patch},
        return_document=ReturnDocument.AFTER,
    )
    if not c:
        raise not_found("Conversation not found")
    return c


async def delete_conversation(
    db: AsyncDatabase, workspace_id: ObjectId, user_id: ObjectId, conversation_id: str
) -> None:
    c = await get_conversation(db, workspace_id, user_id, conversation_id)
    await db.messages.delete_many({"conversation_id": c["_id"]})
    await db.conversations.delete_one({"_id": c["_id"]})


async def list_messages(db: AsyncDatabase, conversation_id: ObjectId) -> list[dict[str, Any]]:
    return [
        m
        async for m in db.messages.find({"conversation_id": conversation_id}).sort("created_at", 1)
    ]


async def set_feedback(
    db: AsyncDatabase, workspace_id: ObjectId, user_id: ObjectId, conversation_id: str,
    message_id: str, rating: str | None, comment: str | None,
) -> None:  # fmt: skip
    c = await get_conversation(db, workspace_id, user_id, conversation_id)
    fb = {"rating": rating, "comment": comment, "at": utcnow()} if rating else None
    res = await db.messages.update_one(
        {"_id": to_oid(message_id, "Message"), "conversation_id": c["_id"], "role": "assistant"},
        {"$set": {"feedback": fb}},
    )
    if res.matched_count == 0:
        raise not_found("Message not found")


async def _add_message(
    db: AsyncDatabase, conv: dict[str, Any], role: str, content: str, **extra: Any
) -> dict[str, Any]:
    now = utcnow()
    doc = {
        "conversation_id": conv["_id"], "workspace_id": conv["workspace_id"], "user_id": conv["user_id"],
        "role": role, "content": content, "citations": [], "meta": {}, "feedback": None,
        "created_at": now, **extra,
    }  # fmt: skip
    doc["_id"] = (await db.messages.insert_one(doc)).inserted_id
    await db.conversations.update_one(
        {"_id": conv["_id"]}, {"$set": {"updated_at": now}, "$inc": {"message_count": 1}}
    )
    return doc


def _history(messages: list[dict[str, Any]]) -> list[HistoryMessage]:
    return [
        HistoryMessage(
            role=m["role"],
            content=_CITE.sub("", m["content"]) if m["role"] == "assistant" else m["content"],
        )
        for m in messages
    ]


async def stream_turn(
    *, db: AsyncDatabase, pipeline: RagPipeline, conv: dict[str, Any], question: str,
    history_messages: list[dict[str, Any]], slots: asyncio.Semaphore, save_user_message: bool = True,
) -> AsyncIterator[str]:  # fmt: skip
    """One answer turn as Server-Sent Events. The user message is stored first; the assistant
    message is stored only once a validated final answer exists."""
    if save_user_message:
        um = await _add_message(db, conv, "user", question)
        yield sse("user_message", {"id": str(um["_id"])})
        if conv.get("auto_title") and conv["message_count"] == 0:
            title = (question[:57] + "...") if len(question) > 60 else question
            await db.conversations.update_one(
                {"_id": conv["_id"]}, {"$set": {"title": title, "auto_title": False}}
            )
            yield sse("title", {"title": title})

    scope = Filters(
        **{
            k: [str(i) for i in v] if isinstance(v, list) else v
            for k, v in conv.get("scope", {}).items()
        }
    )
    try:
        async with slots:
            async for ev in pipeline.run(
                workspace_id=conv["workspace_id"], user_id=conv["user_id"], question=question,
                history=_history(history_messages), filters=scope,
            ):  # fmt: skip
                if ev["type"] != "final":
                    yield sse(ev["type"], {k: v for k, v in ev.items() if k != "type"})
                    continue
                am = await _add_message(
                    db, conv, "assistant", ev["answer"], citations=ev["citations"],
                    meta={k: ev[k] for k in ("grounded", "insufficient_evidence", "warnings", "retrieval", "usage", "prompt_version")},
                )  # fmt: skip
                yield sse(
                    "final",
                    {
                        **{k: v for k, v in ev.items() if k not in ("type", "withheld_answer")},
                        "message_id": str(am["_id"]),
                    },
                )
    except LLMError as e:
        yield sse(
            "error", {"code": "llm_unavailable", "message": e.message, "retryable": e.retryable}
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Unexpected error while streaming an answer")
        yield sse(
            "error",
            {
                "code": "internal_error",
                "message": "Something went wrong while answering.",
                "retryable": True,
            },
        )
    yield sse("done", {})
