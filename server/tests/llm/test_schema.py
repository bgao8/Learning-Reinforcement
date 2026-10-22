"""Tests for llm.schema: no network needed."""
import pytest

from app.llm.errors import InvalidOutput
from app.llm.schema import validate

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "feedback": {"type": "string"},
        "ok": {"type": "boolean"},
        "n": {"type": "integer"},
    },
    "required": ["score", "feedback"],
}


def test_valid_passes():
    # check if the input param is equal to the desired output
    assert validate('{"score": 0.8, "feedback": "Nice"}', SCHEMA) == {"score": 0.8, "feedback": "Nice"}


def test_optional_fields_pass():
    assert validate('{"score": 1, "feedback": "x", "ok": true, "n": 3}', SCHEMA) == {"score": 1, "feedback": "x", "ok": True, "n": 3}


def test_invalid_json_raises():
    with pytest.raises(InvalidOutput, match="not valid JSON"):
        validate('{"score": True, "feedback": x}', SCHEMA)


def test_non_object_raises():
    with pytest.raises(InvalidOutput, match="expected a JSON object"):
        validate('[1, 2]', SCHEMA)


def test_missing_required_field_raises():
    with pytest.raises(InvalidOutput, match="missing field: feedback"):
        validate('{"score": 0.8}', SCHEMA)


def test_extra_field_raises():
    with pytest.raises(InvalidOutput, match="extra field: grade"):
        validate('{"score": 0.8, "feedback": "x", "grade": 1}', SCHEMA)


def test_bool_is_not_a_number():
    # test should raise an InvalidOutput
    with pytest.raises(InvalidOutput, match="field score: expected number"):
        validate('{"score": true, "feedback": "x"}', SCHEMA)


def test_string_is_not_a_number():
    with pytest.raises(InvalidOutput, match="field score: expected number"):
        validate('{"score": "0.8", "feedback": "x"}', SCHEMA)


def test_bool_is_not_an_integer():
    with pytest.raises(InvalidOutput, match="field n: expected integer"):
        validate('{"score": 0.8, "feedback": "x", "n": true}', SCHEMA)


def test_float_is_not_an_integer():
    with pytest.raises(InvalidOutput, match="field n: expected integer"):
        validate('{"score": 0.8, "feedback": "x", "n": 2.5}', SCHEMA)


def test_int_is_not_a_boolean():
    with pytest.raises(InvalidOutput, match="field ok: expected boolean"):
        validate('{"score": 0.8, "feedback": "x", "ok": 1}', SCHEMA)
