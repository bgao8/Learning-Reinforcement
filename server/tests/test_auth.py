"""new_token, hash_token and issue_token (#33). issue_token runs against the local Postgres (rolled back after each test)."""
import hashlib
import string
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.auth import TOKEN_PREFIX, TOKEN_TTL, hash_token, issue_token, new_token
from app.db.models import DeviceToken, User

URL_SAFE = set(string.ascii_letters + string.digits + "-_")


def token_rows(db, user) -> list[DeviceToken]:
    return list(db.scalars(select(DeviceToken).where(DeviceToken.user_id == user.user_id)))


# --- new_token ---

def test_new_token_is_prefixed_and_url_safe():
    token = new_token()
    body = token.removeprefix(TOKEN_PREFIX)
    assert token.startswith(TOKEN_PREFIX)
    assert len(body) == 43      # 32 random bytes in URL-safe base64, no padding
    assert set(body) <= URL_SAFE


def test_new_tokens_are_all_different():
    assert len({new_token() for _ in range(1000)}) == 1000


# --- hash_token ---

def test_hash_is_the_sha256_hex_digest():
    assert hash_token("frz_abc") == hashlib.sha256(b"frz_abc").hexdigest()


def test_hash_is_stable_and_fits_the_column():
    token = new_token()
    assert hash_token(token) == hash_token(token)
    assert len(hash_token(token)) == 64


def test_different_tokens_hash_differently():
    assert hash_token("frz_a") != hash_token("frz_b")


# --- issue_token ---

def test_issue_saves_only_the_hash(db, user):
    token = issue_token(db, user.user_id, "MacBook")
    db.flush()
    [row] = token_rows(db, user)
    assert row.token_hash == hash_token(token)
    assert row.token_hash != token
    assert row.label == "MacBook"


def test_issued_token_starts_unused_and_unrevoked(db, user):
    issue_token(db, user.user_id)
    db.flush()
    [row] = token_rows(db, user)
    db.refresh(row)     # load the server defaults (token_id, created_at)
    assert row.token_id is not None and row.created_at is not None
    assert row.label is None
    assert row.last_used_at is None
    assert row.revoked_at is None


def test_issued_token_expires_after_the_ttl(db, user):
    before = datetime.now(UTC)
    issue_token(db, user.user_id)
    after = datetime.now(UTC)
    db.flush()
    [row] = token_rows(db, user)
    assert before + TOKEN_TTL <= row.expires_at <= after + TOKEN_TTL


def test_each_device_gets_its_own_token(db, user):
    first = issue_token(db, user.user_id, "MacBook")
    second = issue_token(db, user.user_id, "iMac")
    db.flush()
    assert first != second
    assert {row.label for row in token_rows(db, user)} == {"MacBook", "iMac"}


def test_issue_doesnt_commit(db, user):
    issue_token(db, user.user_id)
    assert db.new, "the row should be pending until the caller flushes or commits"


def test_token_hash_is_unique(db, user):
    db.add(DeviceToken(user_id=user.user_id, token_hash="a" * 64, expires_at=datetime.now(UTC)))
    db.add(DeviceToken(user_id=user.user_id, token_hash="a" * 64, expires_at=datetime.now(UTC)))
    with pytest.raises(IntegrityError):
        db.flush()


def test_tokens_are_deleted_with_their_user(db, user):
    issue_token(db, user.user_id)
    db.flush()
    db.expunge_all()    # let the database's ON DELETE CASCADE do the work, not the ORM
    db.execute(delete(User).where(User.user_id == user.user_id))
    assert db.scalars(select(DeviceToken).where(DeviceToken.user_id == user.user_id)).all() == []
