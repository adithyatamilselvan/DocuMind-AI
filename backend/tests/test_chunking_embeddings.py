import httpx
import pytest

from app.ai.providers import embeddings as emb
from app.core.config import get_settings
from app.modules.chunking.service import ChunkingConfig, chunk_document, estimate_tokens
from app.modules.extraction.models import Block, ExtractedDocument, Page
from app.modules.ingestion.errors import PermanentError, RetryableError

from .helpers import LOREM


def doc(*pages: Page) -> ExtractedDocument:
    return ExtractedDocument(list(pages), "physical")


def H(text, level=1):
    return Block("heading", text, level)


def P(text):
    return Block("paragraph", text)


def test_chunks_never_cross_pages_and_keep_section_paths():
    d = doc(
        Page(1, [H("Intro"), P(LOREM * 2), H("Background", 2), P(LOREM)]),
        Page(2, [P(LOREM * 2), H("Methods"), P(LOREM)]),
    )
    chunks = chunk_document(d)
    assert [c.page_number for c in chunks] == sorted(c.page_number for c in chunks)
    by_page = {c.page_number for c in chunks}
    assert by_page == {1, 2}
    bg = next(c for c in chunks if c.section_heading == "Background")
    assert bg.section_path == ["Intro", "Background"] and bg.page_number == 1
    # page 2 text before "Methods" still belongs to the section that was open at that point
    first_p2 = next(c for c in chunks if c.page_number == 2)
    assert first_p2.section_path == ["Intro", "Background"]
    methods = next(c for c in chunks if c.section_heading == "Methods")
    assert methods.section_path == ["Methods"]  # level-1 heading resets the stack
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.token_count == estimate_tokens(c.content) for c in chunks)


def test_long_text_is_split_within_budget_with_overlap():
    para = " ".join(
        f"Sentence number {i} talks about the quarterly results in detail." for i in range(200)
    )
    cfg = ChunkingConfig(target_tokens=100, max_tokens=150, overlap_tokens=25)
    chunks = chunk_document(doc(Page(1, [P(para)])), cfg)
    assert len(chunks) > 5 and all(c.token_count <= cfg.max_tokens + 10 for c in chunks)
    # overlap: each chunk starts with the tail of the previous one
    for a, b in zip(chunks, chunks[1:], strict=False):
        tail = a.content.split(". ")[-1].strip()
        assert tail[:20] in b.content
    assert all(c.page_number == 1 for c in chunks)


def test_tables_get_own_chunks_with_repeated_header():
    rows = [["Region", "Revenue"]] + [[f"R{i}", str(i * 10)] for i in range(120)]
    t = Block("table", "\n".join(" | ".join(r) for r in rows), rows=rows)
    chunks = chunk_document(
        doc(Page(1, [H("Results"), P(LOREM), t])), ChunkingConfig(max_tokens=100)
    )
    tables = [c for c in chunks if c.type == "table"]
    assert len(tables) > 1 and all(c.content.startswith("Region | Revenue") for c in tables)
    assert all(c.section_heading == "Results" for c in tables)
    rows_seen = sum(c.content.count("\n") for c in tables)
    assert rows_seen >= 120  # nothing lost


def test_tiny_fragments_are_merged_and_hashes_are_stable():
    d = doc(Page(1, [P("Short note."), P("Another short note.")]))
    chunks = chunk_document(d)
    assert (
        len(chunks) == 1 and "Short note." in chunks[0].content and "Another" in chunks[0].content
    )
    assert chunk_document(d)[0].content_hash == chunks[0].content_hash


def test_oversized_single_word_run_is_hard_split():
    chunks = chunk_document(doc(Page(1, [P("x" * 10000)])), ChunkingConfig(max_tokens=100))
    assert len(chunks) >= 20 and all(len(c.content) <= 450 for c in chunks)


# ---------- embedding providers ----------


async def test_hashing_embeddings_are_deterministic_and_lexically_meaningful():
    e = emb.HashingEmbeddings(get_settings())
    a, b, c = await e.embed_documents(
        [
            "quarterly revenue growth in europe",
            "europe revenue growth quarterly",
            "medieval castle architecture",
        ]
    )
    assert a == (await e.embed_documents(["quarterly revenue growth in europe"]))[0]
    dot = lambda x, y: sum(i * j for i, j in zip(x, y, strict=True))  # noqa: E731
    assert dot(a, b) > 0.8 > 0.3 > dot(a, c) and len(a) == e.dimensions
    assert abs(dot(a, a) - 1.0) < 1e-6


def _mock_openai(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(emb.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))


def _settings(**over):
    s = get_settings().model_copy(update={"embedding_provider": "openai", **over})
    return s


async def test_openai_batches_and_orders_results(monkeypatch):
    from pydantic import SecretStr

    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(req.content)
        calls.append(body)
        assert req.headers["authorization"] == "Bearer sk-test" and body["dimensions"] == 8
        data = [{"index": i, "embedding": [float(len(t))] * 8} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": list(reversed(data))})  # out of order on purpose

    _mock_openai(monkeypatch, handler)
    s = _settings(openai_api_key=SecretStr("sk-test"), embedding_dim=8, embedding_batch_size=2)
    e = emb.OpenAIEmbeddings(s)
    out = await e.embed_documents(["a", "bb", "ccc", "dddd", "eeeee"])
    assert [v[0] for v in out] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert [len(c["input"]) for c in calls] == [2, 2, 1]


@pytest.mark.parametrize(
    ("status", "exc"),
    [(429, RetryableError), (503, RetryableError), (401, PermanentError), (400, PermanentError)],
)
async def test_openai_error_mapping(monkeypatch, status, exc):
    from pydantic import SecretStr

    _mock_openai(monkeypatch, lambda req: httpx.Response(status, json={"error": "x"}))
    e = emb.OpenAIEmbeddings(_settings(openai_api_key=SecretStr("k"), embedding_dim=8))
    with pytest.raises(exc):
        await e.embed_query("hi")


async def test_openai_missing_key_and_wrong_dimension(monkeypatch):
    from pydantic import SecretStr

    with pytest.raises(PermanentError, match="not configured"):
        await emb.OpenAIEmbeddings(_settings(openai_api_key=SecretStr(""))).embed_query("x")
    _mock_openai(
        monkeypatch,
        lambda req: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 3}]}),
    )
    with pytest.raises(PermanentError, match="dimensions"):
        await emb.OpenAIEmbeddings(
            _settings(openai_api_key=SecretStr("k"), embedding_dim=8)
        ).embed_query("x")


async def test_openai_timeout_is_retryable(monkeypatch):
    from pydantic import SecretStr

    def boom(req):
        raise httpx.ConnectTimeout("slow")

    _mock_openai(monkeypatch, boom)
    with pytest.raises(RetryableError):
        await emb.OpenAIEmbeddings(
            _settings(openai_api_key=SecretStr("k"), embedding_dim=8)
        ).embed_query("x")


def test_factory_and_production_guard():
    assert emb.build_embedder(_settings(embedding_provider="hashing")).name == "hashing"
    assert emb.build_embedder(_settings(embedding_provider="local")).name == "local"
    with pytest.raises(RuntimeError):
        emb.build_embedder(_settings(embedding_provider="hashing", env="production"))
    assert _settings(embedding_provider="hashing").embeds_externally is False
    assert _settings().embeds_externally is True
