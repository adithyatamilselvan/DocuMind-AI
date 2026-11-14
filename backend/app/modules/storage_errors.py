from collections.abc import AsyncIterator

from app.core.errors import not_found
from app.storage.base import ObjectNotFoundError


async def not_available(stream: AsyncIterator[bytes]) -> bytes:
    """Read the first chunk so a missing object becomes a clean 404 before the response starts."""
    try:
        return await anext(stream)
    except (ObjectNotFoundError, StopAsyncIteration):
        raise not_found("File is not available") from None
