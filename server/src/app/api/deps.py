"""Dependencies shared by the API routers: current user and cached model clients."""
from functools import cache

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import User
from app.db.session import get_db
from app.llm import ModelClient, make_client

SEED_EMAIL = "bgao2005@gmail.com"


def get_current_user(db: DbSession = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.email == SEED_EMAIL))
    if user is None:
        raise HTTPException(status_code=500, detail="seed user missing; run scripts/seed.py")
    return user


@cache
def get_shift_client() -> ModelClient:
    return make_client("fast")


@cache
def get_smart_client() -> ModelClient:
    return make_client("smart")
