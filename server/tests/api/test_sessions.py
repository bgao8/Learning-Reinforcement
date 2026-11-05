"""Runs against the local Postgres. Every test is rolled back, so no rows are left behind."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app.api.sessions import get_current_user
from app.db.models import Session, User
from app.db.session import engine, get_db
from app.main import app


@pytest.fixture
def db():
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
def client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_returns_open_session(client):
    res = client.post("/sessions", json={"title": "Bio 101", "source": "youtube"})
    assert res.status_code == 201
    body = res.json()
    assert body["session_id"]
    assert body["title"] == "Bio 101"
    assert body["source"] == "youtube"
    assert body["started_at"]
    assert body["ended_at"] is None


def test_create_with_empty_body_is_allowed(client):
    assert client.post("/sessions", json={}).status_code == 201


def test_create_saves_row_for_current_user(client, db, user):
    session_id = client.post("/sessions", json={}).json()["session_id"]
    row = db.scalar(select(Session).where(Session.session_id == session_id))
    assert row.user_id == user.user_id


def test_create_rejects_wrong_type(client):
    assert client.post("/sessions", json={"title": 123}).status_code == 422


def test_end_sets_ended_at(client):
    session_id = client.post("/sessions", json={}).json()["session_id"]
    res = client.patch(f"/sessions/{session_id}/end")
    assert res.status_code == 200
    assert res.json()["ended_at"] is not None


def test_ending_twice_keeps_first_time(client):
    session_id = client.post("/sessions", json={}).json()["session_id"]
    first = client.patch(f"/sessions/{session_id}/end").json()["ended_at"]
    second = client.patch(f"/sessions/{session_id}/end")
    assert second.status_code == 200
    assert second.json()["ended_at"] == first


def test_end_unknown_session_is_404(client):
    assert client.patch(f"/sessions/{uuid4()}/end").status_code == 404


def test_end_invalid_id_is_422(client):
    assert client.patch("/sessions/not-a-uuid/end").status_code == 422
