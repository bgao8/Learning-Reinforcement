"""LiveSession: runs one recording's audio through the transcription pipeline."""
import numpy as np
from dataclasses import dataclass

from app.stt.buffer import TranscriptBuffer
from app.stt.silence import is_silent
from app.stt.transcriber import Transcriber
from app.stt.windower import AudioWindower, Window, owned_words


class OutOfOrderChunk(Exception):
    """A chunk arrived with a different sequence than what was expected."""

# Windows with transcript pieces, aka windows with transcribed words
@dataclass(frozen=True)
class TranscriptPiece:
    seq: int
    start: float
    end: float
    text: str


class LiveSession:
    def __init__(self, transcriber: Transcriber):
        self._transcriber = transcriber
        self._windower = AudioWindower()
        self.buffer = TranscriptBuffer()
        self.next_seq = 0
        self._window_seq = 0

    async def add_chunk(self, seq: int, samples: np.ndarray) -> None:
        if seq != self.next_seq:
            raise OutOfOrderChunk("Sequence out of order.")

        self.next_seq += 1

        pieces = []
        for window in self._windower.feed(samples):
            piece = await self._process(window)
            if piece is not None:
                pieces.append(piece)

        return pieces

    async def finish(self) -> list[TranscriptPiece]:
        window = self._windower.flush()
        if window is None:
            return []
        
        piece = await self._process(window)
        if piece is not None:
            return [piece]
        return []
    

    async def _process(self, window: Window):
        seq = self._window_seq
        self._window_seq += 1
        
        if is_silent(window.samples):
            return None

        words = await self._transcriber.transcribe_words(window.samples)
        kept = owned_words(window, words)
        self.buffer.add(kept)

        if not kept:
            return None

        text = " ".join(w.text for w in kept)
        return TranscriptPiece(seq, window.own_start, window.own_end, text)