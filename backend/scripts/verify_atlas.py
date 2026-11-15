"""Verify the MongoDB connection (Atlas or local) with real reads and writes. Prints no secrets.

    python scripts/verify_atlas.py

Writes one throwaway document to a collection named `_connectivity_check`, reads it back, deletes it
and drops the collection. Also runs the idempotent index creation. Existing data is never modified.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_SECRET_KEY", "script-only-secret-key-0123456789abcdef")

from app.core.config import get_settings  # noqa: E402
from app.core.db import create_client  # noqa: E402
from app.core.ids import utcnow  # noqa: E402
from app.core.indexes import ensure_indexes  # noqa: E402


async def main() -> int:
    s = get_settings()
    host = urlsplit(s.mongodb_uri).hostname or "?"  # hostname only: credentials never printed
    print(f"host={host} database={s.mongodb_db} srv={s.mongodb_uri.startswith('mongodb+srv')}")
    client = create_client(s)
    try:
        await client.admin.command("ping")
        print("ping: ok")
        info = await client.server_info()
        print("server version:", info.get("version"))
        coll = client[s.mongodb_db]["_connectivity_check"]
        token = uuid.uuid4().hex
        await coll.insert_one({"_id": token, "at": utcnow()})
        got = await coll.find_one({"_id": token})
        assert got and got["_id"] == token, "read-back failed"
        print("write+read: ok")
        await coll.delete_one({"_id": token})
        await client[s.mongodb_db].drop_collection("_connectivity_check")
        print("cleanup: ok")
        await ensure_indexes(client[s.mongodb_db])
        print("indexes: ok")
        names = sorted(await client[s.mongodb_db].list_collection_names())
        print("collections:", ", ".join(names) or "(none)")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {str(e)[:300]}")
        return 1
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
