import asyncio
import wave
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("mlx_whisper")
from app.stt.mlx import MlxWhisperTranscriber

pytestmark = [pytest.mark.anyio, pytest.mark.slow]
CLIP = Path(__file__).parent / "fixtures" / "lecture_10s.wav"


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768   # int16 → [-1, 1]


@pytest.fixture(scope="module")
def transcriber():
    return MlxWhisperTranscriber()          # one instance = model loads once for all tests


async def test_transcribes_known_clip(transcriber):
    text = await transcriber.transcribe(load_wav(CLIP))
    assert "cellular respiration" in text.lower()


async def test_concurrent_calls_return_in_order(transcriber):
    audio = load_wav(CLIP)
    halves = [audio[: len(audio) // 2], audio[len(audio) // 2 :]]
    results = await asyncio.gather(*(transcriber.transcribe(h) for h in halves))
    assert "today" in results[0].lower()    # first half's result came back first