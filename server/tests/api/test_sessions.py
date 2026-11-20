"""Runs against the local Postgres. Every test is rolled back, so no rows are left behind."""
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session as DbSession

from contextlib import contextmanager

import app.api.sessions as sessions_api
import json

from app.api.deps import get_current_user, get_smart_client
from app.api.sessions import checkpoint_task, get_transcriber, live_sessions, questions_task
from app.db.models import Concept, Question, Quiz, Session, TranscriptChunk, User
from app.llm.client import ModelClient
from app.llm.errors import ModelUnavailable
from app.llm.providers.fake import FakeProvider
from app.stt.live import LiveSession
from app.topic_shift import QuizTrigger
from app.db.session import engine, get_db
from app.main import app
from app.stt.transcriber import SAMPLE_RATE, Word


class FakeTranscriber:
    """Says "hello" in the middle of every window, so no model is loaded."""

    def __init__(self):
        self.calls = 0

    async def transcribe(self, samples):
        return "hello"

    async def transcribe_words(self, samples, prompt=None):
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
    app.dependency_overrides[get_smart_client] = lambda: None  # real one needs an API key
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


# --- PATCH /sessions/{id}: the optional video title ---

def test_patch_sets_title_trimmed(client):
    sid = start(client)
    res = client.patch(f"/sessions/{sid}", json={"title": "  Flywheel KERS explained  "})
    assert res.status_code == 200
    assert res.json()["title"] == "Flywheel KERS explained"


def test_patch_title_reaches_the_live_session(client):
    # Whisper's prompt uses it from the next window on
    sid = client.post("/sessions", json={}).json()["session_id"]
    client.patch(f"/sessions/{sid}", json={"title": "Flywheel KERS"})
    assert live_sessions[UUID(sid)].title == "Flywheel KERS"


def test_create_passes_the_title_to_the_live_session(client):
    sid = client.post("/sessions", json={"title": "Flywheel KERS"}).json()["session_id"]
    assert live_sessions[UUID(sid)].title == "Flywheel KERS"


def test_patch_empty_title_clears_it(client):
    sid = client.post("/sessions", json={"title": "old"}).json()["session_id"]
    assert client.patch(f"/sessions/{sid}", json={"title": "   "}).json()["title"] is None


def test_patch_title_over_300_chars_is_rejected(client):
    sid = start(client)
    assert client.patch(f"/sessions/{sid}", json={"title": "x" * 301}).status_code == 422


def test_patch_unknown_session_is_404(client):
    assert client.patch(f"/sessions/{uuid4()}", json={"title": "t"}).status_code == 404


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


def saved_rows(db, session_id):
    return db.scalars(
        select(TranscriptChunk)
        .where(TranscriptChunk.session_id == UUID(session_id))
        .order_by(TranscriptChunk.seq)
    ).all()


def test_uploads_save_transcript_rows(client, db):
    session_id = start(client)
    for seq in range(3):
        client.post(f"/sessions/{session_id}/chunks?seq={seq}", content=audio(5))
    rows = saved_rows(db, session_id)
    assert [(r.seq, r.start_ts, r.end_ts, r.text_) for r in rows] == [
        (0, 0, 5, "hello"),
        (1, 5, 10, "hello"),
    ]


def test_end_saves_the_tail_row(client, db):
    session_id = start(client)
    client.post(f"/sessions/{session_id}/chunks?seq=0", content=audio(3))
    assert saved_rows(db, session_id) == []
    client.patch(f"/sessions/{session_id}/end")
    rows = saved_rows(db, session_id)
    assert [(r.seq, r.start_ts, r.end_ts) for r in rows] == [(0, 0, 3)]


def test_rejected_chunk_saves_nothing(client, db):
    session_id = start(client)
    client.post(f"/sessions/{session_id}/chunks?seq=5", content=audio(10))
    assert saved_rows(db, session_id) == []


def test_silent_audio_saves_no_rows(client, db):
    session_id = start(client)
    client.post(f"/sessions/{session_id}/chunks?seq=0", content=audio(10, level=0.0))
    client.patch(f"/sessions/{session_id}/end")
    assert saved_rows(db, session_id) == []


# --- checkpoint_task: saves what run_checkpoint decided ---

@pytest.fixture
def use_test_db(db, monkeypatch):
    """checkpoint_task opens its own SessionLocal(); point it at the rolled-back test session."""
    @contextmanager
    def test_session():
        yield db
    monkeypatch.setattr(sessions_api, "SessionLocal", test_session)


