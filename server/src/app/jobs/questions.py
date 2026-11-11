from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from uuid import UUID

from app.db.models import TranscriptChunk



@dataclass(frozen=True)
class Span:
    text: str
    start_chunk: int
    end_chunk: int
    start_ts: float
    end_ts: float


def load_span(db: DbSession, session_id: UUID, start: float, end: float) -> Span | None:
    mid = (TranscriptChunk.start_ts + TranscriptChunk.end_ts) / 2
    chunks = db.scalars(
        select(TranscriptChunk)
        .where(TranscriptChunk.session_id == session_id, mid >= start, mid < end)
        .order_by(TranscriptChunk.seq)
    ).all()

    if not chunks:
        return None

    span = Span(
        text=" ".join(chunk.text_ for chunk in chunks), 
        start_chunk=chunks[0].seq, 
        end_chunk=chunks[-1].seq, 
        start_ts=chunks[0].start_ts, 
        end_ts=chunks[-1].end_ts
    )

    return span