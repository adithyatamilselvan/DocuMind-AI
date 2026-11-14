from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.rate_limit import rate_limit
from app.modules.auth.deps import DB
from app.modules.chat import service
from app.modules.chat.schemas import (
    ConversationDetail,
    ConversationOut,
    CreateConversationIn,
    FeedbackIn,
    MessageOut,
    SendMessageIn,
    UpdateConversationIn,
)
from app.modules.documents.transfer_router import require_ai_consent
from app.modules.rag.deps import LLM, Embedder, RerankerDep, Vectors
from app.modules.rag.pipeline import RagPipeline
from app.modules.workspaces.deps import WorkspaceContext, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/conversations", tags=["chat"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Config = Annotated[Settings, Depends(get_settings)]

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",  # tell nginx not to buffer the stream
    "Connection": "keep-alive",
}


@router.get("", response_model=list[ConversationOut])
async def list_conversations(ctx: Viewer, db: DB, q: str | None = None):
    rows = await service.list_conversations(db, ctx.workspace_id, ctx.user_id, q)
    return [ConversationOut.from_doc(c) for c in rows]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(body: CreateConversationIn, ctx: Viewer, db: DB):
    c = await service.create_conversation(db, ctx.workspace_id, ctx.user_id, body.title, body.scope)
    return ConversationOut.from_doc(c)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, ctx: Viewer, db: DB):
    c = await service.get_conversation(db, ctx.workspace_id, ctx.user_id, conversation_id)
    msgs = await service.list_messages(db, c["_id"])
    return ConversationDetail(
        **ConversationOut.from_doc(c).model_dump(), messages=[MessageOut.from_doc(m) for m in msgs]
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: str, body: UpdateConversationIn, ctx: Viewer, db: DB
):
    c = await service.update_conversation(
        db, ctx.workspace_id, ctx.user_id, conversation_id, body.title, body.scope
    )
    return ConversationOut.from_doc(c)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, ctx: Viewer, db: DB) -> Response:
    await service.delete_conversation(db, ctx.workspace_id, ctx.user_id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _stream(gen) -> StreamingResponse:  # noqa: ANN001
    return StreamingResponse(gen, media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/{conversation_id}/messages", dependencies=[Depends(rate_limit("chat", 30, 60))])
async def send_message(
    conversation_id: str, body: SendMessageIn, ctx: Viewer, db: DB, settings: Config,
    vectors: Vectors, embedder: Embedder, reranker: RerankerDep, llm: LLM,
):  # fmt: skip
    """Ask a question in a conversation. Streams Server-Sent Events:
    user_message, title?, status*, retrieval, token*, final, error?, done."""
    require_ai_consent(ctx, settings)
    conv = await service.get_conversation(db, ctx.workspace_id, ctx.user_id, conversation_id)
    history = await service.list_messages(db, conv["_id"])
    pipe = RagPipeline(
        db=db, store=vectors, embedder=embedder, reranker=reranker, llm=llm, settings=settings
    )
    return _stream(
        service.stream_turn(
            db=db,
            pipeline=pipe,
            conv=conv,
            question=body.content,
            history_messages=history,
            slots=service.llm_slots(settings.llm_concurrency),
        )
    )


@router.post("/{conversation_id}/regenerate", dependencies=[Depends(rate_limit("chat", 30, 60))])
async def regenerate(
    conversation_id: str, ctx: Viewer, db: DB, settings: Config, vectors: Vectors,
    embedder: Embedder, reranker: RerankerDep, llm: LLM,
):  # fmt: skip
    """Replace the last assistant answer by generating it again for the same question."""
    require_ai_consent(ctx, settings)
    conv = await service.get_conversation(db, ctx.workspace_id, ctx.user_id, conversation_id)
    msgs = await service.list_messages(db, conv["_id"])
    if len(msgs) < 2 or msgs[-1]["role"] != "assistant" or msgs[-2]["role"] != "user":
        raise AppError(409, "nothing_to_regenerate", "There is no answer to regenerate")
    await db.messages.delete_one({"_id": msgs[-1]["_id"]})
    await db.conversations.update_one({"_id": conv["_id"]}, {"$inc": {"message_count": -1}})
    conv["message_count"] -= 1
    pipe = RagPipeline(
        db=db, store=vectors, embedder=embedder, reranker=reranker, llm=llm, settings=settings
    )
    return _stream(
        service.stream_turn(
            db=db,
            pipeline=pipe,
            conv=conv,
            question=msgs[-2]["content"],
            history_messages=msgs[:-2],
            slots=service.llm_slots(settings.llm_concurrency),
            save_user_message=False,
        )
    )


@router.put(
    "/{conversation_id}/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT
)
async def message_feedback(
    conversation_id: str, message_id: str, body: FeedbackIn, ctx: Viewer, db: DB
) -> Response:
    await service.set_feedback(
        db, ctx.workspace_id, ctx.user_id, conversation_id, message_id, body.rating, body.comment
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