@pytest.fixture
def spawned(monkeypatch):
    """Capture coroutines checkpoint_task hands to _spawn instead of running them in the background."""
    coros = []
    monkeypatch.setattr(sessions_api, "_spawn", coros.append)
    yield coros
    for coro in coros:
        coro.close()  # never awaited; close to silence the "never awaited" warning


@pytest.mark.anyio
async def test_checkpoint_task_saves_quiz_with_span_and_topic(db, recording, use_test_db, spawned, monkeypatch):
    row = recording
    trigger = QuizTrigger("topic_shift", span_start=0.0, span_end=140.0, topic="civic")

    async def fake_run_checkpoint(live, client):
        return trigger
    monkeypatch.setattr(sessions_api, "run_checkpoint", fake_run_checkpoint)

    live = LiveSession(transcriber=None)
    live.checking = True
    await checkpoint_task(live, client=None, smart_client=None, session_id=row.session_id)

    quiz = db.scalars(select(Quiz).where(Quiz.session_id == row.session_id)).one()
    assert (quiz.trigger_reason, quiz.span_start_ts, quiz.span_end_ts, quiz.topic) == ("topic_shift", 0.0, 140.0, "civic")
    assert live.checking is False


@pytest.mark.anyio
async def test_checkpoint_task_saves_nothing_without_trigger(db, recording, use_test_db, spawned, monkeypatch):
    row = recording

    async def fake_run_checkpoint(live, client):
        return None
    monkeypatch.setattr(sessions_api, "run_checkpoint", fake_run_checkpoint)

    live = LiveSession(transcriber=None)
    live.checking = True
    await checkpoint_task(live, client=None, smart_client=None, session_id=row.session_id)

    assert db.scalars(select(Quiz).where(Quiz.session_id == row.session_id)).all() == []
    assert live.checking is False
    assert spawned == []


@pytest.mark.anyio
async def test_checkpoint_task_hands_off_questions_and_releases_checking(db, recording, use_test_db, spawned, monkeypatch):
    """Question generation runs as its own task, so live.checking is released without waiting on the LLM."""
    trigger = QuizTrigger("length", span_start=0.0, span_end=30.0, topic=None)

    async def fake_run_checkpoint(live, client):
        return trigger
    monkeypatch.setattr(sessions_api, "run_checkpoint", fake_run_checkpoint)

    live = LiveSession(transcriber=None)
    live.checking = True
    await checkpoint_task(live, client=None, smart_client=None, session_id=recording.session_id)

    assert live.checking is False
    assert len(spawned) == 1
    assert spawned[0].cr_code is questions_task.__code__
    quiz = db.scalars(select(Quiz).where(Quiz.session_id == recording.session_id)).one()
    assert spawned[0].cr_frame.f_locals["quiz_id"] == quiz.quiz_id


# --- questions_task: span -> generate -> keep_grounded -> Question rows ---

SPAN_CHUNKS = [
    (0, 0.0, 5.0, "so glycolysis splits glucose"),
    (1, 5.0, 10.0, "into two pyruvate"),
    (2, 30.0, 35.0, "now the krebs cycle"),  # outside [0, 10)
]


def add_chunks(db, session_id, chunks):
    for seq, start, end, text in chunks:
        db.add(TranscriptChunk(session_id=session_id, seq=seq, start_ts=start, end_ts=end, text_=text))
    db.flush()


def make_quiz(db, session_id) -> Quiz:
    quiz = Quiz(session_id=session_id, trigger_reason="length", span_start_ts=0.0, span_end_ts=10.0)
    db.add(quiz)
    db.flush()
    return quiz


def llm(*scripted):
    return ModelClient(provider=FakeProvider(list(scripted)), model="fake-model")


def answer(*questions, skip_reason=None, course="biology 101"):
    out = {"course": course, "questions": list(questions)}
    if skip_reason:
        out["skip_reason"] = skip_reason
    return json.dumps(out)


def question(evidence="glycolysis splits glucose", prompt="What does glycolysis split?", question_type="short_answer", options=(), answer_key="glucose", concept="glycolysis"):
    return {"evidence": evidence, "concept": concept, "prompt": prompt, "question_type": question_type, "options": list(options), "answer_key": answer_key}


