from app.core.config import Settings
from app.modules.vector_search.atlas import AtlasVectorStore
from app.modules.vector_search.base import VectorStore
from app.modules.vector_search.local import LocalVectorStore


def build_vector_store(settings: Settings) -> VectorStore:
    if settings.vector_backend == "atlas":
        return AtlasVectorStore(settings)
    if settings.env == "production":
        raise RuntimeError("VECTOR_BACKEND=local is not allowed in production; use atlas")
    return LocalVectorStore(settings.local_scan_limit)
