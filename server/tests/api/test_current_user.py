"""get_current_user (#33): the device token in the Authorization header picks the user.

Runs the real dependency (the other API tests replace it) behind a one-route app, against the
local Postgres (rolled back after each test).
"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_current_user
from app.auth import TOKEN_TTL, hash_token, issue_token
from app.db.models import DeviceToken, User
from app.db.session import get_db

probe = FastAPI()


@probe.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"user_id": str(user.user_id)}


@pytest.fixture
def api(db):
    probe.dependency_overrides[get_db] = lambda: db
    yield TestClient(probe)
    probe.dependency_overrides.clear()


@pytest.fixture
def token(db, user) -> str:
    raw = issue_token(db, user.user_id, "MacBook")
    db.flush()
    return raw


def row_for(db, raw: str) -> DeviceToken:
    return db.scalar(select(DeviceToken).where(DeviceToken.token_hash == hash_token(raw)))


def get_me(api, raw: str | None = None, scheme: str = "Bearer"):
    headers = {"Authorization": f"{scheme} {raw}"} if raw is not None else {}
    return api.get("/me", headers=headers)


def assert_unauthorized(response):
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid or expired token"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- who gets in ---

def test_valid_token_returns_its_user(api, token, user):
    response = get_me(api, token)
    assert response.status_code == 200
    assert response.json() == {"user_id": str(user.user_id)}


def test_the_token_picks_the_user(api, db, token):
    other = User(user_name="Other", email=f"{uuid4()}@example.com")
    db.add(other)
    db.flush()
    other_token = issue_token(db, other.user_id)
    db.flush()
    assert get_me(api, other_token).json() == {"user_id": str(other.user_id)}


# --- who doesn't (all get the same 401, so a reply never says why) ---

def test_no_header_is_401(api):
    assert_unauthorized(get_me(api))


def test_other_scheme_is_401(api, token):
    assert_unauthorized(get_me(api, token, scheme="Basic"))


def test_unknown_token_is_401(api, token):
    assert_unauthorized(get_me(api, token + "x"))


def test_the_hash_itself_is_not_a_token(api, db, token):
    assert_unauthorized(get_me(api, row_for(db, token).token_hash))


def test_revoked_token_is_401(api, db, token):
    row_for(db, token).revoked_at = datetime.now(UTC)
    db.flush()
    assert_unauthorized(get_me(api, token))


def test_expired_token_is_401(api, db, token):
    row_for(db, token).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    assert_unauthorized(get_me(api, token))


# --- sliding expiry ---

def test_first_use_records_it_and_extends_the_expiry(api, db, token):
    row = row_for(db, token)
    row.expires_at = datetime.now(UTC) + timedelta(days=1)     # nearly expired
    db.flush()

    before = datetime.now(UTC)
    get_me(api, token)
    db.refresh(row)
    assert row.last_used_at >= before
    assert row.expires_at >= before + TOKEN_TTL


def test_use_within_the_hour_writes_nothing(api, db, token):
    row = row_for(db, token)
    used = datetime.now(UTC) - timedelta(minutes=30)
    expires = datetime.now(UTC) + timedelta(days=10)
    row.last_used_at, row.expires_at = used, expires
    db.flush()

    assert get_me(api, token).status_code == 200
    db.refresh(row)
    assert (row.last_used_at, row.expires_at) == (used, expires)


def test_use_after_an_hour_extends_again(api, db, token):
    row = row_for(db, token)
    row.last_used_at = datetime.now(UTC) - timedelta(hours=2)
    row.expires_at = datetime.now(UTC) + timedelta(days=10)
    db.flush()

    before = datetime.now(UTC)
    get_me(api, token)
    db.refresh(row)
    assert row.last_used_at >= before
    assert row.expires_at >= before + TOKEN_TTL


def test_rejected_token_is_not_extended(api, db, token):
    row = row_for(db, token)
    row.revoked_at = datetime.now(UTC)
    db.flush()

    get_me(api, token)
    db.refresh(row)
    assert row.last_used_at is None
