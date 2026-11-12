import pytest

from app.llm.client import ModelClient
from app.llm.errors import InvalidOutput, ModelUnavailable
from app.llm.providers.fake import FakeProvider
from app.topic_shift import SHIFT_SCHEMA, ShiftResult, detect_shift

pytestmark = pytest.mark.anyio


def make(script):
    fake = FakeProvider(script)
    return fake, ModelClient(provider=fake, model="fake-model")


async def test_returns_parsed_result():
    _, client = make(['{"previous_topic": "cell energy", "recent_topic": "supply and demand", "reason": "moved to economics", "relation": "different_subject"}'])
    result = await detect_shift(client, "cells make ATP", "supply and demand")
    assert result == ShiftResult(
        shift=True,
        relation="different_subject",
        reason="moved to economics",
        previous_topic="cell energy",
        recent_topic="supply and demand",
    )


async def test_sends_both_passages_labeled_with_schema():
    fake, client = make(['{"previous_topic": "a", "recent_topic": "a", "reason": "same", "relation": "more_detail"}'])
    await detect_shift(client, "cells make ATP", "supply and demand")
    request = fake.requests[0]
    content = request.messages[0].content
    assert "PREVIOUS" in content and "cells make ATP" in content
    assert "RECENT" in content and "supply and demand" in content
    assert content.index("cells make ATP") < content.index("supply and demand")
    assert request.schema == SHIFT_SCHEMA
    assert "relation" in request.system


@pytest.mark.parametrize(
    ("relation", "shift"),
    [
        ("new_concept", True),
        ("different_subject", True),
        ("more_detail", False),
        ("example", False),
        ("tangent", False),
        ("recap", False),
        ("housekeeping", False),
    ],
)
async def test_code_maps_relation_to_shift(relation, shift):
    _, client = make([f'{{"previous_topic": "a", "recent_topic": "b", "reason": "r", "relation": "{relation}"}}'])
    result = await detect_shift(client, "a", "b")
    assert result.relation == relation
    assert result.shift is shift


async def test_unknown_relation_is_rejected():
    bad = '{"previous_topic": "a", "recent_topic": "b", "reason": "r", "relation": "vibes"}'
    _, client = make([bad, bad])
    with pytest.raises(InvalidOutput):
        await detect_shift(client, "a", "b")


async def test_model_down_propagates():
    _, client = make([ModelUnavailable("ollama not running")])
    with pytest.raises(ModelUnavailable):
        await detect_shift(client, "a", "b")


async def test_invalid_output_twice_propagates():
    _, client = make(['{"shift": "yes"}', "not json"])
    with pytest.raises(InvalidOutput):
        await detect_shift(client, "a", "b")


# --- run_checkpoint: gate + buffer + model, no database ---

from app.checkpoint import CheckpointGate
from app.stt.live import LiveSession
from app.stt.transcriber import Word
from app.topic_shift import QuizTrigger, run_checkpoint

SHIFT = '{"previous_topic": "a", "recent_topic": "b", "reason": "r", "relation": "new_concept"}'
SAME = '{"previous_topic": "a", "recent_topic": "a", "reason": "r", "relation": "more_detail"}'


def live_until(seconds: int, start: int = 1) -> LiveSession:
    """A LiveSession whose buffer has one word ending every second from start..seconds."""
    live = LiveSession(transcriber=None)  # transcriber unused: we fill the buffer directly
    live.gate = CheckpointGate(cooldown_s=180, force_s=600, check_every_s=30)  # the times below assume these
    grow(live, start, seconds)
    return live


def grow(live: LiveSession, start: int, end: int) -> None:
    """Add one word per second for start..end (lecture time moves forward)."""
    live.buffer.add([Word(t - 0.5, float(t), f"w{t}") for t in range(start, end + 1)])


def shift_to(topic: str) -> str:
    return f'{{"previous_topic": "old", "recent_topic": "{topic}", "reason": "r", "relation": "new_concept"}}'


async def test_checkpoint_does_nothing_during_cooldown():
    fake, client = make([])
    assert await run_checkpoint(live_until(100), client) is None
    assert fake.requests == []


async def test_checkpoint_forces_length_quiz_without_model():
    fake, client = make([])
    live = live_until(600)
    trigger = await run_checkpoint(live, client)
    assert trigger.reason == "length"
    assert fake.requests == []
    assert live.gate.decide(650) is None  # cooldown restarted


