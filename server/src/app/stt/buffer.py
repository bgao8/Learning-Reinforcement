from collections import deque

from app.stt.transcriber import Word


class TranscriptBuffer:
    def __init__(self, keep_s: float = 600.0):
        self._keep = keep_s
        self._words: deque[Word] = deque()

    def add(self, words: list[Word]) -> None:
        self._words.extend(words)

        if not self._words:
            return

        cutoff = self._words[-1].end - self._keep

        while self._words[0].end < cutoff:
            self._words.popleft()

    def last(self, seconds: float) -> str:
        if not self._words: 
            return ""

        cutoff = self._words[-1].end - seconds

        return " ".join(word.text for word in self._words if word.end > cutoff)

    @property
    def last_end(self) -> float:
        """End time of the last word, or 0.0 if empty."""
        return self._words[-1].end if self._words else 0.0

    def between(self, start: float, end: float) -> str:
        """Text of words whose end time is in (start, end]."""
        return " ".join(w.text for w in self._words if start < w.end <= end)