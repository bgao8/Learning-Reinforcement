from typing import Protocol
from dataclasses import dataclass
import numpy as np


SAMPLE_RATE = 16_000

@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


class TranscriptionError(Exception):
    """A transcriber couldn't transcribe this audio (network, rate limit, server error)."""


class Transcriber(Protocol):
    """Anything with this method counts as a transcriber."""

    async def transcribe(self, samples: np.ndarray) -> str:
        """Return the spoken text in `samples` ("" if nothing was said)."""
        ...

    async def transcribe_words(self, samples: np.ndarray, prompt: str | None = None) -> list[Word]:
        """Words with times relative to the start of samples. prompt: text that came before
        the audio, which steers spellings (see stt/names.py)."""
        ...