"""generate_questions against FakeProvider: no network, no DB."""
import json

import pytest

from app.jobs.questions import PROMPT, QUESTIONS_SCHEMA, GeneratedQuestion, GeneratedQuiz, Span, build_message, generate_questions
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
        "concept": "glycolysis",
        "prompt": prompt,
        "question_type": "short_answer",
        "options": [],
        "answer_key": "glucose",
    }
    item.update(overrides)
    return item


def answer(*items, course="biology 101", skip_reason=None):
    out = {"course": course, "questions": list(items)}
    if skip_reason:
        out["skip_reason"] = skip_reason
    return json.dumps(out)


async def test_returns_generated_questions():
    _, client = make([answer(q())])
    result = await generate_questions(client, SPAN, "glycolysis")
    assert result.course == "biology 101"
    assert result.questions == [
        GeneratedQuestion(
            prompt="What does glycolysis split?",
            question_type="short_answer",
            options=[],
            answer_key="glucose",
            evidence="glycolysis splits glucose",
            concept="glycolysis",
        )
    ]


async def test_multiple_choice_keeps_options():
    mc = q(question_type="multiple_choice", options=["glucose", "pyruvate", "ATP"], answer_key="glucose")
    _, client = make([answer(mc)])
    [result] = (await generate_questions(client, SPAN, "glycolysis")).questions
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
    result = (await generate_questions(client, SPAN, "glycolysis")).questions
    assert [x.prompt for x in result] == ["one", "two", "three"]


async def test_empty_list_returns_empty():
    _, client = make([answer()])
    assert await generate_questions(client, SPAN, "glycolysis") == GeneratedQuiz(course="biology 101", questions=[])


async def test_bad_item_is_retried_then_succeeds():
    bad = q()
    del bad["answer_key"]
    fake, client = make([answer(bad), answer(q())])
    result = (await generate_questions(client, SPAN, "glycolysis")).questions
    assert len(result) == 1
    assert len(fake.requests) == 2


async def test_bad_output_twice_raises():
    _, client = make([answer(q(question_type="essay")), '{"questions": "nope"}'])
    with pytest.raises(InvalidOutput):
        await generate_questions(client, SPAN, "glycolysis")


async def test_missing_concept_is_retried():
    no_concept = q()
    del no_concept["concept"]
    fake, client = make([answer(no_concept), answer(q())])
    [result] = (await generate_questions(client, SPAN, "glycolysis")).questions
    assert result.concept == "glycolysis"
    assert len(fake.requests) == 2


async def test_sends_known_concepts_between_topic_and_transcript():
    fake, client = make([answer(q())])
    await generate_questions(client, SPAN, "glycolysis", ["glycolysis", "atp production"])
    content = fake.requests[0].messages[0].content
    assert "KNOWN CONCEPTS\n- glycolysis\n- atp production" in content
    assert content.index("TOPIC") < content.index("KNOWN CONCEPTS") < content.index("TRANSCRIPT")


def test_no_known_concepts_section_when_empty():
    assert "KNOWN CONCEPTS" not in build_message(SPAN, "glycolysis", [])
    assert build_message(SPAN, None) == "TRANSCRIPT\nso glycolysis splits glucose"


async def test_sends_lecture_so_far_first():
    fake, client = make([answer(q())])
    await generate_questions(client, SPAN, "glycolysis", ["glycolysis"], ["cell structure", "enzymes"])
    content = fake.requests[0].messages[0].content
    assert content.startswith("LECTURE SO FAR\n- cell structure\n- enzymes\n\nTOPIC")
    assert content.index("TOPIC") < content.index("KNOWN CONCEPTS") < content.index("TRANSCRIPT")


def test_no_lecture_so_far_section_when_empty():
    assert "LECTURE SO FAR" not in build_message(SPAN, "glycolysis", ["glycolysis"], [])


def test_lecture_title_comes_first():
    message = build_message(SPAN, "glycolysis", ["glycolysis"], ["cell structure"], "Bio 101: respiration")
    assert message.startswith("LECTURE TITLE\nBio 101: respiration\n\nLECTURE SO FAR")


def test_no_lecture_title_section_when_missing():
    assert "LECTURE TITLE" not in build_message(SPAN, "glycolysis", title=None)
    assert "LECTURE TITLE" not in build_message(SPAN, "glycolysis", title="")


async def test_missing_course_is_retried():
    no_course = json.dumps({"questions": [q()]})
    fake, client = make([no_course, answer(q(), course="deep learning")])
    result = await generate_questions(client, SPAN, "glycolysis")
    assert result.course == "deep learning"
    assert len(fake.requests) == 2


def test_course_comes_before_questions_in_the_schema():
    # generation follows schema order: the course must be settled before concepts are named
    assert list(QUESTIONS_SCHEMA["properties"]) == ["course", "questions", "skip_reason"]


# --- skip_reason: why the model wrote no questions ---

@pytest.mark.parametrize("reason", ["not_educational", "too_little_content"])
async def test_no_questions_returns_the_models_reason(reason):
    _, client = make([answer(skip_reason=reason, course="career development")])
    result = await generate_questions(client, SPAN, "salaries")
    assert (result.questions, result.skip_reason) == ([], reason)


async def test_no_questions_and_no_reason_is_allowed():
    _, client = make([answer()])
    assert (await generate_questions(client, SPAN, "glycolysis")).skip_reason is None


async def test_reason_next_to_questions_is_ignored():
    # contradicts the prompt; the questions win
    _, client = make([answer(q(), skip_reason="not_educational")])
    result = await generate_questions(client, SPAN, "glycolysis")
    assert (len(result.questions), result.skip_reason) == (1, None)


async def test_unknown_skip_reason_is_retried():
    fake, client = make([answer(skip_reason="boring"), answer(skip_reason="not_educational")])
    result = await generate_questions(client, SPAN, "glycolysis")
    assert result.skip_reason == "not_educational"
    assert len(fake.requests) == 2


def test_prompt_names_every_skip_reason():
    # the model can only use the reasons the prompt explains
    for reason in QUESTIONS_SCHEMA["properties"]["skip_reason"]["enum"]:
        assert f'"{reason}"' in PROMPT
