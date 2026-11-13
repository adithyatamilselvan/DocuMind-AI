"""Atlas Vector Search / Atlas Search index definitions for `document_chunks`.

The vector dimension MUST equal the embedding provider's output dimension (EMBEDDING_DIM).
Changing model/dimension requires creating a new index and re-embedding (bump EMBEDDING_VERSION).
"""

from typing import Any

VECTOR_INDEX = "chunks_vector"
TEXT_INDEX = "chunks_text"


def vector_index_definition(dimensions: int) -> dict[str, Any]:
    return {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": dimensions, "similarity": "cosine"},
            # permission / scope filter fields
            {"type": "filter", "path": "workspace_id"},
            {"type": "filter", "path": "document_id"},
            {"type": "filter", "path": "is_current"},
        ]
    }  # fmt: skip


def text_index_definition() -> dict[str, Any]:
    return {
        "mappings": {
            "dynamic": False,
            "fields": {
                "content": {"type": "string", "analyzer": "lucene.standard"},
                "section_heading": {"type": "string", "analyzer": "lucene.standard"},
                "workspace_id": {"type": "objectId"},
                "document_id": {"type": "objectId"},
                "is_current": {"type": "boolean"},
            },
        }
    }
