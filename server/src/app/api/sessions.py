import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID
from functools import cache
import numpy as np

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import Quiz, Session, User, TranscriptChunk
from app.db.session import SessionLocal, get_db
from app.llm import ModelClient, make_client
from app.topic_shift import run_checkpoint

from app.stt.factory import make_transcriber
from app.stt.live import LiveSession, OutOfOrderChunk, TranscriptPiece
from app.stt.transcriber import Transcriber

live_sessions: dict[UUID, LiveSession] = {}
# asyncio only keeps weak references to tasks; hold them here so they aren't garbage-collected mid-run
_checkpoint_tasks: set[asyncio.Task] = set()
log = logging.getLogger(__name__)


SEND_EMAIL = "bgao2005@gmail.com"
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

def get_current_user(db: DbSession = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.email == SEND_EMAIL))
    if user is None:
        raise HTTPException(status_code=500, detail="seed user missing; run scripts/seed.py")
    
    return user

@cache
def get_transcriber() -> Transcriber:
    return make_transcriber()

@cache
def get_shift_client() -> ModelClient:
    return make_client("fast")

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

@router.post("/{session_id}/chunks", status_code=204)
async def upload_chunk(session_id: UUID, seq: int, request: Request, db: DbSession = Depends(get_db), shift_client: ModelClient = Depends(get_shift_client)):
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
        task = asyncio.create_task(checkpoint_task(live, shift_client, session_id))
        _checkpoint_tasks.add(task)
        task.add_done_callback(_checkpoint_tasks.discard)


async def checkpoint_task(live: LiveSession, client: ModelClient, session_id: UUID) -> None:
    try:
        trigger = await run_checkpoint(live, client)
        if trigger is not None:
            # own DB session: the request's session is closed by the time this runs
            with SessionLocal() as db:
                db.add(Quiz(
                    session_id=session_id, 
                    trigger_reason=trigger.reason, 
                    span_start_ts=trigger.span_start, 
                    span_end_ts=trigger.span_end, 
                    topic=trigger.topic)
                )
                db.commit()
            log.info("quiz triggered for %s: %s", session_id, trigger.reason)
    except Exception:
        log.exception("checkpoint failed for %s", session_id)
    finally:
        live.checking = False


def save_pieces(db: DbSession, session_id: UUID, pieces: list[TranscriptPiece]) -> None:
    for p in pieces:
        db.add(TranscriptChunk(session_id=session_id, seq=p.seq, text_=p.text, start_ts=p.start, end_ts=p.end))

    db.commit()