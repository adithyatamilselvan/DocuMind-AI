from datetime import timedelta

from bson import ObjectId

from app.core.ids import utcnow

from .conftest import register
from .test_rag_api import FIN_BIO, setup


async def test_kb_crud_membership_status_and_scoped_retrieval(client, app, ai):
    ws, base, (fin, bio) = await setup(client, app, FIN_BIO)
    kb = (
        await client.post(
            f"{base}/knowledge-bases", json={"name": "Finance KB", "description": "d"}
        )
    ).json()
    assert kb["document_count"] == 0 and kb["index_status"] == "empty"
    assert (
        await client.post(f"{base}/knowledge-bases", json={"name": "Finance KB"})
    ).status_code == 409
    bad = await client.post(
        f"{base}/knowledge-bases/{kb['id']}/documents", json={"document_ids": [str(ObjectId())]}
    )
    assert bad.status_code == 400
    r = await client.post(
        f"{base}/knowledge-bases/{kb['id']}/documents", json={"document_ids": [fin]}
    )
    assert r.json()["document_count"] == 1 and r.json()["index_status"] == "ready"
    detail = (await client.get(f"{base}/knowledge-bases/{kb['id']}")).json()
    assert (
        detail["status_counts"] == {"COMPLETED": 1} and detail["documents"][0]["title"] == "finance"
    )

    # independent search and question answering through the KB scope
    f = {"knowledge_base_ids": [kb["id"]]}
    out = await client.post(
        f"{base}/search", json={"query": "mitochondria energy", "mode": "keyword", "filters": f}
    )
    assert out.json()["hits"] == []  # biology is outside the KB
    out = await client.post(
        f"{base}/search", json={"query": "revenue", "mode": "keyword", "filters": f}
    )
    assert {h["document_id"] for h in out.json()["hits"]} == {fin}
    ans = (
        await client.post(
            f"{base}/ask", json={"question": "How did revenue grow in Europe?", "filters": f}
        )
    ).json()
    assert ans["grounded"] and ans["citations"][0]["document_id"] == fin
    miss = await client.post(
        f"{base}/ask", json={"question": "Calvin cycle photosynthesis chloroplasts", "filters": f}
    )
    assert miss.json()["insufficient_evidence"]

    c = (await client.post(f"{base}/conversations", json={"scope": f})).json()
    assert c["scope"]["knowledge_base_ids"] == [kb["id"]]

    renamed = await client.patch(f"{base}/knowledge-bases/{kb['id']}", json={"name": "Renamed"})
    assert renamed.json()["name"] == "Renamed"
    assert (
        await client.delete(f"{base}/knowledge-bases/{kb['id']}/documents/{fin}")
    ).status_code == 204
    assert (await client.get(f"{base}/knowledge-bases/{kb['id']}")).json()["document_count"] == 0
    assert (await client.delete(f"{base}/knowledge-bases/{kb['id']}")).status_code == 204
    assert (await client.get(f"{base}/knowledge-bases/{kb['id']}")).status_code == 404
    assert (await client.get(f"{base}/documents/{fin}")).status_code == 200  # documents untouched


async def test_deleting_a_document_removes_it_from_knowledge_bases(client, app, ai):
    ws, base, (fin, _) = await setup(client, app, FIN_BIO)
    kb = (await client.post(f"{base}/knowledge-bases", json={"name": "K"})).json()
    await client.post(f"{base}/knowledge-bases/{kb['id']}/documents", json={"document_ids": [fin]})
    await client.delete(f"{base}/documents/{fin}")
    assert (await client.get(f"{base}/knowledge-bases/{kb['id']}")).json()["document_count"] == 0


