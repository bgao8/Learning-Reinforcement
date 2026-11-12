"""CheckpointGate: decides when to ask the topic-shift model or force a quiz.

All times are lecture time in seconds (TranscriptBuffer.last_end). The session
start counts as the last quiz, so nothing happens during the first cooldown.
The timings have no defaults here: LiveSession passes them from config.py
(gate_cooldown_s, gate_force_s, gate_check_every_s), overridable in .env.
"""
from typing import Literal

Decision = Literal["check", "length"] | None


class CheckpointGate:
    def __init__(self, cooldown_s: float, force_s: float, check_every_s: float):
        # no checks or quizzes until this long after the last quiz
        self.cooldown_s = cooldown_s
        # force a "length" quiz once this long has passed without one
        self.force_s = force_s
        # ask the topic-shift model at most this often
        self.check_every_s = check_every_s
        self._last_quiz = 0.0
        self._last_check: float | None = None

    @property
    def last_quiz(self) -> float:
        return self._last_quiz

    def mark_quiz(self, now: float) -> None:
        """Caller reports that a quiz was created at `now`."""
        self._last_quiz = now

    def decide(self, now: float) -> Decision:
        since_quiz = now - self._last_quiz
        if since_quiz < self.cooldown_s:
            return None

        if since_quiz >= self.force_s:
            return "length"

        if self._last_check is not None and now - self._last_check < self.check_every_s:
            return None

        self._last_check = now
        return "check"
