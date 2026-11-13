import asyncio
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi's PasswordHasher defaults to Argon2id.
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-login")


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password: str, password_hash: str | None) -> tuple[bool, bool]:
    """Returns (valid, needs_rehash). Runs a dummy verify when the user doesn't exist."""

    def _check() -> tuple[bool, bool]:
        try:
            _hasher.verify(password_hash or _DUMMY_HASH, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, False
        if password_hash is None:
            return False, False
        return True, _hasher.check_needs_rehash(password_hash)

    return await asyncio.to_thread(_check)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for(session_token: str, secret: str) -> str:
    return hmac.new(secret.encode(), session_token.encode(), hashlib.sha256).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
