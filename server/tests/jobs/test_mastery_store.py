"""record_answer against the local Postgres (rolled back after each test)."""
import pytest
from sqlalchemy import select

from app.db.models import Attempt, Mastery, Question, User
from app.jobs.mastery import START_RATING, apply_change
from app.jobs.mastery_store import graded_attempts, record_answer
from app.jobs.questions import get_or_create_concept


def concept(db, name="glycolysis"):
    return get_or_create_concept(db, name)


def answered(db, user_id, session_id, concept_id, score):
    """An earlier answer on a question of this concept (score None = grading failed)."""
    question = Question(session_id=session_id, prompt="p", concept_id=concept_id)
    db.add(question)
    db.flush()
    db.add(Attempt(question_id=question.question_id, user_id=user_id, user_answer="a", score=score))
    db.flush()


def rating(db, user_id, concept_id):
    return db.scalars(select(Mastery.elo).where(Mastery.user_id == user_id, Mastery.concept_id == concept_id)).one()


def test_first_answer_creates_the_row_at_1000_and_moves_it(db, user):
    c = concept(db)
    update = record_answer(db, user.user_id, c, 1.0)
    assert (update.concept, update.elo_before, update.elo_after, update.calibrating) == ("glycolysis", START_RATING, 1030, True)
    assert rating(db, user.user_id, c) == 1030


def test_a_wrong_answer_lowers_it(db, user):
    c = concept(db)
    assert record_answer(db, user.user_id, c, 0.0).elo_after == 970


def test_earlier_answers_decide_calibration(db, user, recording):
    c = concept(db)
    for _ in range(3):
        answered(db, user.user_id, recording.session_id, c, 1.0)
    db.add(Mastery(user_id=user.user_id, concept_id=c, elo=1090))
    db.flush()

    update = record_answer(db, user.user_id, c, 1.0)

    assert update.elo_after == pytest.approx(apply_change(1090, 1.0, 3))   # weighted, not +30
    assert update.calibrating is False


def test_third_answer_is_the_last_calibrating_one(db, user, recording):
    c = concept(db)
    for _ in range(2):
        answered(db, user.user_id, recording.session_id, c, 1.0)
    update = record_answer(db, user.user_id, c, 1.0)
    assert update.elo_after - update.elo_before == 30   # still a fixed step
    assert update.calibrating is False                # but calibration is now done


def test_ungraded_and_other_users_answers_dont_count(db, user, recording):
    c = concept(db)
    stranger = User(user_name="Other", email="other-mastery-store@example.com")
    db.add(stranger)
    db.flush()
    answered(db, user.user_id, recording.session_id, c, None)        # grading failed
    answered(db, stranger.user_id, recording.session_id, c, 1.0)     # someone else
    assert graded_attempts(db, user.user_id, c) == 0


def test_concepts_are_rated_separately(db, user):
    a, b = concept(db, "glycolysis"), concept(db, "krebs cycle")
    record_answer(db, user.user_id, a, 1.0)
    record_answer(db, user.user_id, b, 0.0)
    assert (rating(db, user.user_id, a), rating(db, user.user_id, b)) == (1030, 970)
