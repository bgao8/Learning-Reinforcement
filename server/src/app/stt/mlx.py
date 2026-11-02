"""MlxWhisperTranscriber: the only module that imports mlx_whisper."""
import asyncio

import mlx_whisper
import numpy as np


class MlxWhisperTranscriber:
    def __init__(self, model: str = "mlx-community/whisper-large-v3-turbo", language: str = "en"):
        self._model = model
        self._language = language
        self._lock = asyncio.Lock()

    # thread safety so Whisper operation doesn't block server
    async def transcribe(self, samples: np.ndarray) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._transcribe_sync, samples)

    # runs Whisper
    def _transcribe_sync(self, samples: np.ndarray) -> str:
        result = mlx_whisper.transcribe(
            samples.astype(np.float32, copy=False),
            path_or_hf_repo=self.model,
            language=self._language
        )
        return result["text"].strip()

    # loads model into memory where GPU can use it, set up network's layers
    async def warm_up(self) -> None:
        """Load the model now (seconds) instead of on the first real chunk."""
        await self.transcribe(np.zeros(16_000, dtype=np.float32))