async def test_kb_status_reflects_failures_and_reindex_rebuilds_chunks(client, app, ai):
    ws, base, (fin, bio) = await setup(client, app, FIN_BIO)
    kb = (await client.post(f"{base}/knowledge-bases", json={"name": "K"})).json()
    await client.post(
        f"{base}/knowledge-bases/{kb['id']}/documents", json={"document_ids": [fin, bio]}
    )
    await app.state.db.documents.update_one({"_id": ObjectId(bio)}, {"$set": {"status": "FAILED"}})
    assert (await client.get(f"{base}/knowledge-bases/{kb['id']}")).json()[
        "index_status"
    ] == "partial"
    before = {
        c["chunk_id"]
        async for c in app.state.db.document_chunks.find({"document_id": ObjectId(fin)})
    }
    r = await client.post(f"{base}/knowledge-bases/{kb['id']}/reindex")
    assert r.status_code == 202 and r.json()["queued"] == 2
    await app.state.queue.drain()
    assert (await client.get(f"{base}/knowledge-bases/{kb['id']}")).json()[
        "index_status"
    ] == "ready"
    after = {
        c["chunk_id"]
        async for c in app.state.db.document_chunks.find({"document_id": ObjectId(fin)})
    }
    assert after and after == before  # same version -> same deterministic chunk ids, rebuilt


async def test_kb_permissions_and_isolation(client, new_client, app, ai):
    ws, base, (fin, _) = await setup(client, app, FIN_BIO)
    kb = (await client.post(f"{base}/knowledge-bases", json={"name": "K"})).json()
    async with new_client() as v:
        await register(v, "v@example.com", "V")
        await client.post(f"{base}/members", json={"email": "v@example.com", "role": "viewer"})
        assert len((await v.get(f"{base}/knowledge-bases")).json()) == 1
        assert (await v.post(f"{base}/knowledge-bases", json={"name": "X"})).status_code == 403
        assert (await v.delete(f"{base}/knowledge-bases/{kb['id']}")).status_code == 403
        assert (await v.post(f"{base}/knowledge-bases/{kb['id']}/reindex")).status_code == 403
    async with new_client() as o:
        await register(o, "o@example.com", "O")
        assert (await o.get(f"{base}/knowledge-bases")).status_code == 404
        ows = (await o.get("/api/v1/workspaces")).json()[0]["id"]
        r = await o.post(
            f"/api/v1/workspaces/{ows}/search",
            json={
                "query": "revenue",
                "mode": "keyword",
                "filters": {"knowledge_base_ids": [kb["id"]]},
            },
        )
        assert r.json()["hits"] == []  # another workspace cannot use this KB id as a scope


async def test_search_history_and_date_filter(client, app, ai):
    ws, base, _ = await setup(client, app, FIN_BIO)
    for q, m in (("revenue", "keyword"), ("revenue", "keyword"), ("mitochondria", "hybrid")):
        await client.post(f"{base}/search", json={"query": q, "mode": m})
    h = (await client.get(f"{base}/search/history")).json()
    assert [(x["query"], x["mode"]) for x in h] == [
        ("mitochondria", "hybrid"),
        ("revenue", "keyword"),
    ]
    assert h[1]["results"] >= 1
    future = (utcnow() + timedelta(days=1)).isoformat()
    past = (utcnow() - timedelta(days=1)).isoformat()
    none = await client.post(
        f"{base}/search",
        json={"query": "revenue", "mode": "keyword", "filters": {"created_from": future}},
    )
    some = await client.post(
        f"{base}/search",
        json={"query": "revenue", "mode": "keyword", "filters": {"created_from": past}},
    )
    assert none.json()["hits"] == [] and some.json()["hits"]
    assert (await client.delete(f"{base}/search/history")).status_code == 204
    assert (await client.get(f"{base}/search/history")).json() == []


async def test_search_filters_by_category_tag_and_type(client, app, ai):
    ws, base, (fin, bio) = await setup(client, app, FIN_BIO)
    await client.patch(f"{base}/documents/{fin}", json={"category": "Finance", "tags": ["q1"]})

    async def hits(query, **filters):
        r = await client.post(
            f"{base}/search", json={"query": query, "mode": "keyword", "filters": filters}
        )
        return r.json()["hits"]

    assert {h["document_id"] for h in await hits("revenue", category="Finance")} == {fin}
    assert await hits("revenue", category="Legal") == []
    assert await hits("revenue", tags=["q1"])
    assert await hits("mitochondria", mime_type="application/pdf") == []  # biology is a DOCX
