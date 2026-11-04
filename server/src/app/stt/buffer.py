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