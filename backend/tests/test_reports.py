import io

import pymupdf
import pytest
from bson import ObjectId
from docx import Document

from .conftest import register
from .test_comparison import NAPS, SLEEP
from .test_rag_api import setup
from .test_research import PAPER_A, PAPER_B

TWO = [("sleep.txt", PAPER_A.encode()), ("nap.txt", PAPER_B.encode())]


async def make(client, base, body):
    r = await client.post(f"{base}/reports", json=body)
    assert r.status_code == 202, r.text
    return r.json()


async def fetch(client, base, rid, fmt):
    r = await client.get(f"{base}/reports/{rid}/download", params={"format": fmt})
    assert r.status_code == 200, r.text
    return r


def pdf_text(data: bytes) -> str:
    return "\n".join(p.get_text() for p in pymupdf.open(stream=data, filetype="pdf"))


def docx_parts(data: bytes):
    d = Document(io.BytesIO(data))
    return d, "\n".join(p.text for p in d.paragraphs)


async def test_document_summary_report_pdf_and_docx_contain_real_content(client, app, ai):
    ws, base, (a, _) = await setup(client, app, TWO)
    rep = await make(
        client, base, {"type": "document_summary", "document_ids": [a], "title": "Sleep summary"}
    )
    await app.state.queue.drain()
    full = (await client.get(f"{base}/reports/{rep['id']}")).json()
    assert full["status"] == "completed" and full["formats"] == ["pdf", "docx"]
    titles = [s["title"] for s in full["sections"]]
    assert titles[:2] == ["Executive summary", "Summary"] and "Key findings" in titles
    assert (
        full["references"]
        and full["references"][0]["document_title"] == "sleep"
        and full["references"][0]["page"] == 1
    )

    pdf = await fetch(client, base, rep["id"], "pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    assert "Sleep%20summary.pdf" in pdf.headers["content-disposition"]
    text = pdf_text(pdf.content)
    assert "Sleep summary" in text and "Executive summary" in text and "Key findings" in text
    assert (
        "References" in text
        and "[1]" in text
        and "Generated 20" in text
        and "verify important details" in text
    )

    dx = await fetch(client, base, rep["id"], "docx")
    doc, dtext = docx_parts(dx.content)
    assert (
        "Sleep summary" in dtext and "Executive summary" in dtext and "[1] sleep, page 1" in dtext
    )
    assert doc.core_properties.title == "Sleep summary"


async def test_research_and_literature_review_reports_label_ai_gaps_and_include_tables(
    client, app, ai
):
    ws, base, (a, b) = await setup(client, app, TWO)
    paper = (await client.post(f"{base}/research/papers", json={"document_id": a})).json()
    synth = (await client.post(f"{base}/research/synthesis", json={"document_ids": [a, b]})).json()
    await app.state.queue.drain()
    r1 = await make(client, base, {"type": "research", "analysis_id": paper["id"]})
    r2 = await make(client, base, {"type": "literature_review", "analysis_id": synth["id"]})
    await app.state.queue.drain()
    t1 = pdf_text((await fetch(client, base, r1["id"], "pdf")).content)
    assert "Methodology" in t1 and "AI-identified" in t1 and "Sample size" in t1
    t2 = pdf_text((await fetch(client, base, r2["id"], "pdf")).content)
    assert (
        "Comparison of papers" in t2
        and "experimental" in t2
        and "survey" in t2
        and "AI-identified suggestions" in t2
    )
    d, _ = docx_parts((await fetch(client, base, r2["id"], "docx")).content)
    assert (
        len(d.tables) == 1
        and d.tables[0].rows[0].cells[0].text == "Paper"
        and len(d.tables[0].rows) == 3
    )


async def test_comparison_multi_document_and_executive_reports(client, app, ai):
    ws, base, (a, b) = await setup(
        client, app, [("sleep.txt", SLEEP.encode()), ("naps.txt", NAPS.encode())]
    )
    comp = (await client.post(f"{base}/comparisons", json={"document_ids": [a, b]})).json()
    await app.state.queue.drain()
    reps = [
        await make(client, base, {"type": "comparison", "comparison_id": comp["id"]}),
        await make(client, base, {"type": "multi_document", "document_ids": [a, b]}),
        await make(client, base, {"type": "executive_summary", "document_ids": [a, b]}),
        await make(client, base, {"type": "findings", "document_ids": [a, b]}),
    ]
    await app.state.queue.drain()
    for r in reps:
        got = (await client.get(f"{base}/reports/{r['id']}")).json()
        assert got["status"] == "completed", got
        assert pdf_text((await fetch(client, base, r["id"], "pdf")).content).strip()
    cmp_text = pdf_text((await fetch(client, base, reps[0]["id"], "pdf")).content)
    assert "Methodology: differences" in cmp_text
    multi = docx_parts((await fetch(client, base, reps[1]["id"], "docx")).content)[0]
    assert len(multi.tables) == 1  # "Documents at a glance"
    exec_titles = [
        s["title"] for s in (await client.get(f"{base}/reports/{reps[2]['id']}")).json()["sections"]
    ]
    assert "Documents at a glance" not in exec_titles


async def test_version_comparison_report(client, app, ai):
    ws, base, (doc_id,) = await setup(
        client, app, [("policy.txt", b"# P\n\nRemote work two days per week is allowed here.")]
    )
    await client.post(
        f"{base}/documents/{doc_id}/versions",
        files={
            "file": (
                "policy.txt",
                b"# P\n\nRemote work three days per week is allowed here.",
                "text/plain",
            )
        },
    )
    await app.state.queue.drain()
    comp = (await client.post(f"{base}/comparisons/versions", json={"document_id": doc_id})).json()
    await app.state.queue.drain()
    rep = await make(client, base, {"type": "comparison", "comparison_id": comp["id"]})
    await app.state.queue.drain()
    text = pdf_text((await fetch(client, base, rep["id"], "pdf")).content)
    assert "Changed passages" in text and "three days" in text


async def test_validation_not_ready_permissions_isolation_and_delete(client, new_client, app, ai):
    ws, base, (a, b) = await setup(client, app, TWO)
    assert (
        await client.post(
            f"{base}/reports", json={"type": "document_summary", "document_ids": [a, b]}
        )
    ).json()["error"]["code"] == "bad_sources"
    assert (
        await client.post(f"{base}/reports", json={"type": "multi_document", "document_ids": [a]})
    ).json()["error"]["code"] == "bad_sources"
    assert (
        await client.post(
            f"{base}/reports", json={"type": "document_summary", "document_ids": [str(ObjectId())]}
        )
    ).status_code == 404
    assert (
        await client.post(
            f"{base}/reports", json={"type": "research", "analysis_id": str(ObjectId())}
        )
    ).status_code == 404
    assert (await client.post(f"{base}/reports", json={"type": "bogus"})).status_code == 422
    rec = await make(client, base, {"type": "document_summary", "document_ids": [a]})
    await app.state.queue.drain()
    async with new_client() as v:
        await register(v, "v@example.com", "V")
        await client.post(f"{base}/members", json={"email": "v@example.com", "role": "viewer"})
        assert (await v.get(f"{base}/reports/{rec['id']}/download")).status_code == 200
        assert (
            await v.post(f"{base}/reports", json={"type": "document_summary", "document_ids": [a]})
        ).status_code == 403
        assert (await v.delete(f"{base}/reports/{rec['id']}")).status_code == 403
    async with new_client() as o:
        await register(o, "o@example.com", "O")
        assert (await o.get(f"{base}/reports/{rec['id']}/download")).status_code == 404
    key = (await app.state.db.reports.find_one({"_id": ObjectId(rec["id"])}))["exports"][0][
        "storage_key"
    ]
    assert await app.state.store.exists(key)
    assert (await client.delete(f"{base}/reports/{rec['id']}")).status_code == 204
    assert not await app.state.store.exists(key)  # exported files are removed with the report
    assert (await client.get(f"{base}/reports/{rec['id']}")).status_code == 404


async def test_failure_when_insights_missing_and_cascade_on_document_delete(client, app, ai):
    ws, base, (a, b) = await setup(client, app, TWO)
    await app.state.db.document_insights.delete_many({"document_id": ObjectId(a)})
    bad = await make(client, base, {"type": "document_summary", "document_ids": [a]})
    await app.state.queue.drain()
    got = (await client.get(f"{base}/reports/{bad['id']}")).json()
    assert got["status"] == "failed" and "Insights" in got["error"]
    assert (await client.get(f"{base}/reports/{bad['id']}/download")).status_code == 409
    ok = await make(client, base, {"type": "document_summary", "document_ids": [b]})
    await app.state.queue.drain()
    await client.delete(f"{base}/documents/{b}")
    assert (
        await client.get(f"{base}/reports/{ok['id']}")
    ).status_code == 404  # derived report removed with its source


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
async def test_download_before_ready_is_a_conflict(client, app, ai, fmt):
    ws, base, (a, _) = await setup(client, app, TWO)

    class Hold:
        async def enqueue(self, job_id):
            return None

        async def close(self):
            return None

    real, app.state.queue = app.state.queue, Hold()
    try:
        rec = await make(client, base, {"type": "document_summary", "document_ids": [a]})
    finally:
        app.state.queue = real
    r = await client.get(f"{base}/reports/{rec['id']}/download", params={"format": fmt})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_ready"
