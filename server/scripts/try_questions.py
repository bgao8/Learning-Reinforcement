"""Replay question generation on an existing quiz with the real smart model.

    python scripts/try_questions.py                 # latest quiz
    python scripts/try_questions.py <quiz_id>       # a specific quiz
    python scripts/try_questions.py --save          # also write the Question rows

    python scripts/try_questions.py --session 80a22956 [--start 0 --end 150] [--topic "..."]
    python scripts/try_questions.py --session latest  # session with the newest chunks

Session mode runs on any transcript range without a quiz, so it can't --save
(a Question row needs a quiz_id). Without --save nothing is written.
Each run is one real (billed) model call.
"""
import argparse
import asyncio
import textwrap
import time
from uuid import UUID

from sqlalchemy import String, cast, func, select

from app.db.models import Quiz, TranscriptChunk
from app.db.session import SessionLocal
from app.jobs.questions import (
    PROMPT, QUESTIONS_SCHEMA, GeneratedQuestion, _well_formed, keep_grounded, load_span, save_questions,
)
from app.llm import Message, make_client


def pick_quiz(db, quiz_id: str | None) -> Quiz:
    if quiz_id:
        quiz = db.get(Quiz, UUID(quiz_id))
    else:
        quiz = db.scalars(
            select(Quiz).where(Quiz.span_end_ts.is_not(None)).order_by(Quiz.triggered_at.desc()).limit(1)
        ).first()
    if quiz is None:
        raise SystemExit("no matching quiz with a span")
    return quiz


def pick_session(db, ref: str) -> UUID:
    """Full id, unique prefix, or "latest" (the session with the most recent chunk)."""
    if ref == "latest":
        session_id = db.scalar(
            select(TranscriptChunk.session_id).order_by(TranscriptChunk.created_at.desc()).limit(1)
        )
        if session_id is None:
            raise SystemExit("no transcript chunks in the DB")
        return session_id
    matches = db.scalars(
        select(TranscriptChunk.session_id).distinct()
        .where(cast(TranscriptChunk.session_id, String).startswith(ref.lower()))
    ).all()
    if len(matches) != 1:
        raise SystemExit(f"session {ref!r} matches {len(matches)} sessions with transcripts")
    return matches[0]


def drop_reason(q: GeneratedQuestion) -> str:
    return "malformed" if not _well_formed(q) else "evidence not in span"


async def main(args) -> None:
    with SessionLocal() as db:
        if args.session:
            session_id = pick_session(db, args.session)
            start = args.start if args.start is not None else 0.0
            end = args.end if args.end is not None else db.scalar(
                select(func.max(TranscriptChunk.end_ts)).where(TranscriptChunk.session_id == session_id)
            ) + 1  # load_span's end is exclusive
            qid, topic = None, args.topic
            print(f"session {session_id}  (no quiz, topic={topic!r})")
        else:
            quiz = pick_quiz(db, args.quiz_id)
            session_id, qid, topic = quiz.session_id, quiz.quiz_id, quiz.topic
            start, end = quiz.span_start_ts, quiz.span_end_ts
            print(f"quiz {qid}  ({quiz.trigger_reason}, topic={topic!r})")
        print(f"span {start:.0f}s -> {end:.0f}s")
        span = load_span(db, session_id, start, end)

    if span is None:
        raise SystemExit("no transcript chunks in that span")
    print(f"span text: {len(span.text.split())} words, chunks {span.start_chunk}-{span.end_chunk}")
    print(textwrap.indent(textwrap.fill(span.text[:400] + " ...", 100), "  "), "\n")

    # same prompt/schema as generate_questions, but keep the Response for timing and usage
    text = f"TRANSCRIPT\n{span.text}"
    if topic:
        text = f"TOPIC\n{topic}\n\n{text}"
    client = make_client("smart")
    started = time.perf_counter()
    response = await client.generate(system=PROMPT, messages=[Message(role="user", content=text)], schema=QUESTIONS_SCHEMA)
    elapsed = time.perf_counter() - started

    generated = [GeneratedQuestion(**q) for q in response.output["questions"][:3]]
    kept = keep_grounded(generated, span.text)

    for i, q in enumerate(generated, 1):
        status = "KEPT" if q in kept else f"DROPPED ({drop_reason(q)})"
        print(f"[{i}] {status}  {q.question_type}")
        print(f"    Q: {q.prompt}")
        if q.options:
            print(f"    options: {q.options}")
        print(f"    A: {q.answer_key}")
        print(f"    evidence: {q.evidence!r}\n")

    usage = response.raw.usage
    print(f"{client.model}: {elapsed:.1f}s wall, {response.attempts} attempt(s), "
          f"{usage.input_tokens} in / {usage.output_tokens} out tokens, stop={response.raw.stop_reason}")
    print(f"kept {len(kept)} of {len(generated)}")

    if args.save:
        with SessionLocal() as db:
            save_questions(db, session_id, qid, span, kept)
            db.commit()
        print(f"saved {len(kept)} question rows for quiz {qid}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("quiz_id", nargs="?")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--session", help="session id, unique prefix, or 'latest' (runs without a quiz)")
    parser.add_argument("--start", type=float, help="span start in seconds (session mode, default 0)")
    parser.add_argument("--end", type=float, help="span end in seconds (session mode, default end of transcript)")
    parser.add_argument("--topic", help="topic hint to send (session mode)")
    args = parser.parse_args()

    if args.session and (args.quiz_id or args.save):
        parser.error("--session can't be combined with a quiz_id or --save")
    if not args.session and any(v is not None for v in (args.start, args.end, args.topic)):
        parser.error("--start/--end/--topic only apply with --session")
    asyncio.run(main(args))
