from datetime import timedelta
from typing import Any

from bson import ObjectId
from pydantic import BaseModel
from pymongo.asynchronous.database import AsyncDatabase

from app.core.ids import utcnow
from app.modules.documents.states import IN_PROGRESS


class CountItem(BaseModel):
    label: str
    count: int


class ActivityItem(BaseModel):
    action: str
    actor_name: str | None
    target: dict[str, Any]
    created_at: str


class TopDocument(BaseModel):
    id: str
    title: str
    access_count: int


class UsagePoint(BaseModel):
    date: str
    requests: int
    tokens: int


class Overview(BaseModel):
    total_documents: int
    completed_documents: int
    failed_documents: int
    in_progress_documents: int
    processing_success_rate: float | None
    storage_bytes: int
    knowledge_bases: int
    conversations: int
    by_status: list[CountItem]
    categories: list[CountItem]
    top_documents: list[TopDocument]
    recent_activity: list[ActivityItem]
    usage_trend: list[UsagePoint]
    ai_requests_30d: int
    ai_tokens_30d: int


async def overview(db: AsyncDatabase, workspace_id: ObjectId) -> Overview:
    live = {"workspace_id": workspace_id, "deleted_at": None}

    by_status: dict[str, int] = {}
    storage = 0
    async for row in await db.documents.aggregate(
        [
            {"$match": live},
            {"$group": {"_id": "$status", "n": {"$sum": 1}, "bytes": {"$sum": "$size_bytes"}}},
        ]
    ):
        by_status[row["_id"]] = row["n"]
        storage += row["bytes"]
    total = sum(by_status.values())
    completed = by_status.get("COMPLETED", 0)
    failed = by_status.get("FAILED", 0)
    in_progress = sum(n for s, n in by_status.items() if s in {x.value for x in IN_PROGRESS})
    finished = completed + failed

    categories = [
        CountItem(label=r["_id"] or "Uncategorized", count=r["n"])
        async for r in await db.documents.aggregate(
            [
                {"$match": live},
                {"$group": {"_id": "$category", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": 12},
            ]
        )
    ]
    top = [
        TopDocument(id=str(d["_id"]), title=d["title"], access_count=d["access_count"])
        async for d in db.documents.find({**live, "access_count": {"$gt": 0}})
        .sort("access_count", -1)
        .limit(5)
    ]

    logs = [
        a
        async for a in db.audit_logs.find({"workspace_id": workspace_id})
        .sort("created_at", -1)
        .limit(10)
    ]
    actors = {
        u["_id"]: u["name"]
        async for u in db.users.find(
            {"_id": {"$in": [a["actor_id"] for a in logs if a.get("actor_id")]}}
        )
    }
    activity = [
        ActivityItem(
            action=a["action"],
            actor_name=actors.get(a.get("actor_id")),
            target=a.get("target", {}),
            created_at=a["created_at"].isoformat(),
        )  # fmt: skip
        for a in logs
    ]

    since = (utcnow() - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    daily: dict[str, tuple[int, int]] = {}
    async for r in await db.usage_records.aggregate(
        [
            {"$match": {"workspace_id": workspace_id, "created_at": {"$gte": since}}},
            {
                "$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "n": {"$sum": 1},
                    "tokens": {
                        "$sum": {
                            "$add": [
                                {"$ifNull": ["$tokens_in", 0]},
                                {"$ifNull": ["$tokens_out", 0]},
                            ]
                        }
                    },
                }
            },
        ]
    ):
        daily[r["_id"]] = (r["n"], r["tokens"])
    trend = []
    for i in range(30):
        day = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        n, t = daily.get(day, (0, 0))
        trend.append(UsagePoint(date=day, requests=n, tokens=t))

    return Overview(
        total_documents=total, completed_documents=completed, failed_documents=failed,
        in_progress_documents=in_progress,
        processing_success_rate=round(completed / finished, 4) if finished else None,
        storage_bytes=storage,
        knowledge_bases=await db.knowledge_bases.count_documents({**live}),
        conversations=await db.conversations.count_documents({"workspace_id": workspace_id}),
        by_status=[CountItem(label=k, count=v) for k, v in sorted(by_status.items())],
        categories=categories, top_documents=top, recent_activity=activity, usage_trend=trend,
        ai_requests_30d=sum(p.requests for p in trend), ai_tokens_30d=sum(p.tokens for p in trend),
    )  # fmt: skip
