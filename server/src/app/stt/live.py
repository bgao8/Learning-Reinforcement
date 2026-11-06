"""LiveSession: runs one recording's audio through the transcription pipeline."""
import numpy as np

from app.stt.buffer import TranscriptBuffer
from app.stt.silence import is_silent
from app.stt.transcriber import Transcriber
from app.stt.windower import AudioWindower, Window, owned_words


class OutOfOrderChunk(Exception):
    """A chunk arrived with a different sequence than what was expected."""


class LiveSession:
    def __init__(self, transcriber: Transcriber):
        self._transcriber = transcriber
        self._windower = AudioWindower()
        self.buffer = TranscriptBuffer()
        self.next_seq = 0

    async def add_chunk(self, seq: int, samples: np.ndarray) -> None:
        if seq != self.next_seq:
            raise OutOfOrderChunk("Sequence out of order.")

        self.next_seq += 1

        for window in self._windower.feed(samples):
            await self._process(window)

    async def finish(self) -> None:
        window = self._windower.flush()

        if window is not None:
            await self._process(window)

    async def _process(self, window: Window):
        if is_silent(window.samples):
            return

        words = await self._transcriber.transcribe_words(window.samples)
        self.buffer.add(owned_words(window, words))