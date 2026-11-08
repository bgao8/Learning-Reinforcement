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
