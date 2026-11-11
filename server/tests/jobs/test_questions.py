"""load_span against the local Postgres (rolled back after each test)."""
from app.db.models import Session, TranscriptChunk
from app.jobs.questions import Span, load_span


def add_chunks(db, session_id, chunks):
    """chunks: (seq, start_ts, end_ts, text) tuples."""
    for seq, start, end, text in chunks:
        db.add(TranscriptChunk(session_id=session_id, seq=seq, start_ts=start, end_ts=end, text_=text))
    db.flush()


SIX = [
    (0, 0.0, 5.0, "so glycolysis"),
    (1, 5.0, 10.0, "happens in the"),
    (2, 10.0, 15.0, "cytoplasm and"),
    (3, 15.0, 20.0, "splits glucose"),
    (4, 20.0, 25.0, "into two"),
    (5, 25.0, 30.0, "pyruvate"),
]


def test_loads_chunks_in_range_as_one_span(db, recording):
    add_chunks(db, recording.session_id, SIX)
    span = load_span(db, recording.session_id, 0.0, 15.0)
    assert span == Span(
        text="so glycolysis happens in the cytoplasm and",
        start_chunk=0,
        end_chunk=2,
        start_ts=0.0,
        end_ts=15.0,
    )


def test_chunks_are_joined_in_seq_order(db, recording):
    add_chunks(db, recording.session_id, list(reversed(SIX)))  # inserted backwards
    span = load_span(db, recording.session_id, 0.0, 30.0)
    assert span.text.startswith("so glycolysis")
    assert (span.start_chunk, span.end_chunk) == (0, 5)


def test_chunk_belongs_to_the_side_of_its_midpoint(db, recording):
    add_chunks(db, recording.session_id, SIX)
    # boundary at 12.0 cuts chunk 2 (10-15, midpoint 12.5): it goes to the later span
    before = load_span(db, recording.session_id, 0.0, 12.0)
    after = load_span(db, recording.session_id, 12.0, 30.0)
    assert (before.start_chunk, before.end_chunk) == (0, 1)
    assert (after.start_chunk, after.end_chunk) == (2, 5)


def test_midpoint_exactly_on_end_goes_to_next_span(db, recording):
    add_chunks(db, recording.session_id, SIX)
    # chunk 2 midpoint is 12.5: excluded from [0, 12.5), included in [12.5, 30)
    assert load_span(db, recording.session_id, 0.0, 12.5).end_chunk == 1
    assert load_span(db, recording.session_id, 12.5, 30.0).start_chunk == 2


def test_gaps_in_seq_are_fine(db, recording):
    # seq 1 was a silent window: no row
    add_chunks(db, recording.session_id, [SIX[0], SIX[2], SIX[3]])
    span = load_span(db, recording.session_id, 0.0, 20.0)
    assert (span.start_chunk, span.end_chunk) == (0, 3)
    assert span.text == "so glycolysis cytoplasm and splits glucose"


def test_empty_range_is_none(db, recording):
    add_chunks(db, recording.session_id, SIX)
    assert load_span(db, recording.session_id, 100.0, 200.0) is None


def test_session_with_no_chunks_is_none(db, recording):
    assert load_span(db, recording.session_id, 0.0, 600.0) is None


def test_other_sessions_chunks_are_ignored(db, recording, user):
    other = Session(user_id=user.user_id)
    db.add(other)
    db.flush()
    add_chunks(db, other.session_id, SIX)
    add_chunks(db, recording.session_id, [SIX[0]])
    span = load_span(db, recording.session_id, 0.0, 30.0)
    assert span.text == "so glycolysis"
