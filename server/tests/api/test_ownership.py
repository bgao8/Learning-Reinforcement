"""Ownership (#33): a user can only touch their own sessions and questions.

Another user's session or question gets the same 404 as one that doesn't exist, so a reply
never says whether an ID is real. Runs against the local Postgres (rolled back after each test).
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_current_user, get_shift_client, get_smart_client
from app.api.sessions import get_transcriber, live_sessions
from app.db.models import Attempt, Question, Session, User
from app.db.session import get_db
from app.main import app
from tests.api.test_sessions import FakeTranscriber, audio


@pytest.fixture
def stranger(db) -> User:
    other = User(user_name="Stranger", email=f"{uuid4()}@example.com")
    db.add(other)
    db.flush()
    return other


@pytest.fixture
def api(db, user):
    """TestClient acting as `user`; `api.act_as(other)` switches who's calling."""
    caller = {"user": user}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: caller["user"]
    app.dependency_overrides[get_transcriber] = FakeTranscriber
    app.dependency_overrides[get_shift_client] = lambda: None   # never reached: no chunk gets through
    app.dependency_overrides[get_smart_client] = lambda: None
    client = TestClient(app)
    client.act_as = lambda who: caller.update(user=who)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def recording(api, db):
    """A session the owner (`user`) started and is still recording."""
    session_id = api.post("/sessions", json={"title": "Bio 101"}).json()["session_id"]
    yield db.get(Session, session_id)
    live_sessions.pop(next((k for k in live_sessions if str(k) == session_id), None), None)


@pytest.fixture
def question(db, recording) -> Question:
    row = Question(
        session_id=recording.session_id,
        prompt="What does glycolysis split glucose into?",
        answer_key="two pyruvate",
        question_type="short_answer",
        span_text="so glycolysis splits glucose into two pyruvate",
    )
    db.add(row)
    db.flush()
    return row


def session_routes(session_id) -> list[tuple[str, str, dict]]:
    """Every route under /sessions/{id}: (method, path, request kwargs)."""
    return [
        ("PATCH", f"/sessions/{session_id}", {"json": {"title": "hijacked"}}),
        ("PATCH", f"/sessions/{session_id}/end", {}),
        ("GET", f"/sessions/{session_id}/questions/pending", {}),
        ("POST", f"/sessions/{session_id}/chunks?seq=0", {"content": audio(1)}),
    ]


# --- sessions ---

@pytest.mark.parametrize("route", range(4), ids=["rename", "end", "pending", "chunk"])
def test_another_users_session_looks_like_it_doesnt_exist(api, recording, stranger, route):
    api.act_as(stranger)
    method, path, kwargs = session_routes(recording.session_id)[route]
    missing_method, missing_path, _ = session_routes(uuid4())[route]

    theirs = api.request(method, path, **kwargs)
    missing = api.request(missing_method, missing_path, **kwargs)

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json() == {"detail": "session not found"}


def test_stranger_cant_rename_or_end_it(api, db, recording, stranger):
    api.act_as(stranger)
    api.patch(f"/sessions/{recording.session_id}", json={"title": "hijacked"})
    api.patch(f"/sessions/{recording.session_id}/end")

    db.refresh(recording)
    assert recording.title == "Bio 101"
    assert recording.ended_at is None
    assert any(str(k) == str(recording.session_id) for k in live_sessions), "still recording"


def test_owner_still_gets_through(api, recording):
    session_id = recording.session_id
    assert api.patch(f"/sessions/{session_id}", json={"title": "Bio 102"}).status_code == 200
    assert api.get(f"/sessions/{session_id}/questions/pending").status_code == 200
    assert api.patch(f"/sessions/{session_id}/end").status_code == 200


# --- answering questions ---

def test_another_users_question_looks_like_it_doesnt_exist(api, question, stranger):
    api.act_as(stranger)
    theirs = api.post(f"/questions/{question.question_id}/attempts", json={"user_answer": "pyruvate"})
    missing = api.post(f"/questions/{uuid4()}/attempts", json={"user_answer": "pyruvate"})

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json() == {"detail": "question not found"}


def test_strangers_answer_is_not_saved(api, db, question, stranger):
    api.act_as(stranger)
    api.post(f"/questions/{question.question_id}/attempts", json={"user_answer": "pyruvate"})
    assert db.scalars(select(Attempt).where(Attempt.question_id == question.question_id)).all() == []
