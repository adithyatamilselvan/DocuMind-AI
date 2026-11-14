from bson import ObjectId

from .conftest import enable_ai, register
from .test_rag_api import FIN_BIO, setup


async def test_audit_log_is_admin_only_filterable_and_paginated(client, new_client, app, ai):
    ws, base, (fin, bio) = await setup(client, app, FIN_BIO)
    await client.delete(f"{base}/documents/{bio}")
    r = (await client.get(f"{base}/analytics/audit-logs")).json()
    actions = [e["action"] for e in r["items"]]
    assert (
        r["total"] >= 5
        and "document.upload" in actions
        and "document.delete" in actions
        and "workspace.update" in actions
    )
    assert all(
        e["actor_name"] == "Alice" for e in r["items"] if e["action"].startswith("document.")
    )
    assert actions[0] == "document.delete"  # newest first
    only = (await client.get(f"{base}/analytics/audit-logs", params={"action": "document."})).json()
    assert {e["action"] for e in only["items"]} == {"document.upload", "document.delete"}
    page = (
        await client.get(f"{base}/analytics/audit-logs", params={"page_size": 2, "page": 2})
    ).json()
    assert len(page["items"]) == 2 and page["page"] == 2 and page["total"] == r["total"]
    async with new_client() as v:
        await register(v, "v@example.com", "V")
        await client.post(f"{base}/members", json={"email": "v@example.com", "role": "editor"})
        assert (await v.get(f"{base}/analytics/audit-logs")).status_code == 403
        assert (await v.get(f"{base}/analytics/usage")).status_code == 403
    async with new_client() as o:
        await register(o, "o@example.com", "O")
        assert (await o.get(f"{base}/analytics/audit-logs")).status_code == 404


async def test_ai_actions_are_audited(client, app, ai):
    ws, base, (a, b) = await setup(client, app, FIN_BIO)
    await client.post(f"{base}/research/papers", json={"document_id": a})
    await client.post(f"{base}/comparisons", json={"document_ids": [a, b]})
    await client.post(f"{base}/reports", json={"type": "document_summary", "document_ids": [a]})
    await client.post(f"{base}/knowledge-bases", json={"name": "K"})
    await app.state.queue.drain()
    got = {
        e["action"]
        for e in (
            await client.get(f"{base}/analytics/audit-logs", params={"page_size": 100})
        ).json()["items"]
    }
    assert {"research.paper", "comparison.documents", "report.create", "kb.create"} <= got


async def test_usage_report_aggregates_real_records(client, app, ai):
    ws, base, (fin, _) = await setup(client, app, FIN_BIO)
    await client.post(f"{base}/ask", json={"question": "How did revenue grow in Europe?"})
    u = (await client.get(f"{base}/analytics/usage")).json()
    kinds = {r["kind"] for r in u["totals"]}
    assert {"embedding", "insight", "chat"} <= kinds
    assert u["requests"] == sum(r["requests"] for r in u["totals"]) and u["tokens_in"] > 0
    assert u["by_user"] and u["by_user"][0]["name"] in ("Alice", None)
    assert (await client.get(f"{base}/analytics/usage", params={"days": 1})).json()[
        "requests"
    ] == u["requests"]
    assert (
        await client.get(f"{base}/analytics/usage", params={"days": 0})
    ).status_code == 200  # clamped


async def test_export_contains_own_data_and_no_secrets(client, new_client, app, ai):
    ws, base, _ = await setup(client, app, FIN_BIO)
    c = (await client.post(f"{base}/conversations", json={})).json()
    await client.post(
        f"{base}/conversations/{c['id']}/messages",
        json={"content": "How did revenue grow in Europe?"},
    )
    async with new_client() as other:
        await register(other, "o@example.com", "Other")
    e = (await client.get("/api/v1/users/me/export")).json()
    assert e["user"]["email"] == "a@example.com" and "password_hash" not in e["user"]
    assert len(e["workspaces"]) == 1 and len(e["documents"]) == 2 and len(e["conversations"]) == 1
    assert (
        [m["role"] for m in e["messages"]] == ["user", "assistant"]
        and e["usage_records"]
        and e["audit_logs"]
    )
    assert "o@example.com" not in str(e)  # nothing about other users


