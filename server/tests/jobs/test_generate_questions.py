"""generate_questions against FakeProvider: no network, no DB."""
import json

import pytest

from app.jobs.questions import PROMPT, QUESTIONS_SCHEMA, GeneratedQuestion, Span, generate_questions
from app.llm.client import ModelClient
from app.llm.errors import InvalidOutput
from app.llm.providers.fake import FakeProvider

pytestmark = pytest.mark.anyio

SPAN = Span(text="so glycolysis splits glucose", start_chunk=0, end_chunk=0, start_ts=0.0, end_ts=5.0)


def make(script):
    fake = FakeProvider(script)
    return fake, ModelClient(provider=fake, model="fake-model")


def q(prompt="What does glycolysis split?", **overrides):
    item = {
        "evidence": "glycolysis splits glucose",
        "prompt": prompt,
        "question_type": "short_answer",
        "options": [],
        "answer_key": "glucose",
    }
    item.update(overrides)
    return item


def answer(*items):
    return json.dumps({"questions": list(items)})


async def test_returns_generated_questions():
    _, client = make([answer(q())])
    result = await generate_questions(client, SPAN, "glycolysis")
    assert result == [
        GeneratedQuestion(
            prompt="What does glycolysis split?",
            question_type="short_answer",
            options=[],
            answer_key="glucose",
            evidence="glycolysis splits glucose",
        )
    ]


async def test_multiple_choice_keeps_options():
    mc = q(question_type="multiple_choice", options=["glucose", "pyruvate", "ATP"], answer_key="glucose")
    _, client = make([answer(mc)])
    [result] = await generate_questions(client, SPAN, "glycolysis")
    assert result.question_type == "multiple_choice"
    assert result.options == ["glucose", "pyruvate", "ATP"]


async def test_sends_topic_and_transcript_with_prompt_and_schema():
    fake, client = make([answer(q())])
    await generate_questions(client, SPAN, "glycolysis")
    request = fake.requests[0]
    content = request.messages[0].content
    assert "TOPIC\nglycolysis" in content
    assert "TRANSCRIPT\nso glycolysis splits glucose" in content
    assert content.index("TOPIC") < content.index("TRANSCRIPT")
    assert request.system == PROMPT
    assert request.schema == QUESTIONS_SCHEMA


async def test_no_topic_line_when_topic_is_none():
    fake, client = make([answer(q())])
    await generate_questions(client, SPAN, None)
    content = fake.requests[0].messages[0].content
    assert "TOPIC" not in content
    assert "None" not in content
    assert content.startswith("TRANSCRIPT\n")


async def test_keeps_at_most_three():
    _, client = make([answer(q("one"), q("two"), q("three"), q("four"), q("five"))])
    result = await generate_questions(client, SPAN, "glycolysis")
    assert [x.prompt for x in result] == ["one", "two", "three"]


async def test_empty_list_returns_empty():
    _, client = make([answer()])
    assert await generate_questions(client, SPAN, "glycolysis") == []


async def test_bad_item_is_retried_then_succeeds():
    bad = q()
    del bad["answer_key"]
    fake, client = make([answer(bad), answer(q())])
    result = await generate_questions(client, SPAN, "glycolysis")
    assert len(result) == 1
    assert len(fake.requests) == 2


async def test_bad_output_twice_raises():
    _, client = make([answer(q(question_type="essay")), '{"questions": "nope"}'])
    with pytest.raises(InvalidOutput):
        await generate_questions(client, SPAN, "glycolysis")
