"""GET /sessions/{id}/questions/pending against the local Postgres (rolled back after each test)."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db.models import Attempt, Question, Quiz, Session, User
from app.db.session import get_db
from app.main import app

T0 = datetime(2026, 11, 12, tzinfo=UTC)


@pytest.fixture
def api(db, user):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_quiz(db, session_id, minutes=0, topic="glycolysis") -> Quiz:
    quiz = Quiz(session_id=session_id, trigger_reason="topic_shift", topic=topic, triggered_at=T0 + timedelta(minutes=minutes))
    db.add(quiz)
    db.flush()
    return quiz


def add_question(db, quiz, prompt, **overrides) -> Question:
    fields = dict(session_id=quiz.session_id, quiz_id=quiz.quiz_id, prompt=prompt,
                  answer_key="secret", question_type="short_answer", options=None)
    question = Question(**(fields | overrides))
    db.add(question)
    db.flush()
    return question


def answer(db, user, question):
    db.add(Attempt(question_id=question.question_id, user_id=user.user_id, user_answer="x"))
    db.flush()


def pending(api, session_id):
    response = api.get(f"/sessions/{session_id}/questions/pending")
    assert response.status_code == 200
    return response.json()


def test_nothing_pending(api, recording):
    assert pending(api, recording.session_id) == {"quiz_id": None, "topic": None, "questions": []}


def test_returns_oldest_quiz_with_its_questions(api, db, recording):
    newer = add_quiz(db, recording.session_id, minutes=5, topic="krebs cycle")
    add_question(db, newer, "newer q")
    older = add_quiz(db, recording.session_id, minutes=0)
    add_question(db, older, "a short")
    add_question(db, older, "b choice", question_type="multiple_choice", options=["x", "y"], answer_key="x")

    body = pending(api, recording.session_id)

    assert (body["quiz_id"], body["topic"]) == (str(older.quiz_id), "glycolysis")
    assert [(q["prompt"], q["question_type"], q["options"]) for q in body["questions"]] == [
        ("a short", "short_answer", None),
        ("b choice", "multiple_choice", ["x", "y"]),
    ]


def test_answer_key_is_never_sent(api, db, recording):
    add_question(db, add_quiz(db, recording.session_id), "q")
    [question] = pending(api, recording.session_id)["questions"]
    assert set(question) == {"question_id", "prompt", "question_type", "options"}


def test_answered_questions_are_left_out(api, db, user, recording):
    quiz = add_quiz(db, recording.session_id)
    done = add_question(db, quiz, "a done")
    add_question(db, quiz, "b left")
    answer(db, user, done)

    assert [q["prompt"] for q in pending(api, recording.session_id)["questions"]] == ["b left"]


def test_fully_answered_quiz_moves_on_to_next(api, db, user, recording):
    first = add_quiz(db, recording.session_id, minutes=0)
    answer(db, user, add_question(db, first, "old"))
    second = add_quiz(db, recording.session_id, minutes=5, topic="krebs cycle")
    add_question(db, second, "new")

    body = pending(api, recording.session_id)
    assert (body["quiz_id"], [q["prompt"] for q in body["questions"]]) == (str(second.quiz_id), ["new"])


def test_quiz_without_questions_is_skipped(api, db, recording):
    add_quiz(db, recording.session_id, minutes=0)  # generation failed or kept nothing
    later = add_quiz(db, recording.session_id, minutes=5)
    add_question(db, later, "q")
    assert pending(api, recording.session_id)["quiz_id"] == str(later.quiz_id)


def test_other_users_attempts_dont_count(api, db, recording):
    question = add_question(db, add_quiz(db, recording.session_id), "q")
    other = User(user_name="Other", email=f"{uuid4()}@example.com")
    db.add(other)
    db.flush()
    answer(db, other, question)
    assert [q["prompt"] for q in pending(api, recording.session_id)["questions"]] == ["q"]


def test_other_sessions_quizzes_are_ignored(api, db, user, recording):
    elsewhere = Session(user_id=user.user_id)
    db.add(elsewhere)
    db.flush()
    add_question(db, add_quiz(db, elsewhere.session_id), "elsewhere")
    assert pending(api, recording.session_id)["questions"] == []


def test_unknown_session_is_404(api):
    assert api.get(f"/sessions/{uuid4()}/questions/pending").status_code == 404
