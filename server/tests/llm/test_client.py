"""Tests for ModelClient retry/timeout/errors using FakeProvider."""
import pytest
from app.llm.errors import ModelUnavailable, ModelTimeout
from app.llm.providers.fake import FakeProvider


# AnyIO async pytest plugin
@pytest.mark.anyio
async def test_fake_raises_scripted_error():
    fake = FakeProvider(ModelUnavailable("down"))
    with pytest.raises(ModelUnavailable):
        await fake.complete(None)

async def test_unavailable_is_not_retried():
    fake = FakeProvider([ModelUnavailable("down")])
    client = ModelClient(provider=fake)
    result = await client.generate(...)
    assert result.attempts == 1

async def test_timeout_is_retried_once():
    fake = FakeProvider([ModelTimeout("slow"), '{"score": 1, "feedback": "ok"}'])
    client = ModelClient(provider=fake)
    result = await client.generate(...)
    assert result.attempts == 2

