"""get_or_create_concept and known_concepts against the local Postgres (rolled back after each test)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import Concept, Mastery, Question, Session, User
from app.jobs.questions import get_or_create_concept, known_concepts


def concept_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Concept))


# --- get_or_create_concept ---

def test_creates_a_concept_with_its_normalized_key(db):
    concept_id = get_or_create_concept(db, "  Glycolysis. ")
    row = db.get(Concept, concept_id)
    assert (row.name, row.name_key) == ("Glycolysis.", "glycolysis")


def test_same_name_after_normalizing_reuses_the_concept(db):
    first = get_or_create_concept(db, "Krebs cycle")
    before = concept_count(db)
    assert get_or_create_concept(db, "krebs-cycle!") == first
    assert get_or_create_concept(db, "KREBS   CYCLE") == first
    assert concept_count(db) == before


def test_different_names_are_different_concepts(db):
    assert get_or_create_concept(db, "glycolysis") != get_or_create_concept(db, "krebs cycle")


def test_blank_name_is_none(db):
    before = concept_count(db)
    assert get_or_create_concept(db, "") is None
    assert get_or_create_concept(db, " ?! ") is None   # nothing left after normalizing
    assert concept_count(db) == before


# --- known_concepts ---

def add_question(db, session_id, concept_name):
    db.add(Question(session_id=session_id, prompt="p", concept_id=get_or_create_concept(db, concept_name)))
    db.flush()


def rate(db, user_id, concept_name, minutes_ago):
    db.add(Mastery(
        user_id=user_id,
        concept_id=get_or_create_concept(db, concept_name),
        updated_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    ))
    db.flush()


def test_nothing_known_is_empty(db, recording):
    assert known_concepts(db, recording.session_id) == []


def test_session_concepts_then_recently_rated_ones(db, recording, user):
    add_question(db, recording.session_id, "photosynthesis")
    add_question(db, recording.session_id, "glycolysis")
    add_question(db, recording.session_id, "glycolysis")      # used twice, listed once
    rate(db, user.user_id, "osmosis", minutes_ago=50)
    rate(db, user.user_id, "mitosis", minutes_ago=5)
    rate(db, user.user_id, "glycolysis", minutes_ago=1)      # already listed from the session

    assert known_concepts(db, recording.session_id) == ["glycolysis", "photosynthesis", "mitosis", "osmosis"]


def test_other_users_ratings_and_other_sessions_are_ignored(db, recording):
    stranger = User(user_name="Other", email="other-known-concepts@example.com")
    db.add(stranger)
    db.flush()
    other_session = Session(user_id=stranger.user_id)
    db.add(other_session)
    db.flush()
    add_question(db, other_session.session_id, "supply and demand")
    rate(db, stranger.user_id, "inflation", minutes_ago=1)

    assert known_concepts(db, recording.session_id) == []
