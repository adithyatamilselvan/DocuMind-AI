import pytest
from bson import ObjectId

from app.modules.documents import service
from app.modules.documents.states import TRANSITIONS, DocumentStatus, can_transition

from .conftest import first_workspace, register


async def seed(app, ws_id: str, user_id: str, n: int = 3, **over):
    db = app.state.db
    docs = []
    for i in range(n):
        d, _ = await service.create_document(
            db, workspace_id=ObjectId(ws_id), owner_id=ObjectId(user_id),
            filename=f"file{i}.pdf", title=over.get("title", f"Report {i}"),
            mime_type="application/pdf", size_bytes=1000 * (i + 1), sha256=f"{i:064d}",
            storage_key=f"k{i}", status=DocumentStatus.COMPLETED,
        )  # fmt: skip
        docs.append(d)
    return docs


async def setup(client, app):
    me = await register(client)
    ws = await first_workspace(client)
    return me, ws, f"/api/v1/workspaces/{ws['id']}"


def test_state_machine_rules():
    S = DocumentStatus
    assert can_transition(S.QUEUED, S.PROCESSING)
    assert can_transition(S.EXTRACTING, S.CHUNKING)  # OCR optional
    assert can_transition(S.FAILED, S.QUEUED)  # retry
    assert not can_transition(S.COMPLETED, S.EMBEDDING)
    assert not can_transition(S.UPLOADING, S.COMPLETED)
    assert all(S.FAILED in t for s, t in TRANSITIONS.items() if s not in {S.COMPLETED, S.FAILED})


async def test_set_status_is_guarded(client, app):
    me, ws, _ = await setup(client, app)
    (d,) = await seed(app, ws["id"], me["id"], 1)
    db = app.state.db
    assert not await service.set_status(db, d["_id"], DocumentStatus.EMBEDDING)  # illegal jump
    assert await service.set_status(db, d["_id"], DocumentStatus.QUEUED)
    assert await service.set_status(db, d["_id"], DocumentStatus.PROCESSING)
    assert (await db.documents.find_one({"_id": d["_id"]}))["status"] == "PROCESSING"


async def test_list_filter_sort_paginate(client, app):
    me, ws, base = await setup(client, app)
    docs = await seed(app, ws["id"], me["id"], 5)
    await client.patch(
        f"{base}/documents/{docs[0]['_id']}", json={"tags": ["Finance", "q1"], "category": "Report"}
    )
    r = await client.get(
        f"{base}/documents", params={"page_size": 2, "sort": "size_bytes", "order": "desc"}
    )
    body = r.json()
    assert body["total"] == 5 and [d["size_bytes"] for d in body["items"]] == [5000, 4000]
    page2 = (
        await client.get(
            f"{base}/documents",
            params={"page_size": 2, "page": 3, "sort": "size_bytes", "order": "desc"},
        )
    ).json()
    assert [d["size_bytes"] for d in page2["items"]] == [1000]
    assert (await client.get(f"{base}/documents", params={"tag": "finance"})).json()["total"] == 1
    assert (await client.get(f"{base}/documents", params={"category": "Report"})).json()[
        "total"
    ] == 1
    assert (await client.get(f"{base}/documents", params={"q": "report 3"})).json()["total"] == 1
    assert (await client.get(f"{base}/documents", params={"q": ".*"})).json()[
        "total"
    ] == 0  # regex escaped
    assert (await client.get(f"{base}/documents", params={"status": "FAILED"})).json()["total"] == 0
    assert (await client.get(f"{base}/documents", params={"page_size": 1000})).status_code == 422


async def test_update_normalizes_tags_and_validates_collections(client, app):
    me, ws, base = await setup(client, app)
    (d,) = await seed(app, ws["id"], me["id"], 1)
    r = await client.patch(
        f"{base}/documents/{d['_id']}",
        json={"tags": ["  Alpha ", "alpha", "BETA"], "title": " New "},
    )
    assert r.json()["tags"] == ["alpha", "beta"] and r.json()["title"] == "New"
    bad = await client.patch(
        f"{base}/documents/{d['_id']}", json={"collection_ids": [str(ObjectId())]}
    )
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_collection"


async def test_collections_crud_and_membership(client, app):
    me, ws, base = await setup(client, app)
    (d,) = await seed(app, ws["id"], me["id"], 1)
    c = (await client.post(f"{base}/collections", json={"name": "Contracts"})).json()
    child = await client.post(f"{base}/collections", json={"name": "2024", "parent_id": c["id"]})
    assert child.status_code == 201
    assert (await client.post(f"{base}/collections", json={"name": "Contracts"})).status_code == 409
    await client.patch(f"{base}/documents/{d['_id']}", json={"collection_ids": [c["id"]]})
    listing = (await client.get(f"{base}/collections")).json()
    assert {x["name"]: x["document_count"] for x in listing} == {"Contracts": 1, "2024": 0}
    assert (await client.get(f"{base}/documents", params={"collection_id": c["id"]})).json()[
        "total"
    ] == 1
    assert (await client.delete(f"{base}/collections/{c['id']}")).status_code == 409  # has child
    assert (await client.delete(f"{base}/collections/{child.json()['id']}")).status_code == 204
    assert (await client.delete(f"{base}/collections/{c['id']}")).status_code == 204
    assert (await client.get(f"{base}/documents/{d['_id']}")).json()["collection_ids"] == []


