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
