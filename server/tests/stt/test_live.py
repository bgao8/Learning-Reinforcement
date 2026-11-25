import numpy as np
import pytest

from app.config import settings
from app.stt.live import LiveSession, OutOfOrderChunk
from app.stt.transcriber import SAMPLE_RATE, Word

pytestmark = pytest.mark.anyio


class FakeTranscriber:
    """Says one word in the middle of each window's owned stretch, and records its calls."""

    def __init__(self, words=None):
        self.calls = []
        self.prompts = []
        self.words = words   # text for each window, in order; default "word1", "word2", ...

    async def transcribe(self, samples):
        return ""

    async def transcribe_words(self, samples, prompt=None):
        self.calls.append(len(samples) / SAMPLE_RATE)
        self.prompts.append(prompt)
        n = len(self.calls)
        # the first window has no left margin, so its owned stretch starts at 0, not 1
        mid = 2.5 if n == 1 else 3.5
        if self.words is None:
            return [Word(mid - 0.1, mid + 0.1, f"word{n}")]
        texts = self.words[n - 1].split()
        step = 0.2 / len(texts)
        return [Word(mid - 0.1 + i * step, mid - 0.1 + (i + 1) * step, t) for i, t in enumerate(texts)]


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


# --- Whisper prompt: title, names so far, text before the window ---

async def test_first_window_has_no_prompt_without_a_title():
    fake = FakeTranscriber()
    await LiveSession(fake).add_chunk(0, loud(6))
    assert fake.prompts == [None]


async def test_prompt_carries_title_names_and_earlier_text():
    fake = FakeTranscriber(words=["then the GR Corolla", "went faster", "on the track"])
    live = LiveSession(fake, title="Toyota aero")
    for seq in range(3):
        await live.add_chunk(seq, loud(5))   # 15 s: windows at 0–5 and 5–10 are done
    assert fake.prompts[0] is None   # no text before it yet, so the title isn't sent alone
    assert fake.prompts[1] == "Toyota aero. GR Corolla. then the GR Corolla"


async def test_title_change_reaches_the_next_window():
    fake = FakeTranscriber()
    live = LiveSession(fake)
    await live.add_chunk(0, loud(6))
    live.title = "Flywheel KERS"
    await live.add_chunk(1, loud(5))
    assert fake.prompts[1].startswith("Flywheel KERS.")


async def test_names_are_not_sent_without_recent_text():
    # sound at 0–6 s and 45–51 s: after the silence the names are still known, but no text
    # falls in the 30 s before the window
    fake = FakeTranscriber(words=["then the GR Corolla", "went faster", "on the track", "again"])
    live = LiveSession(fake, title="Toyota aero")
    await live.add_chunk(0, loud(6))
    await live.add_chunk(1, quiet(39))
    await live.add_chunk(2, loud(6))
    assert live.names.terms() == ["GR Corolla"]
    assert "GR Corolla" in fake.prompts[1]
    assert fake.prompts[2] is None   # the first window after the silence
