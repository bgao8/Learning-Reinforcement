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

def test_bool_is_not_a_number():
    # test should raise an InvalidOutput
    with pytest.raises(InvalidOutput):
        validate('{"score": true, "feedback": "x"}', SCHEMA)