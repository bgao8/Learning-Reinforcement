"""Tests for ModelClient retry/timeout/errors using FakeProvider."""
import pytest

from app.llm.client import ModelClient                                  # was missing
from app.llm.errors import InvalidOutput, ModelTimeout, ModelUnavailable
from app.llm.providers.fake import FakeProvider
from app.llm.types import Message

pytestmark = pytest.mark.anyio          # applies the async plugin to EVERY test in this file

# any schema works here; these tests are about ModelClient, not grading
GRADE_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "number"}, "feedback": {"type": "string"}},
    "required": ["score", "feedback"],
    "additionalProperties": False,
}
VALID = '{"score": 1, "feedback": "ok"}'
MESSAGES = [Message(role="user", content="What do mitochondria produce?")]


def make_client(script):
    """Fake provider + client, so each test is just the script and the asserts."""
    fake = FakeProvider(script)
    return fake, ModelClient(provider=fake, model="fake-model")         # model= is required


async def test_happy_path():
    fake, client = make_client([VALID])
    result = await client.generate(system="grade it", messages=MESSAGES, schema=GRADE_SCHEMA)
    assert result.output == {"score": 1, "feedback": "ok"}
    assert result.attempts == 1


async def test_unavailable_is_not_retried():
    fake, client = make_client([ModelUnavailable("down")])
    with pytest.raises(ModelUnavailable):                               # it raises, so there's no result
        await client.generate(system="grade it", messages=MESSAGES, schema=GRADE_SCHEMA)
    assert len(fake.requests) == 1                                      # called once, then gave up


async def test_timeout_is_retried_once():
    fake, client = make_client([ModelTimeout("slow"), VALID])
    result = await client.generate(system="grade it", messages=MESSAGES, schema=GRADE_SCHEMA)
    assert result.attempts == 2


async def test_invalid_output_is_retried_once():
    fake, client = make_client(["not json", VALID])
    result = await client.generate(system="grade it", messages=MESSAGES, schema=GRADE_SCHEMA)
    assert result.attempts == 2
    assert fake.requests[0] == fake.requests[1]                         # retry sent the identical request


async def test_gives_up_after_two_failures():
    fake, client = make_client(["not json", "still not json"])
    with pytest.raises(InvalidOutput):
        await client.generate(system="grade it", messages=MESSAGES, schema=GRADE_SCHEMA)
    assert len(fake.requests) == 2                                      # exactly one retry, no more