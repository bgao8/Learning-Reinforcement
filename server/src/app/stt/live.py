"""LiveSession: runs one recording's audio through the transcription pipeline."""
import numpy as np
from dataclasses import dataclass

from app.stt.buffer import TranscriptBuffer
from app.stt.names import NameGlossary, whisper_prompt
from app.stt.silence import is_silent
from app.stt.transcriber import Transcriber
from app.stt.windower import AudioWindower, Window, owned_words
from app.checkpoint import CheckpointGate
from app.config import settings


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
    def __init__(self, transcriber: Transcriber, title: str | None = None):
        self._transcriber = transcriber
        self.title = title            # the video title; PATCH /sessions/{id} updates it mid-session
        self.names = NameGlossary()   # names Whisper has written so far, for the Whisper prompt
        self._windower = AudioWindower()
        self.buffer = TranscriptBuffer()
        self.next_seq = 0
        self._window_seq = 0
        self.gate = CheckpointGate(
            cooldown_s=settings.gate_cooldown_s,
            force_s=settings.gate_force_s,
            check_every_s=settings.gate_check_every_s,
        )
        self.checking = False  # a checkpoint task is running
        self.topic_so_far: str | None = None
        self.pending_shift = False
        self.pending_end: float | None = None

    async def add_chunk(self, seq: int, samples: np.ndarray) -> list[TranscriptPiece]:
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
    

    async def _process(self, window: Window) -> TranscriptPiece | None:
        seq = self._window_seq
        self._window_seq += 1
        
        if is_silent(window.samples):
            return None

        prompt = self.whisper_prompt(window)
        words = await self._transcriber.transcribe_words(window.samples, prompt=prompt)
        kept = owned_words(window, words)
        self.buffer.add(kept)
        self.names.add([w.text for w in kept])

        if not kept:
            return None

        text = " ".join(w.text for w in kept)
        return TranscriptPiece(seq, window.own_start, window.own_end, text)

    def whisper_prompt(self, window: Window) -> str | None:
        """Title, names so far and the text right before the window's audio starts (not the
        margin it shares with the previous window, or Whisper would expect those words twice).
        None without that text: Whisper can repeat a bare title instead of hearing the speech."""
        recent = self.buffer.between(window.t0 - 30, window.t0)
        if not recent.strip():
            return None
        return whisper_prompt(self.title, self.names.terms(), recent)
