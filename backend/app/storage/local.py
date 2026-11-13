import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from app.storage.base import ObjectNotFoundError


class LocalObjectStore:
    """Filesystem-backed store for development and tests. Same interface as S3."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:  # path traversal guard
            raise ValueError("Invalid object key")
        return p

    async def put_file(self, key: str, path: str, content_type: str) -> None:
        dest = self._path(key)

        def _copy() -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)

        await asyncio.to_thread(_copy)

    async def get_bytes(self, key: str) -> bytes:
        p = self._path(key)
        if not p.is_file():
            raise ObjectNotFoundError(key)
        return await asyncio.to_thread(p.read_bytes)

    async def stream(self, key: str, chunk_size: int = 1024 * 256) -> AsyncIterator[bytes]:  # type: ignore[override]
        p = self._path(key)
        if not p.is_file():
            raise ObjectNotFoundError(key)
        with p.open("rb") as f:
            while chunk := await asyncio.to_thread(f.read, chunk_size):
                yield chunk

    async def download_to(self, key: str, path: str) -> None:
        p = self._path(key)
        if not p.is_file():
            raise ObjectNotFoundError(key)
        await asyncio.to_thread(shutil.copyfile, p, path)

    async def delete(self, key: str) -> None:
        p = self._path(key)
        await asyncio.to_thread(lambda: p.unlink(missing_ok=True))

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()
