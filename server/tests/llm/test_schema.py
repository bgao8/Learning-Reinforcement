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


ENUM_SCHEMA = {
    "type": "object",
    "properties": {"color": {"type": "string", "enum": ["red", "blue"]}},
    "required": ["color"],
}


def test_enum_value_passes():
    assert validate('{"color": "red"}', ENUM_SCHEMA) == {"color": "red"}


def test_value_outside_enum_is_rejected():
    with pytest.raises(InvalidOutput, match="field color: 'green' not one of"):
        validate('{"color": "green"}', ENUM_SCHEMA)


# Nested: an array of objects, like the question-generation output.
NESTED_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["a", "b"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "tags"],
            },
        },
    },
    "required": ["items"],
}


def test_nested_valid_passes():
    text = '{"items": [{"kind": "a", "tags": ["x", "y"]}, {"kind": "b", "tags": []}]}'
    assert validate(text, NESTED_SCHEMA)["items"][1] == {"kind": "b", "tags": []}


def test_empty_array_passes():
    assert validate('{"items": []}', NESTED_SCHEMA) == {"items": []}


def test_non_list_is_not_an_array():
    with pytest.raises(InvalidOutput, match=r"field items: expected array"):
        validate('{"items": {"kind": "a"}}', NESTED_SCHEMA)


def test_array_item_must_be_object():
    with pytest.raises(InvalidOutput, match=r"field items\[0\]: expected object"):
        validate('{"items": ["a"]}', NESTED_SCHEMA)


def test_nested_missing_field_names_its_path():
    with pytest.raises(InvalidOutput, match=r"missing field: items\[1\]\.tags"):
        validate('{"items": [{"kind": "a", "tags": []}, {"kind": "b"}]}', NESTED_SCHEMA)


def test_nested_extra_field_rejected():
    with pytest.raises(InvalidOutput, match=r"extra field: items\[0\]\.color"):
        validate('{"items": [{"kind": "a", "tags": [], "color": "red"}]}', NESTED_SCHEMA)


def test_nested_enum_checked():
    with pytest.raises(InvalidOutput, match=r"field items\[0\]\.kind: 'c' not one of"):
        validate('{"items": [{"kind": "c", "tags": []}]}', NESTED_SCHEMA)


def test_array_of_strings_item_type_checked():
    with pytest.raises(InvalidOutput, match=r"field items\[0\]\.tags\[1\]: expected string"):
        validate('{"items": [{"kind": "a", "tags": ["x", 2]}]}', NESTED_SCHEMA)
