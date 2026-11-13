from .conftest import first_workspace, register


async def test_tenant_isolation(client, new_client):
    await register(client, "a@example.com", "Alice")
    ws_a = await first_workspace(client)
    async with new_client() as other:
        await register(other, "b@example.com", "Bob")
        for method, path in [
            ("get", f"/api/v1/workspaces/{ws_a['id']}"),
            ("get", f"/api/v1/workspaces/{ws_a['id']}/members"),
            ("patch", f"/api/v1/workspaces/{ws_a['id']}"),
            ("delete", f"/api/v1/workspaces/{ws_a['id']}"),
        ]:
            r = await getattr(other, method)(
                path, **({"json": {"name": "x"}} if method == "patch" else {})
            )
            assert r.status_code == 404, (method, path, r.status_code)
        assert (await other.get("/api/v1/workspaces")).json()[0]["id"] != ws_a["id"]
    assert (await client.get("/api/v1/workspaces/not-an-id")).status_code == 404


async def test_rbac_matrix(client, new_client):
    await register(client, "owner@example.com", "Owner")
    ws = await first_workspace(client)
    base = f"/api/v1/workspaces/{ws['id']}"
    async with new_client() as viewer:
        await register(viewer, "viewer@example.com", "Viewer")
        r = await client.post(
            f"{base}/members", json={"email": "viewer@example.com", "role": "viewer"}
        )
        assert r.status_code == 201
        assert (await viewer.get(base)).status_code == 200
        assert (await viewer.patch(base, json={"name": "Hacked"})).status_code == 403
        assert (
            await viewer.post(f"{base}/members", json={"email": "owner@example.com"})
        ).status_code == 403
        assert (await viewer.delete(base)).status_code == 403
        # promote to admin: can edit, still can't delete or grant owner
        uid = r.json()["user_id"]
        assert (
            await client.patch(f"{base}/members/{uid}", json={"role": "admin"})
        ).status_code == 204
        assert (await viewer.patch(base, json={"name": "Renamed"})).status_code == 200
        assert (await viewer.delete(base)).status_code == 403
        self_promote = await viewer.patch(f"{base}/members/{uid}", json={"role": "owner"})
        assert self_promote.status_code == 403


async def test_last_owner_protected(client):
    me = await register(client)
    ws = await first_workspace(client)
    base = f"/api/v1/workspaces/{ws['id']}"
    r = await client.patch(f"{base}/members/{me['id']}", json={"role": "admin"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "last_owner"
    assert (await client.delete(f"{base}/members/{me['id']}")).status_code == 400


async def test_member_can_leave_but_not_remove_others(client, new_client):
    await register(client, "owner@example.com", "Owner")
    owner = (await client.get("/api/v1/auth/me")).json()
    ws = await first_workspace(client)
    base = f"/api/v1/workspaces/{ws['id']}"
    async with new_client() as m:
        mem = await register(m, "m@example.com", "M")
        await client.post(f"{base}/members", json={"email": "m@example.com", "role": "editor"})
        assert (await m.delete(f"{base}/members/{owner['id']}")).status_code == 403
        assert (await m.delete(f"{base}/members/{mem['id']}")).status_code == 204
        assert (await m.get(base)).status_code == 404


async def test_deleted_workspace_is_inaccessible(client):
    await register(client)
    ws = await first_workspace(client)
    assert (await client.delete(f"/api/v1/workspaces/{ws['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/workspaces/{ws['id']}")).status_code == 404
    assert (await client.get("/api/v1/workspaces")).json() == []


async def test_ai_consent_setting_and_audit_log(client, app):
    await register(client)
    ws = await first_workspace(client)
    assert ws["settings"]["ai_processing_consent"] is False
    r = await client.patch(
        f"/api/v1/workspaces/{ws['id']}", json={"settings": {"ai_processing_consent": True}}
    )
    assert r.json()["settings"]["ai_processing_consent"] is True
    actions = [a["action"] async for a in app.state.db.audit_logs.find({})]
    assert "auth.register" in actions and "workspace.update" in actions
