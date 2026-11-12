"""Spec for CheckpointGate: decides when to ask the topic-shift model or force a quiz.

All times are lecture time in seconds (TranscriptBuffer.last_end).
These tests use fixed timings (cooldown 180 s, force 600 s, check every 30 s) so they
test the gate's rules, not the product's tuning in config.py. The session start counts
as the last quiz (time 0).
"""
from app.checkpoint import CheckpointGate


def make_gate() -> CheckpointGate:
    return CheckpointGate(cooldown_s=180, force_s=600, check_every_s=30)


def test_nothing_during_initial_cooldown():
    gate = make_gate()
    assert gate.decide(10) is None
    assert gate.decide(179) is None


def test_first_check_when_cooldown_ends():
    assert make_gate().decide(180) == "check"


def test_checks_are_at_least_30s_apart():
    gate = make_gate()
    assert gate.decide(180) == "check"
    assert gate.decide(200) is None
    assert gate.decide(209) is None
    assert gate.decide(210) == "check"


def test_quiz_restarts_cooldown():
    gate = make_gate()
    assert gate.decide(180) == "check"
    gate.mark_quiz(185)
    assert gate.decide(300) is None
    assert gate.decide(364) is None
    assert gate.decide(365) == "check"


def test_length_quiz_forced_after_600s_without_a_quiz():
    gate = make_gate()
    assert gate.decide(570) == "check"
    assert gate.decide(600) == "length"


def test_length_wins_over_a_due_check():
    gate = make_gate()
    assert gate.decide(650) == "length"


def test_length_resets_after_mark_quiz():
    gate = make_gate()
    assert gate.decide(600) == "length"
    gate.mark_quiz(600)
    assert gate.decide(700) is None
    assert gate.decide(780) == "check"
    assert gate.decide(1200) == "length"


def test_length_repeats_until_caller_marks_quiz():
    gate = make_gate()
    assert gate.decide(600) == "length"
    assert gate.decide(605) == "length"


def test_custom_timings():
    gate = CheckpointGate(cooldown_s=10, force_s=100, check_every_s=5)
    assert gate.decide(9) is None
    assert gate.decide(10) == "check"
    assert gate.decide(14) is None
    assert gate.decide(15) == "check"
    assert gate.decide(100) == "length"
