"""Embedding providers behind one interface, so the model/provider can change without touching
business logic. Changing model or dimension requires a new `embedding_version` + re-embedding."""

import asyncio
import hashlib
import logging
import math
import re
from typing import Protocol

import httpx
import numpy as np

from app.core.config import Settings
from app.modules.ingestion.errors import PermanentError, RetryableError

log = logging.getLogger("documind.embeddings")


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int
    version: str
    max_batch: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbeddings:
    """Hosted embeddings through the OpenAI-compatible /embeddings endpoint."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dim
        self.version = settings.embedding_version
        self.max_batch = min(settings.embedding_batch_size, 256)
        self._key = settings.openai_api_key.get_secret_value()
        self._url = settings.openai_base_url.rstrip("/") + "/embeddings"
        self._timeout = settings.ai_timeout_s

    async def _call(self, texts: list[str]) -> list[list[float]]:
        if not self._key:
            raise PermanentError(
                "The embedding provider is not configured on the server (missing API key)"
            )
        payload: dict = {"model": self.model, "input": texts, "encoding_format": "float"}
        if self.model.startswith("text-embedding-3"):
            payload["dimensions"] = self.dimensions
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.post(
                    self._url, json=payload, headers={"Authorization": f"Bearer {self._key}"}
                )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise RetryableError("Embedding provider unreachable") from e
        if r.status_code in (401, 403):
            raise PermanentError("The embedding provider rejected the server's credentials")
        if r.status_code == 429 or r.status_code >= 500:
            raise RetryableError(f"Embedding provider returned {r.status_code}")
        if r.status_code >= 400:
            log.error("Embedding request rejected: %s %s", r.status_code, r.text[:200])
            raise PermanentError("The embedding provider rejected the request")
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        vectors = [d["embedding"] for d in data]
        if len(vectors) != len(texts) or any(len(v) != self.dimensions for v in vectors):
            raise PermanentError("The embedding provider returned unexpected dimensions")
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.max_batch):
            out.extend(await self._call(texts[i : i + self.max_batch]))
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._call([text]))[0]


class LocalSentenceTransformer:
    """Local model (e.g. BAAI/bge-m3, 1024-dim). Requires `pip install sentence-transformers`."""

    name = "local"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dim
        self.version = settings.embedding_version
        self.max_batch = settings.embedding_batch_size
        self._model = None

    def _load(self):  # noqa: ANN202
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise PermanentError(
                    "Local embeddings need the 'sentence-transformers' package on the server"
                ) from e
            self._model = SentenceTransformer(self.model)
            actual = self._model.get_sentence_embedding_dimension()
            if actual != self.dimensions:
                raise PermanentError(
                    f"EMBEDDING_DIM={self.dimensions} but {self.model} produces {actual}"
                )
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self._load().encode(
            texts, batch_size=self.max_batch, normalize_embeddings=True, show_progress_bar=False
        )
        return [v.tolist() for v in vecs]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._encode, texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await asyncio.to_thread(self._encode, [text]))[0]


_WORD = re.compile(r"[a-z0-9]+")


class HashingEmbeddings:
    """Deterministic bag-of-words feature hashing. Similar wording -> similar vectors.
    FOR TESTS AND OFFLINE DEVELOPMENT ONLY: it has no semantic understanding."""

    name = "hashing"
    model = "hashing-bow"
    version = "1"
    max_batch = 256

    def __init__(self, settings: Settings) -> None:
        self.dimensions = settings.embedding_dim

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dimensions, dtype=np.float64)
        for tok in _WORD.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            v[h % self.dimensions] += 1.0 if (h >> 63) & 1 else -1.0
            v[(h >> 20) % self.dimensions] += 0.5
        norm = math.sqrt(float((v * v).sum())) or 1.0
        return (v / norm).tolist()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def build_embedder(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddings(settings)
    if settings.embedding_provider == "local":
        return LocalSentenceTransformer(settings)
    if settings.env == "production":
        raise RuntimeError("EMBEDDING_PROVIDER=hashing is not allowed in production")
    return HashingEmbeddings(settings)
