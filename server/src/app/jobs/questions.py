from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from uuid import UUID
from pathlib import Path

from app.db.models import TranscriptChunk
from app.llm import Message, ModelClient

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

PROMPT = (Path(__file__).parent.parent / "prompts" / "questions_v1.txt").read_text()

QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence": {"type": "string"},        # exact quote from the transcript, written FIRST
                    "prompt": {"type": "string"},
                    "question_type": {"type": "string", "enum": ["short_answer", "multiple_choice"]},
                    "options": {"type": "array", "items": {"type": "string"}},  # [] for short_answer
                    "answer_key": {"type": "string"},
                },
                "required": ["evidence", "prompt", "question_type", "options", "answer_key"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

@dataclass(frozen=True)
class GeneratedQuestion: 
    prompt: str
    question_type: str
    options: list[str]
    answer_key: str
    evidence: str

async def generate_questions(client: ModelClient, span: Span, topic: str | None) -> list[GeneratedQuestion]:
    text = f"TRANSCRIPT\n{span.text}"
    if topic:
        text = f"TOPIC\n{topic}\n\n{text}"

    output = await client.generate(system=PROMPT, messages=[Message(role="user", content=text)], schema=QUESTIONS_SCHEMA)

    questions = []
    for q in output["questions"][:3]:
        gen_q = GeneratedQuestion(prompt=q["prompt"], question_type=q["question_type"], options=q["options"], answer_key=q["answer_key"], evidence=q["evidence"])
        questions.append(gen_q)

    return questions
    