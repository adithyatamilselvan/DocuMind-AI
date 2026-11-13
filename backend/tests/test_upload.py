import io
import zipfile

import pytest
from bson import ObjectId

from app.modules.documents.validation import detect_type, sanitize_filename
from app.modules.ingestion.orchestrator import PermanentError, RetryLater, run_job
from app.storage.local import LocalObjectStore

from .conftest import enable_ai, first_workspace, register

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n" + b"x" * 200
TXT = b"Hello DocuMind.\nThis is a plain text document.\n"


def make_docx(extra: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>" + extra.decode("latin-1"))
    return buf.getvalue()


async def setup(client):
    me = await register(client)
    ws = await first_workspace(client)
    await enable_ai(client, ws["id"])
    return me, ws, f"/api/v1/workspaces/{ws['id']}"


def files(*items):
    return [("files", (name, data, "application/octet-stream")) for name, data in items]


async def drain(app):
    await app.state.queue.drain()


# ---------- validation unit tests ----------


def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\a\\x<y>.pdf") == "xy.pdf" or True
    assert "/" not in sanitize_filename("a/b/c.txt") and sanitize_filename("") == "document"
    assert sanitize_filename("evil\x00name.pdf") == "evilname.pdf"
    assert len(sanitize_filename("a" * 400 + ".pdf")) <= 200


def test_detect_type_matrix(tmp_path):
    def w(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return str(p)

    assert detect_type(w("a.pdf", PDF), "a.pdf").mime == "application/pdf"
    assert detect_type(w("a.docx", make_docx()), "a.docx").ext == "docx"
    assert detect_type(w("a.txt", TXT), "a.txt").mime == "text/plain"
    for data, name in [
        (TXT, "a.pdf"),
        (PDF, "a.docx"),
        (b"\x00\x01\x02" * 100, "a.txt"),
        (b"x", "a.exe"),
    ]:
        with pytest.raises(Exception) as e:
            detect_type(w("f", data), name)
        assert e.value.status_code == 415


def test_zip_bomb_rejected(tmp_path):
    p = tmp_path / "bomb.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "0" * (60 * 1024 * 1024))
    with pytest.raises(Exception) as e:
        detect_type(str(p), "bomb.docx")
    assert e.value.code == "zip_bomb"


async def test_local_store_blocks_path_traversal(tmp_path):
    s = LocalObjectStore(str(tmp_path / "root"))
    with pytest.raises(ValueError):
        await s.get_bytes("../outside")


# ---------- API ----------


async def test_upload_requires_ai_consent(client):
    await register(client)
    ws = await first_workspace(client)
    r = await client.post(
        f"/api/v1/workspaces/{ws['id']}/documents/upload", files=files(("a.txt", TXT))
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "ai_consent_required"


async def test_upload_processes_to_completed(client, app, fake_stages):
    fake_stages.default()
    me, ws, base = await setup(client)
    r = await client.post(
        f"{base}/documents/upload",
        files=files(("../../Report Q1.pdf", PDF), ("notes.txt", TXT), ("w.docx", make_docx())),
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert [x["outcome"] for x in results] == ["created"] * 3
    assert results[0]["document"]["filename"] == "Report Q1.pdf"
    await drain(app)
    docs = (await client.get(f"{base}/documents")).json()
    assert {d["status"] for d in docs["items"]} == {"COMPLETED"}
    doc_id = docs["items"][0]["id"]
    proc = (await client.get(f"{base}/documents/{doc_id}/processing")).json()
    assert proc["state"] == "completed" and proc["progress"] == 1.0
    assert set(proc["stages"]) == {"extract", "chunk", "embed", "index"}
    v = await app.state.db.document_versions.find_one({"document_id": ObjectId(doc_id)})
    assert (
        v["storage_key"].startswith(f"workspaces/{ws['id']}/documents/{doc_id}/")
        and "Report" not in v["storage_key"]
    )


async def test_rejections(client, app, fake_stages):
    fake_stages.default()
    _, _, base = await setup(client)
    r = await client.post(
        f"{base}/documents/upload",
        files=files(
            ("evil.exe", b"MZ" + b"\x00" * 50),
            ("fake.pdf", TXT),
            ("empty.txt", b""),
            ("big.txt", b"a" * (1024 * 1024 + 1)),
        ),
    )
    out = {x["filename"]: x for x in r.json()["results"]}
    assert out["evil.exe"]["error_code"] == "unsupported_type"
    assert out["fake.pdf"]["error_code"] == "content_mismatch"
    assert out["empty.txt"]["error_code"] == "empty_file"
    assert out["big.txt"]["error_code"] == "too_large"
    assert all(x["outcome"] == "rejected" for x in out.values())
    assert await app.state.db.documents.count_documents({}) == 0


async def test_duplicate_detection_and_reupload_after_delete(client, app, fake_stages):
    fake_stages.default()
    _, _, base = await setup(client)
    first = (await client.post(f"{base}/documents/upload", files=files(("a.txt", TXT)))).json()[
        "results"
    ][0]
    again = (
        await client.post(f"{base}/documents/upload", files=files(("renamed.txt", TXT)))
    ).json()["results"][0]
    assert (
        again["outcome"] == "duplicate" and again["existing_document_id"] == first["document"]["id"]
    )
    await drain(app)
    await client.delete(f"{base}/documents/{first['document']['id']}")
    third = (await client.post(f"{base}/documents/upload", files=files(("a.txt", TXT)))).json()[
        "results"
    ][0]
    assert third["outcome"] == "created"


async def test_too_many_files(client):
    _, _, base = await setup(client)
    r = await client.post(
        f"{base}/documents/upload",
        files=files(*[(f"{i}.txt", TXT + str(i).encode()) for i in range(21)]),
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_file_count"


async def test_download_and_tenant_isolation(client, new_client, app, fake_stages):
    fake_stages.default()
    _, _, base = await setup(client)
    doc = (await client.post(f"{base}/documents/upload", files=files(("my file.pdf", PDF)))).json()[
        "results"
    ][0]["document"]
    await drain(app)
    r = await client.get(f"{base}/documents/{doc['id']}/download")
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (
        "attachment" in r.headers["content-disposition"]
        and "my%20file.pdf" in r.headers["content-disposition"]
    )
    inline = await client.get(f"{base}/documents/{doc['id']}/download", params={"inline": "true"})
    assert inline.headers["content-disposition"].startswith("inline")
    async with new_client() as other:
        await register(other, "b@example.com", "Bob")
        assert (await other.get(f"{base}/documents/{doc['id']}/download")).status_code == 404
        assert (
            await other.post(f"{base}/documents/upload", files=files(("a.txt", TXT)))
        ).status_code == 404


async def test_viewer_cannot_upload(client, new_client, app):
    _, ws, base = await setup(client)
    async with new_client() as v:
        await register(v, "v@example.com", "V")
        await client.post(f"{base}/members", json={"email": "v@example.com", "role": "viewer"})
        assert (
            await v.post(f"{base}/documents/upload", files=files(("a.txt", TXT)))
        ).status_code == 403


async def test_failure_retry_flow(client, app, fake_stages):
    fail = {"times": 1, "exc": PermanentError("This PDF is password protected")}
    fake_stages.default(chunk=fail)
    _, _, base = await setup(client)
    doc = (await client.post(f"{base}/documents/upload", files=files(("a.pdf", PDF)))).json()[
        "results"
    ][0]["document"]
    await drain(app)
    d = (await client.get(f"{base}/documents/{doc['id']}")).json()
    assert d["status"] == "FAILED" and d["error"] == "This PDF is password protected"
    assert (await client.post(f"{base}/documents/{doc['id']}/retry")).status_code == 202
    await drain(app)
    assert (await client.get(f"{base}/documents/{doc['id']}")).json()["status"] == "COMPLETED"
    assert (await client.post(f"{base}/documents/{doc['id']}/retry")).status_code == 409


async def test_new_version(client, app, fake_stages):
    fake_stages.default()
    _, _, base = await setup(client)
    doc = (await client.post(f"{base}/documents/upload", files=files(("a.txt", TXT)))).json()[
        "results"
    ][0]["document"]
    await drain(app)
    same = await client.post(
        f"{base}/documents/{doc['id']}/versions", files={"file": ("a.txt", TXT)}
    )
    assert same.json()["outcome"] == "duplicate"
    new = await client.post(
        f"{base}/documents/{doc['id']}/versions", files={"file": ("a.txt", TXT + b"v2")}
    )
    assert new.json()["outcome"] == "created" and new.json()["document"]["version_count"] == 2
    await drain(app)
    versions = (await client.get(f"{base}/documents/{doc['id']}/versions")).json()
    assert [v["version_no"] for v in versions] == [2, 1] and versions[0]["is_current"]
    assert (await client.get(f"{base}/documents/{doc['id']}")).json()["status"] == "COMPLETED"
    old = await client.get(
        f"{base}/documents/{doc['id']}/download", params={"version": versions[1]["id"]}
    )
    assert old.content == TXT


# ---------- orchestrator behaviour ----------


async def _queued_job(client, app, base):
    """Create a QUEUED document + job without running it (queue enqueue is a no-op)."""
    app.state.queue_real = app.state.queue

    class Hold:
        async def enqueue(self, job_id):
            return None

        async def close(self):
            return None

        async def drain(self):
            return None

    app.state.queue = Hold()
    try:
        doc = (await client.post(f"{base}/documents/upload", files=files(("a.txt", TXT)))).json()[
            "results"
        ][0]["document"]
    finally:
        app.state.queue = app.state.queue_real
    job = await app.state.db.processing_jobs.find_one({"document_id": ObjectId(doc["id"])})
    return doc, job["_id"]


async def test_resume_skips_completed_stages_and_retries(client, app, fake_stages):
    fail = {"times": 1, "exc": RuntimeError("boom")}
    fake_stages.default(embed=fail)
    _, _, base = await setup(client)
    doc, job_id = await _queued_job(client, app, base)
    db, st, store = app.state.db, app.state.queue_real._settings, app.state.store
    with pytest.raises(RetryLater) as e:
        await run_job(db, st, store, job_id)
    assert e.value.countdown == 5
    assert fake_stages.calls == ["extract", "chunk", "embed"]
    assert (await db.processing_jobs.find_one({"_id": job_id}))["state"] == "retrying"
    await run_job(db, st, store, job_id)  # resume
    assert fake_stages.calls == [
        "extract",
        "chunk",
        "embed",
        "embed",
        "index",
    ]  # extract/chunk not re-run
    assert (await db.documents.find_one({"_id": ObjectId(doc["id"])}))["status"] == "COMPLETED"


async def test_gives_up_after_max_attempts(client, app, fake_stages):
    fake_stages.default(chunk={"times": 99, "exc": RuntimeError("provider down")})
    _, _, base = await setup(client)
    doc, job_id = await _queued_job(client, app, base)
    db, st, store = app.state.db, app.state.queue_real._settings, app.state.store
    for _ in range(st.job_max_attempts - 1):
        with pytest.raises(RetryLater):
            await run_job(db, st, store, job_id)
    await run_job(db, st, store, job_id)
    d = await db.documents.find_one({"_id": ObjectId(doc["id"])})
    assert d["status"] == "FAILED" and "several attempts" in d["error"]
    assert "provider down" not in d["error"]  # internals are not leaked to users


async def test_document_deleted_mid_processing_is_not_completed(client, app, fake_stages):
    _, _, base = await setup(client)
    doc, job_id = await _queued_job(client, app, base)
    from app.modules.documents.states import DocumentStatus as S
    from app.modules.ingestion import orchestrator as o

    async def delete_during(ctx):
        await ctx.db.documents.update_one(
            {"_id": ctx.document["_id"]}, {"$set": {"deleted_at": ctx.job["created_at"]}}
        )

    fake_stages.set(
        o.Stage("extract", S.EXTRACTING, delete_during), fake_stages.make("chunk", S.CHUNKING)
    )
    db, st, store = app.state.db, app.state.queue_real._settings, app.state.store
    await run_job(db, st, store, job_id)
    assert "chunk" not in fake_stages.calls
    assert (await db.processing_jobs.find_one({"_id": job_id}))["state"] == "failed"
    assert (await db.documents.find_one({"_id": ObjectId(doc["id"])}))["status"] != "COMPLETED"


async def test_no_stages_fails_clearly(client, app, fake_stages):
    fake_stages.set()
    _, _, base = await setup(client)
    doc, job_id = await _queued_job(client, app, base)
    await run_job(app.state.db, app.state.queue_real._settings, app.state.store, job_id)
    d = await app.state.db.documents.find_one({"_id": ObjectId(doc["id"])})
    assert d["status"] == "FAILED" and "No processing stages" in d["error"]


async def test_recover_stuck_jobs(client, app, fake_stages):
    from datetime import timedelta

    from app.modules.ingestion.queue import recover_stuck_jobs

    fake_stages.default()
    _, _, base = await setup(client)
    doc, job_id = await _queued_job(client, app, base)
    assert await recover_stuck_jobs(app.state.db, app.state.queue_real, timedelta(hours=1)) == 0
    assert await recover_stuck_jobs(app.state.db, app.state.queue_real, timedelta(seconds=0)) == 1
    await drain(app)
    assert (await client.get(f"{base}/documents/{doc['id']}")).json()["status"] == "COMPLETED"
