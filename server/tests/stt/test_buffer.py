from app.stt.buffer import TranscriptBuffer
from app.stt.transcriber import Word

WORDS = [
    Word(40.0, 40.5, "supply"),
    Word(40.6, 40.8, "and"),
    Word(40.9, 41.5, "demand"),
    Word(44.0, 44.6, "curves"),
]


def filled(**kwargs) -> TranscriptBuffer:
    buffer = TranscriptBuffer(**kwargs)
    buffer.add(WORDS)
    return buffer


def test_empty_buffer_returns_empty_string():
    assert TranscriptBuffer().last(10) == ""


def test_adding_nothing_is_safe():
    buffer = TranscriptBuffer()
    buffer.add([])
    assert buffer.last(10) == ""


def test_last_is_measured_back_from_newest_word():
    assert filled().last(2.0) == "curves"


def test_last_returns_words_in_spoken_order():
    assert filled().last(5.0) == "supply and demand curves"


def test_asking_for_more_than_exists_returns_everything():
    assert filled().last(10_000) == "supply and demand curves"


def test_words_older_than_keep_are_dropped():
    assert filled(keep_s=3.0).last(10_000) == "curves"


def test_trimming_happens_across_separate_adds():
    buffer = TranscriptBuffer(keep_s=10.0)
    buffer.add([Word(0.0, 1.0, "old")])
    buffer.add([Word(20.0, 21.0, "new")])
    assert buffer.last(10_000) == "new"


def test_last_end_is_end_of_newest_word():
    assert filled().last_end == 44.6


def test_last_end_of_empty_buffer_is_zero():
    assert TranscriptBuffer().last_end == 0.0


def test_between_excludes_start_includes_end():
    # word ends: 40.5, 40.8, 41.5, 44.6
    assert filled().between(40.5, 41.5) == "and demand"


def test_between_with_no_words_in_range_is_empty():
    assert filled().between(0.0, 30.0) == ""
    assert TranscriptBuffer().between(0.0, 100.0) == ""


def test_between_and_last_split_without_overlap_or_gaps():
    # one word ending every second, 1..200
    buffer = TranscriptBuffer()
    buffer.add([Word(t - 0.5, float(t), f"w{t}") for t in range(1, 201)])
    now = buffer.last_end

    previous = buffer.between(now - 120, now - 60).split()
    recent = buffer.last(60).split()

    assert previous == [f"w{t}" for t in range(81, 141)]
    assert recent == [f"w{t}" for t in range(141, 201)]