def saved_questions(db, quiz_id):
    return db.scalars(select(Question).where(Question.quiz_id == quiz_id).order_by(Question.created_at, Question.prompt)).all()


TRIGGER = QuizTrigger("length", span_start=0.0, span_end=10.0, topic="glycolysis")


@pytest.mark.anyio
async def test_questions_task_saves_question_with_its_span(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)

    await questions_task(llm(answer(question())), recording.session_id, quiz.quiz_id, TRIGGER)

    [row] = saved_questions(db, quiz.quiz_id)
    assert (row.session_id, row.prompt, row.answer_key, row.question_type, row.options) == (
        recording.session_id, "What does glycolysis split?", "glucose", "short_answer", None,
    )
    assert (row.span_text, row.span_start_chunk, row.span_end_chunk, row.span_start_ts, row.span_end_ts) == (
        "so glycolysis splits glucose into two pyruvate", 0, 1, 0.0, 10.0,
    )


@pytest.mark.anyio
async def test_questions_task_stores_multiple_choice_options_as_list(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)
    mc = question(question_type="multiple_choice", options=["glucose", "pyruvate", "ATP"])

    await questions_task(llm(answer(mc)), recording.session_id, quiz.quiz_id, TRIGGER)

    [row] = saved_questions(db, quiz.quiz_id)
    assert row.options == ["glucose", "pyruvate", "ATP"]


@pytest.mark.anyio
async def test_questions_task_drops_ungrounded_questions(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)
    invented = question(evidence="glycolysis makes 36 ATP", prompt="How much ATP?")
    outside_span = question(evidence="now the krebs cycle", prompt="What comes next?")

    await questions_task(llm(answer(question(), invented, outside_span)), recording.session_id, quiz.quiz_id, TRIGGER)

    assert [r.prompt for r in saved_questions(db, quiz.quiz_id)] == ["What does glycolysis split?"]


@pytest.mark.anyio
async def test_questions_task_without_transcript_skips_the_llm(db, recording, use_test_db):
    quiz = make_quiz(db, recording.session_id)
    client = llm()  # empty script: any call raises

    await questions_task(client, recording.session_id, quiz.quiz_id, TRIGGER)

    assert client.provider.requests == []
    assert saved_questions(db, quiz.quiz_id) == []
    assert (quiz.status, quiz.skip_reason) == ("empty", "no_transcript")


@pytest.mark.anyio
async def test_questions_task_failure_keeps_quiz(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)

    await questions_task(llm(ModelUnavailable("down")), recording.session_id, quiz.quiz_id, TRIGGER)

    assert saved_questions(db, quiz.quiz_id) == []
    assert db.get(Quiz, quiz.quiz_id) is not None
    assert (quiz.status, quiz.skip_reason) == ("failed", None)


# --- quiz status: why a quiz has (or doesn't have) questions ---

def test_new_quiz_has_no_status_until_generation_ends(db, recording):
    assert make_quiz(db, recording.session_id).status is None


@pytest.mark.anyio
async def test_questions_task_marks_quiz_ready_when_questions_are_saved(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)

    await questions_task(llm(answer(question())), recording.session_id, quiz.quiz_id, TRIGGER)

    assert (quiz.status, quiz.skip_reason) == ("ready", None)


@pytest.mark.anyio
async def test_questions_task_saves_the_models_skip_reason(db, recording, use_test_db):
    # small talk: the shift fired, but the model found nothing worth asking
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)

    await questions_task(llm(answer(skip_reason="not_educational")), recording.session_id, quiz.quiz_id, TRIGGER)

    assert saved_questions(db, quiz.quiz_id) == []
    assert (quiz.status, quiz.skip_reason) == ("empty", "not_educational")


@pytest.mark.anyio
async def test_questions_task_empty_without_a_reason_saves_none(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)

    await questions_task(llm(answer()), recording.session_id, quiz.quiz_id, TRIGGER)

    assert (quiz.status, quiz.skip_reason) == ("empty", None)


@pytest.mark.anyio
async def test_questions_task_marks_quiz_empty_when_grounding_drops_all(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)
    invented = question(evidence="glycolysis makes 36 ATP")

    await questions_task(llm(answer(invented)), recording.session_id, quiz.quiz_id, TRIGGER)

    assert (quiz.status, quiz.skip_reason) == ("empty", "ungrounded")


def test_status_outside_the_allowed_values_is_rejected(db, recording):
    quiz = make_quiz(db, recording.session_id)
    quiz.status = "done"
    with pytest.raises(IntegrityError):
        db.flush()


