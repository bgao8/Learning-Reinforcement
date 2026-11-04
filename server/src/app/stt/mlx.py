"""MlxWhisperTranscriber: the only module that imports mlx_whisper."""
import asyncio
import mlx_whisper
import numpy as np
from app.stt.transcriber import Word


class MlxWhisperTranscriber:
    def __init__(self, model: str = "mlx-community/whisper-large-v3-turbo", language: str = "en"):
        self._model = model
        self._language = language
        # the lock ensures that only one Whisper job happnes at a time
        self._lock = asyncio.Lock()

    async def transcribe(self, samples: np.ndarray) -> str:
        words = await self.transcribe_words(samples)
        return " ".join(word.text for word in words)

    async def transcribe_words(self, samples: np.ndarray) -> list[Word]:
        async with self._lock:
            return await asyncio.to_thread(self._transcribe_words_sync, samples)

    # runs Whisper
    def _transcribe_words_sync(self, samples: np.ndarray) -> list[Word]:
        result = mlx_whisper.transcribe(
            samples.astype(np.float32, copy=False),
            path_or_hf_repo=self._model,
            language=self._language,
            word_timestamps=True
        )
        lst = []
        for seg in result["segments"]:
            for word in seg["words"]:
                text = word["word"].strip()
                if text:
                    lst.append(Word(word["start"], word["end"], text))

        return lst


    # loads model into memory where GPU can use it, set up network's layers
    async def warm_up(self) -> None:
        """Load the model now (seconds) instead of on the first real chunk."""
        await self.transcribe(np.zeros(16_000, dtype=np.float32))