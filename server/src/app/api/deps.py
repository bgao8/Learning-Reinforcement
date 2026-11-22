"""Dependencies shared by the API routers: current user and cached model clients."""
from functools import cache
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import User, DeviceToken
from app.db.session import get_db
from app.auth import hash_token, TOKEN_TTL
from app.llm import ModelClient, make_client


bearer = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: DbSession = Depends(get_db)) -> User:
    unauthorized = HTTPException(
        status_code=401, 
        detail="invalid or expired token", 
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    now = datetime.now(UTC)
    token = db.scalar(select(DeviceToken).where(
        DeviceToken.token_hash == hash_token(credentials.credentials),
        DeviceToken.revoked_at.is_(None),
        DeviceToken.expires_at > now,
    ))
    if token is None:
        raise unauthorized

    if token.last_used_at is None or now - token.last_used_at > timedelta(hours=1):
        token.last_used_at = now
        token.expires_at = now + TOKEN_TTL
        db.commit()

    return db.get(User, token.user_id)


@cache
def get_shift_client() -> ModelClient:
    return make_client("fast")


@cache
def get_smart_client() -> ModelClient:
    return make_client("smart")