async def test_length_span_runs_from_last_quiz_to_now():
    _, client = make([])
    live = live_until(600)
    live.topic_so_far = "civic"
    trigger = await run_checkpoint(live, client)
    assert trigger == QuizTrigger("length", span_start=0.0, span_end=600.0, topic="civic")


async def test_one_shift_answer_waits_for_confirmation():
    fake, client = make([SHIFT])
    live = live_until(200)
    assert await run_checkpoint(live, client) is None
    assert live.pending_shift is True
    content = fake.requests[0].messages[0].content
    assert "w81" in content and "w200" in content  # PREVIOUS starts at 81, RECENT ends at 200


async def test_two_shift_answers_in_a_row_trigger_quiz_and_cooldown():
    _, client = make([SHIFT, shift_to("quicksort")])
    live = live_until(200)
    assert await run_checkpoint(live, client) is None
    grow(live, 201, 230)
    trigger = await run_checkpoint(live, client)
    assert trigger.reason == "topic_shift"
    assert live.pending_shift is False
    assert live.topic_so_far == "quicksort"
    assert live.gate.decide(300) is None  # cooldown


async def test_shift_span_ends_where_first_shift_answer_saw_new_topic():
    _, client = make([SHIFT, shift_to("quicksort")])
    live = live_until(200)
    await run_checkpoint(live, client)  # first shift answer at 200: RECENT started at 140
    grow(live, 201, 230)
    trigger = await run_checkpoint(live, client)  # confirmed at 230
    assert trigger.span_start == 0.0
    assert trigger.span_end == 140.0  # not 170: that would include 30 s of the new topic


async def test_shift_quiz_is_about_the_old_topic():
    _, client = make([SHIFT, shift_to("quicksort")])
    live = live_until(200)
    live.topic_so_far = "civic"
    await run_checkpoint(live, client)
    grow(live, 201, 230)
    trigger = await run_checkpoint(live, client)
    assert trigger.topic == "civic"
    assert live.topic_so_far == "quicksort"


async def test_span_starts_at_previous_quiz():
    _, client = make([])
    live = live_until(600)
    await run_checkpoint(live, client)  # length quiz at 600
    grow(live, 601, 1200)
    trigger = await run_checkpoint(live, client)  # next length quiz at 1200
    assert (trigger.span_start, trigger.span_end) == (600.0, 1200.0)


async def test_shift_then_same_topic_is_a_passing_mention():
    _, client = make([SHIFT, SAME])
    live = live_until(200)
    assert await run_checkpoint(live, client) is None
    grow(live, 201, 230)
    assert await run_checkpoint(live, client) is None
    assert live.pending_shift is False


async def test_first_check_sets_anchor_from_previous_topic():
    _, client = make([SAME])
    live = live_until(200)
    await run_checkpoint(live, client)
    assert live.topic_so_far == "a"


async def test_anchor_is_sent_to_model_and_kept_without_shift():
    fake, client = make([SAME])
    live = live_until(200)
    live.topic_so_far = "2024 civic review"
    await run_checkpoint(live, client)
    assert fake.requests[0].messages[0].content.startswith("TOPIC SO FAR\n2024 civic review")
    assert live.topic_so_far == "2024 civic review"


async def test_no_anchor_line_on_first_check():
    fake, client = make([SAME])
    await run_checkpoint(live_until(200), client)
    assert "TOPIC SO FAR" not in fake.requests[0].messages[0].content


async def test_length_quiz_clears_pending_shift():
    _, client = make([SHIFT])
    live = live_until(570)
    assert await run_checkpoint(live, client) is None
    assert live.pending_shift is True
    grow(live, 571, 600)
    trigger = await run_checkpoint(live, client)
    assert trigger.reason == "length"
    assert live.pending_shift is False


async def test_checkpoint_same_topic_is_no_quiz():
    _, client = make([SAME])
    assert await run_checkpoint(live_until(200), client) is None


async def test_checkpoint_skips_when_model_is_down():
    _, client = make([ModelUnavailable("ollama not running")])
    assert await run_checkpoint(live_until(200), client) is None


async def test_checkpoint_skips_silent_previous_minute():
    fake, client = make([])
    live = live_until(200, start=150)  # only the last ~50 s have words
    assert await run_checkpoint(live, client) is None
    assert fake.requests == []
