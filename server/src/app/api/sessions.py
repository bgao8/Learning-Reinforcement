import asyncio
import logging
import time
from datetime import UTC, datetime
from uuid import UUID
from functools import cache
import numpy as np

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import Attempt, Question, Quiz, Session, User, TranscriptChunk
from app.jobs.questions import generate_questions, keep_grounded, load_span, save_questions
from app.db.session import SessionLocal, get_db
from app.api.deps import get_current_user, get_shift_client, get_smart_client
from app.llm import ModelClient
from app.topic_shift import QuizTrigger, run_checkpoint

from app.stt.factory import make_transcriber
from app.stt.live import LiveSession, OutOfOrderChunk, TranscriptPiece
from app.stt.transcriber import Transcriber

live_sessions: dict[UUID, LiveSession] = {}
# asyncio only keeps weak references to tasks; hold them here so they aren't garbage-collected mid-run
_background_tasks: set[asyncio.Task] = set()
log = logging.getLogger(__name__)


router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    title: str | None = None
    source: str | None = None


class SessionOut(BaseModel):
    # reads model as SQLAlchemy object
    model_config = ConfigDict(from_attributes=True)
    session_id: UUID
    title: str | None
    source: str | None
    started_at: datetime
    ended_at: datetime | None

class PendingQuestion(BaseModel):
    # what the question card needs; answer_key is deliberately left out
    model_config = ConfigDict(from_attributes=True)
    question_id: UUID
    prompt: str
    question_type: str | None
    options: list[str] | None


class PendingQuiz(BaseModel):
    quiz_id: UUID | None
    topic: str | None
    questions: list[PendingQuestion]


@cache
def get_transcriber() -> Transcriber:
    return make_transcriber()



def _spawn(coro) -> None:
    """Run coro in the background, holding a strong reference until it finishes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

# HTTP request routes
@router.post("", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreate, db: DbSession = Depends(get_db), user: User = Depends(get_current_user), transcriber: Transcriber = Depends(get_transcriber)):
    new_session = Session(user_id=user.user_id, title=body.title, source=body.source)
    # stage new row
    db.add(new_session)
    # saves to Postgres
    db.commit()
    # reloads row
    db.refresh(new_session)
    live_sessions[new_session.session_id] = LiveSession(transcriber)
    # hands back the database object
    return new_session

@router.patch("/{session_id}/end", response_model=SessionOut)
async def end_session(session_id: UUID, db: DbSession = Depends(get_db)):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    live = live_sessions.pop(session_id, None)
    if live is not None:
        save_pieces(db, session_id, await live.finish())

    if session.ended_at is None:
        session.ended_at = datetime.now(UTC)
        db.commit()
        db.refresh(session)

    return session

@router.get("/{session_id}/questions/pending", response_model=PendingQuiz)
def pending_questions(session_id: UUID, db: DbSession = Depends(get_db), user: User = Depends(get_current_user)):
    """The oldest quiz in this session that still has questions the user hasn't answered, with only those questions."""
    if db.get(Session, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")

    answered = select(Attempt.question_id).where(Attempt.user_id == user.user_id)
    rows = db.execute(
        select(Question, Quiz.topic)
        .join(Quiz, Question.quiz_id == Quiz.quiz_id)
        .where(Quiz.session_id == session_id, Question.question_id.not_in(answered))
        .order_by(Quiz.triggered_at, Question.created_at, Question.prompt)
    ).all()

    if not rows:
        return PendingQuiz(quiz_id=None, topic=None, questions=[])
    first_quiz = rows[0].Question.quiz_id
    return PendingQuiz(
        quiz_id=first_quiz,
        topic=rows[0].topic,
        questions=[PendingQuestion.model_validate(r.Question) for r in rows if r.Question.quiz_id == first_quiz],
    )


@router.post("/{session_id}/chunks", status_code=204)
async def upload_chunk(session_id: UUID, seq: int, request: Request, db: DbSession = Depends(get_db), shift_client: ModelClient = Depends(get_shift_client), smart_client: ModelClient = Depends(get_smart_client)):
    live = live_sessions.get(session_id)
    if live is None:
        raise HTTPException(status_code=409, detail="session is not recording")

    raw = await request.body()
    if not raw or len(raw) % 4 != 0:
        raise HTTPException(status_code=400, detail="body must be float32 samples")

    try:
        pieces = await live.add_chunk(seq, np.frombuffer(raw, dtype=np.float32))
    except OutOfOrderChunk:
        raise HTTPException(status_code=409, detail=f"expected seq {live.next_seq}")

    save_pieces(db, session_id, pieces)

    # topic-shift check runs in the background so this request returns right away
    if not live.checking:
        live.checking = True
        _spawn(checkpoint_task(live, shift_client, smart_client, session_id))


async def checkpoint_task(live: LiveSession, client: ModelClient, smart_client: ModelClient, session_id: UUID) -> None:
    try:
        trigger = await run_checkpoint(live, client)
        if trigger is not None:
            # own DB session: the request's session is closed by the time this runs
            with SessionLocal() as db:
                quiz = Quiz(
                    session_id=session_id,
                    trigger_reason=trigger.reason,
                    span_start_ts=trigger.span_start,
                    span_end_ts=trigger.span_end,
                    topic=trigger.topic,
                )
                db.add(quiz)
                db.commit()
                quiz_id = quiz.quiz_id
            log.info("quiz triggered for %s: %s", session_id, trigger.reason)
            # separate task so the slow LLM call doesn't hold live.checking and skip shift checks
            _spawn(questions_task(smart_client, session_id, quiz_id, trigger))
    except Exception:
        log.exception("checkpoint failed for %s", session_id)
    finally:
        live.checking = False


async def questions_task(client: ModelClient, session_id: UUID, quiz_id: UUID, trigger: QuizTrigger) -> None:
    """Generate, filter and save the quiz's questions. On any failure the quiz row stays, with no questions."""
    try:
        with SessionLocal() as db:
            span = load_span(db, session_id, trigger.span_start, trigger.span_end)
        if span is None:
            log.warning("quiz %s: no transcript in span, no questions", quiz_id)
            return

        # no DB session held during the LLM call
        started = time.perf_counter()
        generated = await generate_questions(client, span, trigger.topic)
        elapsed = time.perf_counter() - started

        kept = keep_grounded(generated, span.text)
        log.info("quiz %s: generated %d questions in %.1fs, kept %d", quiz_id, len(generated), elapsed, len(kept))

        with SessionLocal() as db:
            save_questions(db, session_id, quiz_id, span, kept)
            db.commit()
    except Exception:
        log.exception("question generation failed for quiz %s", quiz_id)


def save_pieces(db: DbSession, session_id: UUID, pieces: list[TranscriptPiece]) -> None:
    for p in pieces:
        db.add(TranscriptChunk(session_id=session_id, seq=p.seq, text_=p.text, start_ts=p.start, end_ts=p.end))

    db.commit()