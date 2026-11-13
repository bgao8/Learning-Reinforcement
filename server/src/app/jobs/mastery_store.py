"""Saving rating changes (#25): applies the rules in jobs/mastery.py to the mastery table."""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from app.db.models import Attempt, Concept, Mastery, Question
from app.jobs.mastery import START_RATING, apply_change, is_calibrating


@dataclass(frozen=True)
class RatingUpdate:
    concept: str
    elo_before: float
    elo_after: float
    calibrating: bool   # still calibrating after this answer


def graded_attempts(db: DbSession, user_id: UUID, concept_id: UUID) -> int:
    """How many of this user's answers on this concept were graded (ungraded ones don't count)."""
    return db.scalar(
        select(func.count())
        .select_from(Attempt)
        .join(Question, Question.question_id == Attempt.question_id)
        .where(Attempt.user_id == user_id, Question.concept_id == concept_id, Attempt.score.is_not(None))
    )


def record_answer(db: DbSession, user_id: UUID, concept_id: UUID, score: float) -> RatingUpdate:
    """Move the user's rating for this concept after one graded answer.

    Call it BEFORE adding the new Attempt, so the attempt count is the answers before this
    one. The caller commits, so the rating and the attempt are saved together.
    """
    attempts_before = graded_attempts(db, user_id, concept_id)

    # first answer on this concept: create the row at the start rating
    db.execute(
        insert(Mastery)
        .values(user_id=user_id, concept_id=concept_id, elo=START_RATING)
        .on_conflict_do_nothing(index_elements=["user_id", "concept_id"])
    )
    # lock the row so two answers at once can't both read the old rating
    row = db.scalars(
        select(Mastery).where(Mastery.user_id == user_id, Mastery.concept_id == concept_id).with_for_update()
    ).one()

    before = row.elo
    row.elo = apply_change(before, score, attempts_before)
    row.updated_at = func.now()
    db.flush()

    return RatingUpdate(
        concept=db.get(Concept, concept_id).name,
        elo_before=before,
        elo_after=row.elo,
        calibrating=is_calibrating(attempts_before + 1),
    )