async def test_bulk_actions(client, app):
    me, ws, base = await setup(client, app)
    docs = await seed(app, ws["id"], me["id"], 3)
    ids = [str(d["_id"]) for d in docs]
    r = await client.post(
        f"{base}/documents/bulk", json={"action": "add_tags", "ids": ids, "tags": ["X"]}
    )
    assert r.json()["affected"] == 3
    assert (await client.get(f"{base}/documents", params={"tag": "x"})).json()["total"] == 3
    await client.post(
        f"{base}/documents/bulk", json={"action": "remove_tags", "ids": ids[:1], "tags": ["x"]}
    )
    assert (await client.get(f"{base}/documents", params={"tag": "x"})).json()["total"] == 2
    await client.post(
        f"{base}/documents/bulk", json={"action": "set_category", "ids": ids, "category": "Legal"}
    )
    assert (await client.get(f"{base}/documents", params={"category": "Legal"})).json()[
        "total"
    ] == 3
    assert (
        await client.post(f"{base}/documents/bulk", json={"action": "add_tags", "ids": ids})
    ).status_code == 400
    assert (
        await client.post(f"{base}/documents/bulk", json={"action": "delete", "ids": ids[:2]})
    ).json()["affected"] == 2
    assert (await client.get(f"{base}/documents")).json()["total"] == 1


async def test_delete_purges_chunks_and_insights_immediately(client, app):
    me, ws, base = await setup(client, app)
    (d,) = await seed(app, ws["id"], me["id"], 1)
    db = app.state.db
    await db.document_chunks.insert_one(
        {"workspace_id": ObjectId(ws["id"]), "document_id": d["_id"], "content": "secret"}
    )
    await db.document_insights.insert_one(
        {"workspace_id": ObjectId(ws["id"]), "document_id": d["_id"]}
    )
    assert (await client.delete(f"{base}/documents/{d['_id']}")).status_code == 204
    assert await db.document_chunks.count_documents({}) == 0
    assert await db.document_insights.count_documents({}) == 0
    assert (await client.get(f"{base}/documents/{d['_id']}")).status_code == 404
    assert (await client.delete(f"{base}/documents/{d['_id']}")).status_code == 404


async def test_viewer_cannot_modify_and_other_tenant_cannot_see(client, new_client, app):
    me, ws, base = await setup(client, app)
    (d,) = await seed(app, ws["id"], me["id"], 1)
    async with new_client() as other:
        await register(other, "b@example.com", "Bob")
        assert (await other.get(f"{base}/documents")).status_code == 404
        assert (await other.get(f"{base}/documents/{d['_id']}")).status_code == 404
        # member with viewer role: read ok, write forbidden
        await client.post(f"{base}/members", json={"email": "b@example.com", "role": "viewer"})
        assert (await other.get(f"{base}/documents")).json()["total"] == 1
        assert (
            await other.patch(f"{base}/documents/{d['_id']}", json={"title": "x"})
        ).status_code == 403
        assert (await other.delete(f"{base}/documents/{d['_id']}")).status_code == 403
        assert (
            await other.post(
                f"{base}/documents/bulk", json={"action": "delete", "ids": [str(d["_id"])]}
            )
        ).status_code == 403
        assert (await other.post(f"{base}/collections", json={"name": "x"})).status_code == 403
    # a document id from another workspace is not reachable via my workspace path
    r2 = await client.post("/api/v1/workspaces", json={"name": "Second"})
    other_base = f"/api/v1/workspaces/{r2.json()['id']}"
    assert (await client.get(f"{other_base}/documents/{d['_id']}")).status_code == 404


async def test_overview_is_derived_from_real_data(client, app):
    me, ws, base = await setup(client, app)
    empty = (await client.get(f"{base}/analytics/overview")).json()
    assert empty["total_documents"] == 0 and empty["processing_success_rate"] is None
    assert len(empty["usage_trend"]) == 30
    docs = await seed(app, ws["id"], me["id"], 3)
    db = app.state.db
    await service.set_status(db, docs[0]["_id"], DocumentStatus.QUEUED)
    await db.documents.update_one({"_id": docs[1]["_id"]}, {"$set": {"status": "FAILED"}})
    await client.get(f"{base}/documents/{docs[2]['_id']}")
    await client.post(
        f"{base}/documents/bulk",
        json={"action": "set_category", "ids": [str(docs[2]["_id"])], "category": "A"},
    )
    await db.usage_records.insert_one(
        {"workspace_id": ObjectId(ws["id"]), "kind": "chat", "tokens_in": 10, "tokens_out": 5,
         "created_at": __import__("app.core.ids", fromlist=["utcnow"]).utcnow()}
    )  # fmt: skip
    o = (await client.get(f"{base}/analytics/overview")).json()
    assert o["total_documents"] == 3 and o["completed_documents"] == 1
    assert o["failed_documents"] == 1 and o["in_progress_documents"] == 1
    assert o["processing_success_rate"] == 0.5
    assert o["storage_bytes"] == 6000
    assert o["top_documents"][0]["access_count"] == 1
    assert o["ai_requests_30d"] == 1 and o["ai_tokens_30d"] == 15
    assert o["recent_activity"] and o["recent_activity"][0]["actor_name"] == "Alice"


@pytest.mark.parametrize("path", ["documents", "collections", "analytics/overview"])
async def test_requires_auth(client, path):
    assert (await client.get(f"/api/v1/workspaces/{ObjectId()}/{path}")).status_code == 401
