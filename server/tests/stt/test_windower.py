import numpy as np

from app.stt.transcriber import SAMPLE_RATE, Word
from app.stt.windower import AudioWindower, Window, owned_words


def ramp(seconds: float, start: float = 0.0) -> np.ndarray:
    """Audio where each sample's value IS its lecture time, so slices are checkable."""
    n = round(seconds * SAMPLE_RATE)
    return (start + np.arange(n) / SAMPLE_RATE).astype(np.float32)


def feed_all(windower: AudioWindower, sizes: list[float]) -> list[Window]:
    windows, t = [], 0.0
    for size in sizes:
        windows += windower.feed(ramp(size, t))
        t += size
    return windows


def spans(windows: list[Window]) -> list[tuple[float, float, float]]:
    return [(w.t0, w.own_start, w.own_end) for w in windows]


def test_no_window_until_right_margin_arrives():
    assert AudioWindower().feed(ramp(5.9)) == []


def test_windows_overlap_and_owned_zones_tile():
    windows = feed_all(AudioWindower(), [4, 4, 4, 4])
    assert spans(windows) == [(0, 0, 5), (4, 5, 10), (9, 10, 15)]


def test_window_lengths_first_has_no_left_margin():
    windows = feed_all(AudioWindower(), [16])
    assert [len(w.samples) / SAMPLE_RATE for w in windows] == [6, 7, 7]


def test_window_samples_are_the_right_audio():
    window = feed_all(AudioWindower(), [4, 4, 4])[1]
    assert np.isclose(window.samples[0], 4.0)
    assert np.isclose(window.samples[-1], 11.0, atol=1e-3)


def test_chunk_size_does_not_change_windows():
    small = feed_all(AudioWindower(), [1] * 16)
    large = feed_all(AudioWindower(), [16])
    assert spans(small) == spans(large)


def test_buffer_stays_bounded():
    windower = AudioWindower()
    biggest = 0
    for i in range(3600):                      # one hour, 1 s at a time
        windower.feed(np.zeros(SAMPLE_RATE, dtype=np.float32))
        biggest = max(biggest, len(windower._buf))
    assert biggest <= 7 * SAMPLE_RATE


def test_flush_owns_the_tail():
    windower = AudioWindower()
    feed_all(windower, [4, 4, 4, 4, 1.5])
    last = windower.flush()
    assert (last.t0, last.own_start, last.own_end) == (14, 15, 17.5)


def test_flush_with_nothing_left_returns_none():
    assert AudioWindower().flush() is None


def test_owned_words_shifts_to_lecture_time_and_filters():
    window = Window(t0=4.0, own_start=5.0, own_end=10.0, samples=np.zeros(0))
    words = [
        Word(0.3, 0.9, "before"),   # mid 4.6: previous window's
        Word(1.4, 1.9, "kept"),     # mid 5.65
        Word(6.6, 7.0, "after"),    # mid 10.8: next window's
    ]
    assert owned_words(window, words) == [Word(5.4, 5.9, "kept")]


def test_straddling_word_has_exactly_one_owner():
    a = Window(t0=4.0, own_start=5.0, own_end=10.0, samples=np.zeros(0))
    b = Window(t0=9.0, own_start=10.0, own_end=15.0, samples=np.zeros(0))
    from_a = owned_words(a, [Word(5.8, 6.3, "supply")])   # 9.8–10.3 in lecture time
    from_b = owned_words(b, [Word(0.8, 1.3, "supply")])
    assert len(from_a) + len(from_b) == 1
