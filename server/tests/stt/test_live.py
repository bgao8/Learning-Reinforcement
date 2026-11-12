import numpy as np
import pytest

from app.config import settings
from app.stt.live import LiveSession, OutOfOrderChunk
from app.stt.transcriber import SAMPLE_RATE, Word

pytestmark = pytest.mark.anyio


class FakeTranscriber:
    """Says one word in the middle of each window's owned stretch, and records its calls."""

    def __init__(self):
        self.calls = []

    async def transcribe(self, samples):
        return ""

    async def transcribe_words(self, samples):
        self.calls.append(len(samples) / SAMPLE_RATE)
        n = len(self.calls)
        # the first window has no left margin, so its owned stretch starts at 0, not 1
        mid = 2.5 if n == 1 else 3.5
        return [Word(mid - 0.1, mid + 0.1, f"word{n}")]


def loud(seconds: float) -> np.ndarray:
    return np.full(round(seconds * SAMPLE_RATE), 0.1, dtype=np.float32)


def quiet(seconds: float) -> np.ndarray:
    return np.zeros(round(seconds * SAMPLE_RATE), dtype=np.float32)


async def test_chunks_become_transcript():
    fake = FakeTranscriber()
    live = LiveSession(fake)
    for seq in range(3):
        await live.add_chunk(seq, loud(5))
    assert fake.calls == [6, 7]
    assert live.buffer.last(1000) == "word1 word2"


async def test_wrong_seq_is_rejected_and_nothing_is_transcribed():
    fake = FakeTranscriber()
    live = LiveSession(fake)
    with pytest.raises(OutOfOrderChunk):
        await live.add_chunk(1, loud(10))
    assert fake.calls == []
    assert live.next_seq == 0


async def test_repeated_seq_is_rejected():
    live = LiveSession(FakeTranscriber())
    await live.add_chunk(0, loud(5))
    with pytest.raises(OutOfOrderChunk):
        await live.add_chunk(0, loud(5))


async def test_silent_windows_skip_whisper():
    fake = FakeTranscriber()
    live = LiveSession(fake)
    await live.add_chunk(0, quiet(10))
    assert fake.calls == []
    assert live.buffer.last(1000) == ""


async def test_finish_transcribes_the_tail():
    fake = FakeTranscriber()
    live = LiveSession(fake)
    await live.add_chunk(0, loud(3))
    assert fake.calls == []
    await live.finish()
    assert fake.calls == [3]
    assert live.buffer.last(1000) == "word1"


async def test_finish_with_no_audio_does_nothing():
    fake = FakeTranscriber()
    await LiveSession(fake).finish()
    assert fake.calls == []


async def test_add_chunk_returns_one_piece_per_window_with_words():
    live = LiveSession(FakeTranscriber())
    assert await live.add_chunk(0, loud(5)) == []
    pieces = await live.add_chunk(1, loud(5))
    assert [(p.seq, p.start, p.end, p.text) for p in pieces] == [(0, 0, 5, "word1")]


async def test_silent_window_uses_up_its_seq():
    live = LiveSession(FakeTranscriber())
    await live.add_chunk(0, quiet(6))                 # window 0 (0–5 s) is silent
    pieces = await live.add_chunk(1, loud(5))         # window 1 (5–10 s) has words
    assert [p.seq for p in pieces] == [1]
    assert pieces[0].start == 5


async def test_finish_returns_the_tail_piece():
    live = LiveSession(FakeTranscriber())
    await live.add_chunk(0, loud(3))
    pieces = await live.finish()
    assert [(p.seq, p.start, p.end) for p in pieces] == [(0, 0, 3)]


async def test_finish_with_no_audio_returns_empty_list():
    assert await LiveSession(FakeTranscriber()).finish() == []


async def test_gate_timings_come_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "gate_cooldown_s", 11.0)
    monkeypatch.setattr(settings, "gate_force_s", 22.0)
    monkeypatch.setattr(settings, "gate_check_every_s", 3.0)
    gate = LiveSession(FakeTranscriber()).gate
    assert (gate.cooldown_s, gate.force_s, gate.check_every_s) == (11.0, 22.0, 3.0)
