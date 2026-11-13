from datetime import UTC, datetime
from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BeforeValidator

from app.core.errors import not_found


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_oid(value: str | ObjectId, what: str = "Resource") -> ObjectId:
    """Parse an id from a path/body; invalid ids look like missing resources."""
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise not_found(f"{what} not found") from None


PyId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, ObjectId) else v)]
