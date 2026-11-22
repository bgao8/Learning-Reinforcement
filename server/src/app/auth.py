"""Device tokens (#33): make them, hash them, and issue one when a device signs in.

A device sends its token as "Authorization: Bearer frz_...". The server keeps only the token's
SHA-256 in device_tokens, so a leaked table can't be used to sign in. Tokens are 256 random
bits, too many to guess, which is why a plain fast hash is enough here (passwords need a slow
one like bcrypt because people pick guessable ones).
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session as DbSession

from app.db.models import DeviceToken


TOKEN_PREFIX = "frz_"           # marks a string as a Frizz token, so a leaked one is easy to spot
TOKEN_TTL = timedelta(days=30)  # how long a new token works before the device must sign in again


def new_token() -> str:
    """A new random token: TOKEN_PREFIX + 43 URL-safe characters (32 random bytes)."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """A token's SHA-256 as 64 hex characters: what device_tokens stores and looks up by."""
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: DbSession, user_id: UUID, label: str | None = None) -> str:
    """Sign a device in: save a new token's hash for user_id and return the raw token.

    The return value is the only copy of the raw token; the caller shows it once.
    Doesn't commit: the caller does, so it controls the transaction.
    label names the device (e.g. "MacBook") so one token can be told apart and revoked.
    """
    token = new_token()
    db.add(DeviceToken(
        user_id=user_id,
        token_hash=hash_token(token),
        label=label,
        expires_at=datetime.now(timezone.utc) + TOKEN_TTL,
    ))
    return token
