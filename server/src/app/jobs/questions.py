from dataclasses import dataclass
import re
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

    response = await client.generate(system=PROMPT, messages=[Message(role="user", content=text)], schema=QUESTIONS_SCHEMA)

    questions = []
    for q in response.output["questions"][:3]:
        gen_q = GeneratedQuestion(prompt=q["prompt"], question_type=q["question_type"], options=q["options"], answer_key=q["answer_key"], evidence=q["evidence"])
        questions.append(gen_q)

    return questions


_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    # punctuation -> space (so "two-step" matches Whisper's "two step"), then collapse
    return _SPACE.sub(" ", _PUNCT.sub(" ", s.lower())).strip()


def _well_formed(q: GeneratedQuestion) -> bool:
    if q.question_type == "multiple_choice":
        return len(q.options) >= 2 and q.answer_key in q.options
    return not q.options  # short_answer


def keep_grounded(questions: list[GeneratedQuestion], span_text: str) -> list[GeneratedQuestion]:
    # pad with spaces so evidence only matches on whole-word boundaries
    span = f" {_normalize(span_text)} "
    kept = []
    for q in questions:
        evidence = _normalize(q.evidence)
        if evidence and f" {evidence} " in span and _well_formed(q):
            kept.append(q)
    return kept
