from typing import Protocol
from dataclasses import dataclass
import mlx_whisper
import numpy as np


SAMPLE_RATE = 16_000

@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


class Transcriber(Protocol):
    """Anything with this method counts as a transcriber."""

    async def transcribe(self, samples: np.ndarray) -> str:
        """Return the spoken text in `samples` ("" if nothing was said)."""
        ...

    async def transcribe_words(self, samples: np.ndarray) -> list[Word]:
        ...

    def _transcribe_words_sync(self, samples: np.ndarray) -> list[Word]:
        result = mlx_whisper.transcribe(
            ...,
            word_timestamps=True
        )