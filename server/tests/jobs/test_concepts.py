"""get_or_create_concept, known_concepts and lecture_topics against the local Postgres (rolled back after each test)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import Concept, Mastery, Question, Quiz, Session, User
from app.jobs.questions import KnownConcept, get_or_create_concept, known_concepts, lecture_topics


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


def rate(db, user_id, concept_name, minutes_ago, elo=1000.0):
    db.add(Mastery(
        user_id=user_id,
        concept_id=get_or_create_concept(db, concept_name),
        elo=elo,
        updated_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    ))
    db.flush()


def test_nothing_known_is_empty(db, recording):
    assert known_concepts(db, recording.session_id) == []


def test_session_concepts_then_recently_rated_ones(db, recording, user):
    add_question(db, recording.session_id, "photosynthesis")
    add_question(db, recording.session_id, "glycolysis")
    add_question(db, recording.session_id, "glycolysis")      # used twice, listed once
    rate(db, user.user_id, "osmosis", minutes_ago=50, elo=940.0)
    rate(db, user.user_id, "mitosis", minutes_ago=5, elo=1060.0)
    rate(db, user.user_id, "glycolysis", minutes_ago=1)      # already listed from the session

    assert known_concepts(db, recording.session_id) == [
        KnownConcept("glycolysis", 1000.0),
        KnownConcept("photosynthesis", None),
        KnownConcept("mitosis", 1060.0),
        KnownConcept("osmosis", 940.0),
    ]


def test_session_concept_carries_the_users_rating(db, recording, user):
    add_question(db, recording.session_id, "glycolysis")
    rate(db, user.user_id, "glycolysis", minutes_ago=1, elo=940.0)

    assert known_concepts(db, recording.session_id) == [KnownConcept("glycolysis", 940.0)]


def test_unrated_session_concept_is_kept_with_no_rating(db, recording):
    # asked this session but not answered yet: kept (outer join), elo None, not dropped
    add_question(db, recording.session_id, "photosynthesis")

    assert known_concepts(db, recording.session_id) == [KnownConcept("photosynthesis", None)]


def test_session_concept_ignores_another_users_rating(db, recording):
    stranger = User(user_name="Other", email="other-rating@example.com")
    db.add(stranger)
    db.flush()
    add_question(db, recording.session_id, "glycolysis")
    rate(db, stranger.user_id, "glycolysis", minutes_ago=1, elo=1500.0)

    assert known_concepts(db, recording.session_id) == [KnownConcept("glycolysis", None)]


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


# --- lecture_topics ---

def add_quiz(db, session_id, topic, start):
    quiz = Quiz(session_id=session_id, trigger_reason="topic_shift", span_start_ts=start, span_end_ts=start + 150, topic=topic)
    db.add(quiz)
    db.flush()
    return quiz


def test_earlier_topics_oldest_first_without_blanks_or_repeats(db, recording):
    add_quiz(db, recording.session_id, "enzymes", start=150)
    add_quiz(db, recording.session_id, "cell structure", start=0)
    add_quiz(db, recording.session_id, None, start=300)
    add_quiz(db, recording.session_id, "", start=450)
    add_quiz(db, recording.session_id, "enzymes", start=600)
    assert lecture_topics(db, recording.session_id) == ["cell structure", "enzymes"]


def test_current_quiz_is_excluded(db, recording):
    add_quiz(db, recording.session_id, "cell structure", start=0)
    current = add_quiz(db, recording.session_id, "glycolysis", start=150)
    assert lecture_topics(db, recording.session_id, exclude_quiz_id=current.quiz_id) == ["cell structure"]


def test_other_sessions_topics_are_ignored(db, recording, user):
    other = Session(user_id=user.user_id)
    db.add(other)
    db.flush()
    add_quiz(db, other.session_id, "macroeconomics", start=0)
    assert lecture_topics(db, recording.session_id) == []
