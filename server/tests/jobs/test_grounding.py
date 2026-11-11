"""Spec for keep_grounded(questions, span_text) -> list[GeneratedQuestion].

Not written yet: this file fails on import until it exists in app.jobs.questions.

Drops any question the transcript can't back up:
- evidence must appear in the span text. Compare after normalizing both sides:
  lowercase, punctuation removed, runs of whitespace collapsed to one space.
  (Whisper output is mostly lowercase with no punctuation; the model tends to add both.)
- empty or whitespace-only evidence is dropped
- multiple_choice needs at least 2 options and answer_key must be one of them
- short_answer must have no options
Order of the kept questions is preserved.
"""
from app.jobs.questions import GeneratedQuestion, keep_grounded

SPAN_TEXT = "so glycolysis  splits glucose into two pyruvate and it happens in the cytoplasm"


def gq(evidence="glycolysis splits glucose", question_type="short_answer", options=None, answer_key="glucose", prompt="p"):
    return GeneratedQuestion(
        prompt=prompt,
        question_type=question_type,
        options=options if options is not None else [],
        answer_key=answer_key,
        evidence=evidence,
    )


def test_exact_quote_is_kept():
    question = gq(evidence="splits glucose into two pyruvate")
    assert keep_grounded([question], SPAN_TEXT) == [question]


def test_case_punctuation_and_spacing_are_ignored():
    question = gq(evidence="Glycolysis splits glucose, into two   pyruvate.")
    assert keep_grounded([question], SPAN_TEXT) == [question]


def test_invented_evidence_is_dropped():
    assert keep_grounded([gq(evidence="glycolysis makes 36 ATP")], SPAN_TEXT) == []


def test_paraphrased_evidence_is_dropped():
    assert keep_grounded([gq(evidence="glucose is split by glycolysis")], SPAN_TEXT) == []


def test_empty_evidence_is_dropped():
    assert keep_grounded([gq(evidence=""), gq(evidence="   ")], SPAN_TEXT) == []


def test_multiple_choice_with_answer_in_options_is_kept():
    question = gq(question_type="multiple_choice", options=["glucose", "pyruvate", "ATP"], answer_key="glucose")
    assert keep_grounded([question], SPAN_TEXT) == [question]


def test_multiple_choice_answer_not_in_options_is_dropped():
    question = gq(question_type="multiple_choice", options=["pyruvate", "ATP"], answer_key="glucose")
    assert keep_grounded([question], SPAN_TEXT) == []


def test_multiple_choice_needs_two_options():
    question = gq(question_type="multiple_choice", options=["glucose"], answer_key="glucose")
    assert keep_grounded([question], SPAN_TEXT) == []


def test_short_answer_with_options_is_dropped():
    question = gq(question_type="short_answer", options=["glucose", "ATP"])
    assert keep_grounded([question], SPAN_TEXT) == []


def test_keeps_good_drops_bad_in_order():
    first = gq(prompt="first", evidence="happens in the cytoplasm")
    bad = gq(prompt="bad", evidence="made up")
    last = gq(prompt="last")
    assert keep_grounded([first, bad, last], SPAN_TEXT) == [first, last]


def test_empty_input_returns_empty():
    assert keep_grounded([], SPAN_TEXT) == []
