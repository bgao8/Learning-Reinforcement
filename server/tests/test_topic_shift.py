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
    _, client = make(['{"reason": "moved to economics", "shift": true, "confidence": 0.9}'])
    result = await detect_shift(client, "cells make ATP", "supply and demand")
    assert result == ShiftResult(shift=True, confidence=0.9, reason="moved to economics")


async def test_sends_both_passages_labeled_with_schema():
    fake, client = make(['{"reason": "same", "shift": false, "confidence": 0.1}'])
    await detect_shift(client, "cells make ATP", "supply and demand")
    request = fake.requests[0]
    content = request.messages[0].content
    assert "PREVIOUS" in content and "cells make ATP" in content
    assert "RECENT" in content and "supply and demand" in content
    assert content.index("cells make ATP") < content.index("supply and demand")
    assert request.schema == SHIFT_SCHEMA
    assert "new topic" in request.system


async def test_model_down_propagates():
    _, client = make([ModelUnavailable("ollama not running")])
    with pytest.raises(ModelUnavailable):
        await detect_shift(client, "a", "b")


async def test_invalid_output_twice_propagates():
    _, client = make(['{"shift": "yes"}', "not json"])
    with pytest.raises(InvalidOutput):
        await detect_shift(client, "a", "b")
