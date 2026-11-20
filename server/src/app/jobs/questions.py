from collections.abc import Sequence
from dataclasses import dataclass
import re
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession
from uuid import UUID
from pathlib import Path

from app.db.models import Concept, Mastery, Question, Quiz, Session, TranscriptChunk
from app.llm import Message, ModelClient
from app.jobs.mastery import mastery_tier

@dataclass(frozen=True)
class Span:
    text: str
    start_chunk: int
    end_chunk: int
    start_ts: float
    end_ts: float


@dataclass(frozen=True)
class KnownConcept:
    name: str
    elo: float | None


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

PROMPT = (Path(__file__).parent.parent / "prompts" / "questions_v4.txt").read_text()

QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        # decided FIRST, so concepts are named as units of a standard course, not of this video
        "course": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence": {"type": "string"},        # exact quote from the transcript, written FIRST
                    "concept": {"type": "string"},         # a unit of `course`'s syllabus, decided before writing the question
                    "prompt": {"type": "string"},
                    "question_type": {"type": "string", "enum": ["short_answer", "multiple_choice"]},
                    "options": {"type": "array", "items": {"type": "string"}},  # [] for short_answer
                    "answer_key": {"type": "string"},
                },
                "required": ["evidence", "concept", "prompt", "question_type", "options", "answer_key"],
                "additionalProperties": False,
            },
        },
        # only when questions is empty: why the model wrote none (see the end of the prompt)
        "skip_reason": {"type": "string", "enum": ["not_educational", "too_little_content"]},
    },
    "required": ["course", "questions"],
    "additionalProperties": False,
}

@dataclass(frozen=True)
class GeneratedQuestion: 
    prompt: str
    question_type: str
    options: list[str]
    answer_key: str
    evidence: str
    concept: str


@dataclass(frozen=True)
class GeneratedQuiz:
    course: str                          # the standard course the model placed this lecture in
    questions: list[GeneratedQuestion]
    skip_reason: str | None = None       # set by the model only when it wrote no questions


def build_message(
    span: Span, topic: str | None, known_concepts: Sequence[KnownConcept] = (), lecture_topics: Sequence[str] = (),
    title: str | None = None, course: str | None = None,
) -> str:
    """LECTURE TITLE, COURSE, LECTURE SO FAR, TOPIC, KNOWN CONCEPTS and TRANSCRIPT; all but TRANSCRIPT only when non-empty.

    Each known concept is sent with its mastery tier, "- glycolysis (weak)", which the prompt's adapt rules act on.

    Big picture first: a short excerpt alone doesn't say which course it's from, so the
    title and earlier topics help the model name chapter-level concepts.
    """
    sections = []
    if title:
        sections.append(f"LECTURE TITLE\n{title}")
    if course:
        sections.append(f"COURSE\n{course}")
    if lecture_topics:
        sections.append("LECTURE SO FAR\n" + "\n".join(f"- {t}" for t in lecture_topics))
    if topic:
        sections.append(f"TOPIC\n{topic}")
    if known_concepts:
        sections.append("KNOWN CONCEPTS\n" + "\n".join(f"- {c.name} ({mastery_tier(c.elo)})" for c in known_concepts))
    sections.append(f"TRANSCRIPT\n{span.text}")
    return "\n\n".join(sections)


async def generate_questions(
    client: ModelClient, span: Span, topic: str | None,
    known_concepts: Sequence[KnownConcept] = (), lecture_topics: Sequence[str] = (),
    title: str | None = None, course: str | None = None,
) -> GeneratedQuiz:
    text = build_message(span, topic, known_concepts, lecture_topics, title, course)
    response = await client.generate(system=PROMPT, messages=[Message(role="user", content=text)], schema=QUESTIONS_SCHEMA)

    questions = []
    for q in response.output["questions"][:3]:
        gen_q = GeneratedQuestion(prompt=q["prompt"], question_type=q["question_type"], options=q["options"], answer_key=q["answer_key"], evidence=q["evidence"], concept=q["concept"])
        questions.append(gen_q)

    # a reason next to real questions contradicts the prompt; the questions win
    skip_reason = None if questions else response.output.get("skip_reason")
    return GeneratedQuiz(course=response.output["course"], questions=questions, skip_reason=skip_reason)


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


