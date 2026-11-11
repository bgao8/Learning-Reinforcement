"""Shared fixtures. pytest loads this automatically for every test file under tests/."""
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app.db.models import Session, User
from app.db.session import engine


@pytest.fixture
def db():
    """A DB session inside a transaction that is rolled back after the test.

    Skips the test if Postgres isn't running.
    """
    try:
        connection = engine.connect()
    except OperationalError:
        pytest.skip("Postgres isn't running")
    transaction = connection.begin()
    session = DbSession(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def user(db):
    user = User(user_name="Test", email=f"{uuid4()}@example.com")
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def recording(db, user) -> Session:
    """A sessions row (a recording) owned by `user`."""
    row = Session(user_id=user.user_id)
    db.add(row)
    db.flush()
    return row
