"""Answer a question: POST /questions/{question_id}/attempts grades the answer, saves an Attempt,
and moves the user's rating for the question's concept (#25)."""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from sqlalchemy import select

from app.api.deps import get_current_user, get_smart_client
from app.db.models import Attempt, Question, User, Session, Quiz
from app.db.session import get_db
from app.jobs.grading import grade
from app.jobs.mastery_store import record_answer
from app.llm import ModelClient, ModelError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/questions", tags=["questions"])


class AttemptCreate(BaseModel):
    user_answer: str


class AttemptOut(BaseModel):
    attempt_id: UUID
    graded: bool  # False when the model call failed; the answer is still saved
    is_correct: bool | None
    score: float | None
    feedback: str | None
    # revealed only after answering, so the UI can mark the right option on a wrong pick (#59)
    answer_key: str | None = None
    # rating change (#25); all None when the answer wasn't graded or the question has no concept
    concept: str | None = None
    elo_before: float | None = None
    elo_after: float | None = None
    calibrating: bool | None = None


@router.post("/{question_id}/attempts", response_model=AttemptOut, status_code=201)
async def create_attempt(
    question_id: UUID,
    body: AttemptCreate,
    db: DbSession = Depends(get_db),
    user: User = Depends(get_current_user),
    client: ModelClient = Depends(get_smart_client),
):
    question = db.scalar(
        select(Question)
        .join(Session, Question.session_id == Session.session_id)
        .where(Question.question_id == question_id, Session.user_id == user.user_id)
    )
    if question is None:
        raise HTTPException(status_code=404, detail="question not found")

    try:
        result = await grade(client, question, body.user_answer)
    except ModelError:
        log.exception("grading failed for question %s", question_id)
        result = None

    # rate before adding the attempt, so the count of earlier answers excludes this one
    rating = None
    if result is not None and question.concept_id is not None:
        rating = record_answer(db, user.user_id, question.concept_id, result.score)

    attempt = Attempt(
        question_id=question_id,
        user_id=user.user_id,
        user_answer=body.user_answer,
        is_correct=result.is_correct if result else None,
        score=result.score if result else None,
        feedback=result.feedback if result else None,
    )
    db.add(attempt)
    db.commit()

    return AttemptOut(
        attempt_id=attempt.attempt_id,
        graded=result is not None,
        is_correct=attempt.is_correct,
        score=attempt.score,
        feedback=attempt.feedback,
        answer_key=question.answer_key,
        concept=rating.concept if rating else None,
        elo_before=rating.elo_before if rating else None,
        elo_after=rating.elo_after if rating else None,
        calibrating=rating.calibrating if rating else None,
    )
