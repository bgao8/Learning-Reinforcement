from dataclasses import dataclass
import numpy as np

from app.stt.transcriber import Word, SAMPLE_RATE


@dataclass(frozen=True)
class Window:
    t0: float
    own_start: float
    own_end: float
    samples: np.ndarray


class AudioWindower:
    def __init__(self, step_s=5.0, margin_s=1.0):
        self._step = step_s
        self._margin = margin_s
        self._buf = np.zeros(0, dtype=np.float32)
        self._buf_start = 0.0
        self._next_own = 0.0

    def _buf_end(self) -> float:
        """Lecture time at the end of the buffer."""
        return self._buf_start + len(self._buf) / SAMPLE_RATE

    def _index(self, t: float) -> int:
        """Lecture time -> position in _buf."""
        return round((t - self._buf_start) * SAMPLE_RATE)

    def feed(self, chunk: np.ndarray) -> list[Window]:
        self._buf = np.concatenate([self._buf, chunk])
        windows = []

        while self._buf_end() >= self._next_own + self._step + self._margin:
            start = max(0, self._next_own - self._margin)
            end = self._next_own + self._step + self._margin

            samples = self._buf[self._index(start): self._index(end)]
            windows.append(Window(start, self._next_own, self._next_own + self._step, samples))

            self._next_own += self._step
            keep = max(self._next_own - self._margin, 0)
            self._buf = self._buf[self._index(keep):]
            self._buf_start = keep

        return windows

    def flush(self) -> Window | None:
        if self._buf_end() <= self._next_own:
            return None

        return Window(self._buf_start, self._next_own, self._buf_end(), self._buf)


def owned_words(window: Window, words: list[Word]):
    kept = []

    for w in words:
        start, end = window.t0 + w.start, window.t0 + w.end
        mid = (start + end) / 2
        if window.own_start <= mid < window.own_end:
            kept.append(Word(start, end, w.text))

    return kept