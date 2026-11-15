"""Verify (and optionally create) the Atlas Vector Search / Atlas Search indexes.

    python scripts/verify_indexes.py            # report only, exit code 1 if anything is missing
    python scripts/verify_indexes.py --create   # create missing indexes, then wait until queryable
    python scripts/verify_indexes.py --smoke    # also run a real $vectorSearch query as a smoke test

Requires MONGODB_URI pointing at an Atlas cluster (M0 is enough; it allows 3 search indexes in total).
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_SECRET_KEY", "script-only-secret-key-0123456789abcdef")

from pymongo.operations import SearchIndexModel  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import create_client  # noqa: E402
from app.modules.vector_search.definitions import (  # noqa: E402
    TEXT_INDEX,
    VECTOR_INDEX,
    text_index_definition,
    vector_index_definition,
)


async def main(create: bool, smoke: bool) -> int:
    settings = get_settings()
    client = create_client(settings)
    db = client[settings.mongodb_db]
    coll = db.document_chunks
    try:
        await client.admin.command("ping")
        if "document_chunks" not in await db.list_collection_names():
            await db.create_collection("document_chunks")
        existing = {i["name"]: i async for i in await coll.list_search_indexes()}
        wanted = {
            VECTOR_INDEX: ("vectorSearch", vector_index_definition(settings.embedding_dim)),
            TEXT_INDEX: ("search", text_index_definition()),
        }
        if create:
            for name, (kind, definition) in wanted.items():
                if name not in existing:
                    print(f"creating {kind} index {name} ...")
                    await coll.create_search_index(
                        SearchIndexModel(definition=definition, name=name, type=kind)
                    )
            deadline = time.time() + 300
            while time.time() < deadline:
                existing = {i["name"]: i async for i in await coll.list_search_indexes()}
                if all(existing.get(n, {}).get("queryable") for n in wanted):
                    break
                print("waiting for indexes to become queryable ...")
                await asyncio.sleep(10)
        ok = True
        for name in wanted:
            idx = existing.get(name)
            state = (
                "MISSING"
                if not idx
                else ("READY" if idx.get("queryable") else f"NOT READY ({idx.get('status')})")
            )
            print(f"{name}: {state}")
            ok &= bool(idx and idx.get("queryable"))
        if idx := existing.get(VECTOR_INDEX):
            dims = [
                f.get("numDimensions")
                for f in idx["latestDefinition"]["fields"]
                if f["type"] == "vector"
            ]
            if dims != [settings.embedding_dim]:
                print(
                    f"DIMENSION MISMATCH: index has {dims}, EMBEDDING_DIM={settings.embedding_dim}"
                )
                ok = False
        if smoke and ok:
            res = await (
                await coll.aggregate(
                    [
                        {
                            "$vectorSearch": {
                                "index": VECTOR_INDEX,
                                "path": "embedding",
                                "queryVector": [1.0] + [0.0] * (settings.embedding_dim - 1),  # cosine rejects zero vectors
                                "numCandidates": 10,
                                "limit": 1,
                            }
                        },
                    ]
                )
            ).to_list()
            print(f"smoke query OK ({len(res)} result(s))")
        return 0 if ok else 1
    finally:
        await client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.create, a.smoke)))