async def test_workspace_delete_purges_everything_including_files(client, new_client, app, ai):
    ws, base, (fin, bio) = await setup(client, app, FIN_BIO)
    await client.post(f"{base}/research/papers", json={"document_id": fin})
    rep = (
        await client.post(
            f"{base}/reports", json={"type": "document_summary", "document_ids": [fin]}
        )
    ).json()
    await client.post(f"{base}/conversations", json={})
    await app.state.queue.drain()
    db, store = app.state.db, app.state.store
    keys = [v["storage_key"] async for v in db.document_versions.find({})]
    keys += [
        e["storage_key"]
        for e in (await db.reports.find_one({"_id": ObjectId(rep["id"])}))["exports"]
    ]
    assert keys and all([await store.exists(k) for k in keys])
    async with new_client() as other:  # a second tenant that must stay untouched
        await register(other, "o@example.com", "Other")
        ows = (await other.get("/api/v1/workspaces")).json()[0]["id"]
        await enable_ai(other, ows)
        from .helpers import make_docx
        from .test_indexing import upload as up

        other_doc = await up(
            other,
            f"/api/v1/workspaces/{ows}",
            "keep.docx",
            make_docx([("Normal", "Other tenant content about astronomy planets.")]),
        )
        await app.state.queue.drain()
        assert (await client.delete(f"/api/v1/workspaces/{ws['id']}")).status_code == 204
        for coll in (
            "documents",
            "document_versions",
            "document_chunks",
            "document_insights",
            "research_analyses",
            "reports",
            "conversations",
            "processing_jobs",
            "usage_records",
        ):
            assert await db[coll].count_documents({"workspace_id": ObjectId(ws["id"])}) == 0, coll
        assert not any([await store.exists(k) for k in keys])
        assert await db.workspaces.count_documents({"_id": ObjectId(ws["id"])}) == 0
        assert (
            await other.get(f"/api/v1/workspaces/{ows}/documents/{other_doc}")
        ).status_code == 200
        assert await db.document_chunks.count_documents({"workspace_id": ObjectId(ows)}) > 0


async def test_account_deletion_requires_password_and_handles_shared_workspaces(
    client, new_client, app, ai
):
    ws, base, (fin, _) = await setup(client, app, FIN_BIO)
    me = (await client.get("/api/v1/auth/me")).json()
    assert (
        await client.request("DELETE", "/api/v1/users/me", json={"password": "wrong-password-1"})
    ).status_code == 400
    async with new_client() as m:
        await register(m, "m@example.com", "Member")
        await client.post(f"{base}/members", json={"email": "m@example.com", "role": "editor"})
        blocked = await client.request(
            "DELETE", "/api/v1/users/me", json={"password": "correct-horse-9"}
        )
        assert (
            blocked.status_code == 409
            and blocked.json()["error"]["code"] == "owns_shared_workspaces"
        )
        assert ws["id"] in blocked.json()["error"]["details"]["workspace_ids"]
        # after making the other member an owner, deletion succeeds and the shared workspace survives
        mid = (await m.get("/api/v1/auth/me")).json()["id"]
        assert (
            await client.patch(f"{base}/members/{mid}", json={"role": "owner"})
        ).status_code == 204
        ok = await client.request(
            "DELETE", "/api/v1/users/me", json={"password": "correct-horse-9"}
        )
        assert ok.status_code == 204
        assert (
            await m.get(f"{base}/documents")
        ).status_code == 200  # workspace and data remain for the new owner
    assert await app.state.db.users.count_documents({"_id": ObjectId(me["id"])}) == 0
    assert await app.state.db.conversations.count_documents({"user_id": ObjectId(me["id"])}) == 0
    assert (
        await app.state.db.audit_logs.count_documents({"actor_id": ObjectId(me["id"])}) == 0
    )  # anonymised
    assert (await client.get("/api/v1/auth/me")).status_code == 401  # session gone


async def test_account_deletion_purges_solo_workspaces(client, app, ai):
    ws, base, _ = await setup(client, app, FIN_BIO)
    keys = [v["storage_key"] async for v in app.state.db.document_versions.find({})]
    assert (
        await client.request("DELETE", "/api/v1/users/me", json={"password": "correct-horse-9"})
    ).status_code == 204
    assert (
        await app.state.db.documents.count_documents({}) == 0
        and await app.state.db.document_chunks.count_documents({}) == 0
    )
    assert not any([await app.state.store.exists(k) for k in keys])
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": "a@example.com", "password": "correct-horse-9"}
        )
    ).status_code == 401
