"""Runs against the local Postgres. Every test is rolled back, so no rows are left behind."""
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from app.api.sessions import get_current_user, get_transcriber, live_sessions
from app.db.models import Session, User
from app.db.session import engine, get_db
from app.main import app
from app.stt.transcriber import SAMPLE_RATE, Word


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


class FakeTranscriber:
    """Says "hello" in the middle of every window, so no model is loaded."""

    def __init__(self):
        self.calls = 0

    async def transcribe(self, samples):
        return "hello"

    async def transcribe_words(self, samples):
        self.calls += 1
        mid = len(samples) / SAMPLE_RATE / 2
        return [Word(mid - 0.1, mid + 0.1, "hello")]


@pytest.fixture
def fake():
    return FakeTranscriber()


@pytest.fixture
def client(db, user, fake):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_transcriber] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()
    live_sessions.clear()


def audio(seconds: float, level: float = 0.1) -> bytes:
    return np.full(round(seconds * SAMPLE_RATE), level, dtype=np.float32).tobytes()


def start(client) -> str:
    return client.post("/sessions", json={}).json()["session_id"]


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


def test_chunks_upload_in_order(client):
    session_id = start(client)
    for seq in range(3):
        res = client.post(f"/sessions/{session_id}/chunks?seq={seq}", content=audio(5))
        assert res.status_code == 204


def test_chunks_reach_the_transcript(client, fake):
    session_id = start(client)
    for seq in range(3):
        client.post(f"/sessions/{session_id}/chunks?seq={seq}", content=audio(5))
    assert fake.calls == 2
    assert live_sessions[UUID(session_id)].buffer.last(1000) == "hello hello"


def test_wrong_seq_is_409_with_expected_seq(client):
    session_id = start(client)
    res = client.post(f"/sessions/{session_id}/chunks?seq=1", content=audio(5))
    assert res.status_code == 409
    assert res.json()["detail"] == "expected seq 0"


def test_missing_seq_is_422(client):
    session_id = start(client)
    assert client.post(f"/sessions/{session_id}/chunks", content=audio(5)).status_code == 422


def test_body_that_is_not_float32_is_400(client):
    session_id = start(client)
    res = client.post(f"/sessions/{session_id}/chunks?seq=0", content=b"\x00" * 7)
    assert res.status_code == 400


def test_empty_body_is_400(client):
    session_id = start(client)
    assert client.post(f"/sessions/{session_id}/chunks?seq=0", content=b"").status_code == 400


def test_chunk_for_unknown_session_is_409(client):
    assert client.post(f"/sessions/{uuid4()}/chunks?seq=0", content=audio(5)).status_code == 409


def test_end_transcribes_the_tail_then_stops_accepting(client, fake):
    session_id = start(client)
    client.post(f"/sessions/{session_id}/chunks?seq=0", content=audio(3))
    assert fake.calls == 0
    assert client.patch(f"/sessions/{session_id}/end").status_code == 200
    assert fake.calls == 1
    assert UUID(session_id) not in live_sessions
    res = client.post(f"/sessions/{session_id}/chunks?seq=1", content=audio(5))
    assert res.status_code == 409
