from typing import Protocol

import numpy as np


SAMPLE_RATE = 16_000

class Transcriber(Protocol):
    """Anything with this method counts as a transcriber."""

    async def transcribe(self, samples: np.ndarray) -> str:
        """Return the spoken text in `samples` ("" if nothing was said)."""
        ...