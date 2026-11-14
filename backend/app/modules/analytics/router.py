from typing import Annotated

from fastapi import APIRouter, Depends

from app.modules.analytics import service
from app.modules.analytics.service import Overview
from app.modules.auth.deps import DB
from app.modules.workspaces.deps import WorkspaceContext, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/analytics", tags=["analytics"])


@router.get("/overview", response_model=Overview)
async def overview(ctx: Annotated[WorkspaceContext, Depends(viewer_ctx)], db: DB):
    return await service.overview(db, ctx.workspace_id)


# ---- audit log and usage (admin) ----

from datetime import datetime  # noqa: E402
from typing import Any  # noqa: E402

from pydantic import BaseModel  # noqa: E402

from app.core.pagination import Page, PageParams  # noqa: E402
from app.modules.workspaces.deps import admin_ctx  # noqa: E402

Admin = Annotated[WorkspaceContext, Depends(admin_ctx)]


class AuditEntry(BaseModel):
    id: str
    action: str
    actor_name: str | None
    target: dict[str, Any]
    ip: str | None
    created_at: datetime


@router.get("/audit-logs", response_model=Page[AuditEntry])
async def audit_logs(
    ctx: Admin,
    db: DB,
    paging: Annotated[PageParams, Depends()],
    action: str | None = None,
    actor_id: str | None = None,
):
    """Workspace audit trail (admins only)."""
    from app.core.ids import to_oid

    q: dict[str, Any] = {"workspace_id": ctx.workspace_id}
    if action:
        import re as _re

        q["action"] = {"$regex": "^" + _re.escape(action)}
    if actor_id:
        q["actor_id"] = to_oid(actor_id, "User")
    total = await db.audit_logs.count_documents(q)
    rows = [
        a
        async for a in db.audit_logs.find(q)
        .sort("created_at", -1)
        .skip(paging.skip)
        .limit(paging.page_size)
    ]
    names = {
        u["_id"]: u["name"]
        async for u in db.users.find(
            {"_id": {"$in": [a["actor_id"] for a in rows if a.get("actor_id")]}}
        )
    }
    items = [
        AuditEntry(
            id=str(a["_id"]),
            action=a["action"],
            actor_name=names.get(a.get("actor_id")),
            target=a.get("target", {}),
            ip=a.get("ip"),
            created_at=a["created_at"],
        )  # fmt: skip
        for a in rows
    ]
    return Page[AuditEntry](items=items, total=total, page=paging.page, page_size=paging.page_size)


class UsageRow(BaseModel):
    kind: str
    provider: str
    model: str
    requests: int
    tokens_in: int
    tokens_out: int


class UserUsage(BaseModel):
    user_id: str | None
    name: str | None
    requests: int
    tokens: int


class UsageOut(BaseModel):
    since: datetime
    totals: list[UsageRow]
    by_user: list[UserUsage]
    requests: int
    tokens_in: int
    tokens_out: int


@router.get("/usage", response_model=UsageOut)
async def usage(ctx: Admin, db: DB, days: int = 30):
    """AI usage in the last `days` days, by kind/provider/model and by user (admins only)."""
    from datetime import timedelta

    from app.core.ids import utcnow

    since = utcnow() - timedelta(days=max(1, min(days, 365)))
    match = {"$match": {"workspace_id": ctx.workspace_id, "created_at": {"$gte": since}}}
    rows = [
        UsageRow(kind=r["_id"]["k"], provider=r["_id"]["p"], model=r["_id"]["m"], requests=r["n"], tokens_in=r["ti"], tokens_out=r["to"])
        async for r in await db.usage_records.aggregate([
            match,
            {"$group": {"_id": {"k": "$kind", "p": "$provider", "m": "$model"}, "n": {"$sum": 1},
                        "ti": {"$sum": {"$ifNull": ["$tokens_in", 0]}}, "to": {"$sum": {"$ifNull": ["$tokens_out", 0]}}}},
            {"$sort": {"n": -1}},
        ])
    ]  # fmt: skip
    per_user = [r async for r in await db.usage_records.aggregate([
        match,
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}, "t": {"$sum": {"$add": [{"$ifNull": ["$tokens_in", 0]}, {"$ifNull": ["$tokens_out", 0]}]}}}},
        {"$sort": {"t": -1}},
    ])]  # fmt: skip
    names = {
        u["_id"]: u["name"]
        async for u in db.users.find({"_id": {"$in": [r["_id"] for r in per_user if r["_id"]]}})
    }
    return UsageOut(
        since=since, totals=rows,
        by_user=[UserUsage(user_id=str(r["_id"]) if r["_id"] else None, name=names.get(r["_id"]), requests=r["n"], tokens=r["t"]) for r in per_user],
        requests=sum(r.requests for r in rows), tokens_in=sum(r.tokens_in for r in rows), tokens_out=sum(r.tokens_out for r in rows),
    )  # fmt: skip
