from collections.abc import AsyncIterator
from typing import Protocol


class ObjectNotFoundError(Exception):
    pass


class ObjectStore(Protocol):
    """Private object storage. Keys are server-generated; callers never pass user filenames."""

    async def put_file(self, key: str, path: str, content_type: str) -> None: ...

    async def get_bytes(self, key: str) -> bytes: ...

    def stream(self, key: str, chunk_size: int = 1024 * 256) -> AsyncIterator[bytes]: ...

    async def download_to(self, key: str, path: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...
