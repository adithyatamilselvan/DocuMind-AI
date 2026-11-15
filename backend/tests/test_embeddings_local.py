import sys
import threading
import time
import types

import pytest

from app.ai.providers.embeddings import LocalSentenceTransformer
from app.core.config import get_settings
from app.modules.ingestion.errors import PermanentError


def _fake_st(monkeypatch, *, new_api: bool, dim: int = 384):
    created: list[int] = []

    class Fake:
        def __init__(self, name: str) -> None:
            time.sleep(0.2)  # widen the race window
            created.append(1)

        def get_sentence_embedding_dimension(self) -> int:
            return dim

    if new_api:
        Fake.get_embedding_dimension = lambda self: dim  # type: ignore[attr-defined]
        Fake.get_sentence_embedding_dimension = lambda self: pytest.fail("deprecated method used")  # type: ignore[method-assign]
    mod = types.ModuleType("sentence_transformers")
    mod.SentenceTransformer = Fake  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", mod)
    return created


def _embedder():
    s = get_settings().model_copy(update={"embedding_dim": 384, "embedding_model": "fake/model"})
    return LocalSentenceTransformer(s)


@pytest.mark.parametrize("new_api", [True, False])
def test_concurrent_first_loads_create_one_model(monkeypatch, new_api):
    created = _fake_st(monkeypatch, new_api=new_api)
    emb = _embedder()
    out: list[object] = []
    threads = [threading.Thread(target=lambda: out.append(emb._load())) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(created) == 1 and len({id(m) for m in out}) == 1


def test_dimension_mismatch_is_rejected_every_time_and_model_not_cached(monkeypatch):
    created = _fake_st(monkeypatch, new_api=True, dim=1024)
    emb = _embedder()
    for _ in range(2):
        with pytest.raises(PermanentError, match="EMBEDDING_DIM=384"):
            emb._load()
    assert emb._model is None and len(created) == 2