KNOWN_RECENT = 30   # how many of the user's most recently rated concepts to offer for reuse


def known_concepts(db: DbSession, session_id: UUID) -> list[KnownConcept]:
    """Concepts to offer the generator, each with the user's rating: this session's first, then the user's recently rated ones.

    Two jobs. Reusing names keeps one concept from splitting into near-duplicates ("glycolysis"
    vs "the glycolysis pathway"), which would leave each copy with too few attempts to rate. The
    rating (None if never answered) becomes a mastery tier the prompt adapts its questions to (#26).
    """
    this_session = db.execute(
        select(Concept.name, Mastery.elo)
        .join(Question, Question.concept_id == Concept.concept_id)
        .join(Session, Session.session_id == Question.session_id)
        .outerjoin(Mastery, (Mastery.concept_id == Concept.concept_id) & (Mastery.user_id == Session.user_id))
        .where(Question.session_id == session_id)
        .group_by(Concept.concept_id, Concept.name, Mastery.elo)
        .order_by(Concept.name)
    ).all()
    recent = db.execute(
        select(Concept.name, Mastery.elo)
        .join(Mastery, Mastery.concept_id == Concept.concept_id)
        .join(Session, Session.user_id == Mastery.user_id)
        .where(Session.session_id == session_id)
        .order_by(Mastery.updated_at.desc())
        .limit(KNOWN_RECENT)
    ).all()

    merged = {}
    # dedupe by name, first one wins: this session's concepts stay in front
    for name, elo in [*this_session, *recent]:
        if name not in merged:
            merged[name] = KnownConcept(name, elo)

    return list(merged.values())


def lecture_topics(db: DbSession, session_id: UUID, exclude_quiz_id: UUID | None = None) -> list[str]:
    """Topics of this session's earlier quizzes, oldest first, without blanks or repeats.

    The current quiz is excluded: its topic is already sent as TOPIC.
    """
    query = (
        select(Quiz.topic)
        .where(Quiz.session_id == session_id, Quiz.topic.is_not(None), Quiz.topic != "")
        .order_by(Quiz.triggered_at, Quiz.span_start_ts)
    )
    if exclude_quiz_id is not None:
        query = query.where(Quiz.quiz_id != exclude_quiz_id)
    return list(dict.fromkeys(db.scalars(query).all()))


def concept_key(name: str) -> str:
    """Normalized name used to match concepts: "Glycolysis." and "glycolysis" are the same concept."""
    return _normalize(name)


def get_or_create_concept(db: DbSession, name: str) -> UUID | None:
    """The concept_id for this name, inserting it if new. None for a blank name.

    INSERT ... ON CONFLICT DO NOTHING on the unique name_key, so two quizzes generating at
    the same time can't create the same concept twice.
    """
    key = concept_key(name)
    if not key:
        return None
    db.execute(insert(Concept).values(name=name.strip(), name_key=key).on_conflict_do_nothing(index_elements=["name_key"]))
    return db.scalar(select(Concept.concept_id).where(Concept.name_key == key))


def save_questions(db: DbSession, session_id: UUID, quiz_id: UUID, span: Span, questions: list[GeneratedQuestion]) -> None:
    """Add one Question row per question, each carrying the span it's grounded in and its concept. The caller commits."""
    for q in questions:
        db.add(Question(
            session_id=session_id,
            quiz_id=quiz_id,
            concept_id=get_or_create_concept(db, q.concept),   # None for a blank concept: no rating
            prompt=q.prompt,
            answer_key=q.answer_key,
            question_type=q.question_type,
            options=q.options or None,  # null for short_answer
            span_text=span.text,
            span_start_chunk=span.start_chunk,
            span_end_chunk=span.end_chunk,
            span_start_ts=span.start_ts,
            span_end_ts=span.end_ts,
        ))

def save_course(db: DbSession, session_id: UUID, course: str) -> None:
    course = course.strip().lower()
    if not course:
        return

    db.execute(
        update(Session)
        .where(Session.session_id == session_id, Session.course.is_(None))
        .values(course=course)
    )