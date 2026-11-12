"""POST /questions/{id}/attempts against the local Postgres (rolled back after each test)."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_current_user, get_smart_client
from app.db.models import Attempt, Question
from app.db.session import get_db
from app.llm.client import ModelClient
from app.llm.errors import ModelUnavailable
from app.llm.providers.fake import FakeProvider
from app.main import app


@pytest.fixture
def api(db, user):
    """TestClient whose smart client replies from `api.script` (a list you append to)."""
    script = []
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_smart_client] = lambda: ModelClient(FakeProvider(script), model="fake-model")
    client = TestClient(app)
    client.script = script
    yield client
    app.dependency_overrides.clear()


def add_question(db, session_id, **overrides) -> Question:
    fields = dict(
        session_id=session_id,
        prompt="What does glycolysis split glucose into?",
        answer_key="two pyruvate",
        question_type="short_answer",
        span_text="so glycolysis splits glucose into two pyruvate",
    )
    question = Question(**(fields | overrides))
    db.add(question)
    db.flush()
    return question


def answer(api, question_id, text):
    return api.post(f"/questions/{question_id}/attempts", json={"user_answer": text})


def saved_attempt(db, attempt_id) -> Attempt:
    return db.scalars(select(Attempt).where(Attempt.attempt_id == attempt_id)).one()


def test_short_answer_is_graded_and_saved(api, db, user, recording):
    question = add_question(db, recording.session_id)
    api.script.append(json.dumps({"reason": "r", "verdict": "partially_correct", "feedback": "Close."}))

    response = answer(api, question.question_id, "pyruvate")

    assert response.status_code == 201
    body = response.json()
    assert (body["graded"], body["is_correct"], body["score"], body["feedback"]) == (True, False, 0.5, "Close.")
    row = saved_attempt(db, body["attempt_id"])
    assert (row.question_id, row.user_id, row.user_answer) == (question.question_id, user.user_id, "pyruvate")
    assert (row.is_correct, row.score, row.feedback) == (False, 0.5, "Close.")


def test_multiple_choice_is_graded_without_model(api, db, recording):
    question = add_question(
        db, recording.session_id, question_type="multiple_choice",
        options=["nucleus", "cytoplasm"], answer_key="cytoplasm",
    )
    response = answer(api, question.question_id, "cytoplasm")  # empty script: a model call would fail
    assert (response.json()["graded"], response.json()["is_correct"], response.json()["score"]) == (True, True, 1.0)


def test_model_failure_saves_ungraded_attempt(api, db, recording):
    question = add_question(db, recording.session_id)
    api.script.append(ModelUnavailable("down"))

    response = answer(api, question.question_id, "pyruvate")

    assert response.status_code == 201
    body = response.json()
    assert (body["graded"], body["is_correct"], body["score"], body["feedback"]) == (False, None, None, None)
    row = saved_attempt(db, body["attempt_id"])
    assert (row.user_answer, row.is_correct, row.score, row.feedback) == ("pyruvate", None, None, None)


def test_unknown_question_is_404(api, db):
    missing = uuid4()
    response = answer(api, missing, "anything")
    assert response.status_code == 404
    assert db.scalars(select(Attempt).where(Attempt.question_id == missing)).all() == []


def test_missing_answer_is_422(api, db, recording):
    question = add_question(db, recording.session_id)
    assert api.post(f"/questions/{question.question_id}/attempts", json={}).status_code == 422