def test_skip_reason_outside_the_allowed_values_is_rejected(db, recording):
    quiz = make_quiz(db, recording.session_id)
    quiz.skip_reason = "boring"
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.anyio
async def test_questions_task_tags_questions_with_concepts(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)
    a = question(prompt="a", concept="Glycolysis")
    b = question(prompt="b", concept="glycolysis.")      # same concept after normalizing
    c = question(prompt="c", concept="")                 # blank: no concept, no rating later

    await questions_task(llm(answer(a, b, c)), recording.session_id, quiz.quiz_id, TRIGGER)

    rows = {r.prompt: r for r in saved_questions(db, quiz.quiz_id)}
    assert rows["a"].concept_id is not None
    assert rows["a"].concept_id == rows["b"].concept_id
    assert db.get(Concept, rows["a"].concept_id).name_key == "glycolysis"
    assert rows["c"].concept_id is None


@pytest.mark.anyio
async def test_questions_task_offers_the_sessions_concepts_for_reuse(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    first = make_quiz(db, recording.session_id)
    await questions_task(llm(answer(question(concept="glycolysis"))), recording.session_id, first.quiz_id, TRIGGER)

    second = make_quiz(db, recording.session_id)
    client = llm(answer(question(prompt="again")))
    await questions_task(client, recording.session_id, second.quiz_id, TRIGGER)

    # asked in the first quiz but not answered yet: offered with no rating
    assert "KNOWN CONCEPTS\n- glycolysis (new)" in client.provider.requests[0].messages[0].content


@pytest.mark.anyio
async def test_questions_task_sends_earlier_quiz_topics(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    earlier = Quiz(session_id=recording.session_id, trigger_reason="topic_shift", span_start_ts=0.0, span_end_ts=5.0, topic="cell structure")
    db.add(earlier)
    db.flush()
    current = make_quiz(db, recording.session_id)
    current.topic = "glycolysis"
    db.flush()
    client = llm(answer(question()))

    await questions_task(client, recording.session_id, current.quiz_id, TRIGGER)

    content = client.provider.requests[0].messages[0].content
    assert content.startswith("LECTURE SO FAR\n- cell structure\n\nTOPIC\nglycolysis")



@pytest.mark.anyio
async def test_questions_task_sends_the_session_title_first(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    recording.title = "Cellular respiration, lecture 4"
    db.flush()
    quiz = make_quiz(db, recording.session_id)
    client = llm(answer(question()))

    await questions_task(client, recording.session_id, quiz.quiz_id, TRIGGER)

    content = client.provider.requests[0].messages[0].content
    assert content.startswith("LECTURE TITLE\nCellular respiration, lecture 4\n\n")


# --- the session's course: decided by the first ready quiz, then sent to every later one ---

def course_of(db, session_id):
    return db.scalar(select(Session.course).where(Session.session_id == session_id))


@pytest.mark.anyio
async def test_questions_task_first_ready_quiz_saves_the_course(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)

    await questions_task(llm(answer(question(), course="Cell Biology")), recording.session_id, quiz.quiz_id, TRIGGER)

    assert course_of(db, recording.session_id) == "cell biology"


@pytest.mark.anyio
async def test_questions_task_empty_quiz_does_not_decide_the_course(db, recording, use_test_db):
    # an intro or an ad: its course guess isn't trusted, so the next quiz still gets to decide
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    quiz = make_quiz(db, recording.session_id)

    await questions_task(llm(answer(skip_reason="not_educational", course="marketing")), recording.session_id, quiz.quiz_id, TRIGGER)

    assert course_of(db, recording.session_id) is None


@pytest.mark.anyio
async def test_questions_task_sends_the_decided_course_and_keeps_it(db, recording, use_test_db):
    add_chunks(db, recording.session_id, SPAN_CHUNKS)
    first = make_quiz(db, recording.session_id)
    await questions_task(llm(answer(question(), course="cell biology")), recording.session_id, first.quiz_id, TRIGGER)

    second = make_quiz(db, recording.session_id)
    client = llm(answer(question(prompt="again"), course="biochemistry"))   # the model drifts anyway
    await questions_task(client, recording.session_id, second.quiz_id, TRIGGER)

    assert "COURSE\ncell biology" in client.provider.requests[0].messages[0].content
    assert course_of(db, recording.session_id) == "cell biology"
