"""Validate model JSON output against a job's schema; raises InvalidOutput."""

import json
from app.llm.errors import InvalidOutput


def _matches(expected, value):
    if expected == "string":
        return isinstance(value, str)

    # bool is a subclass of int in Python, so exclude it explicitly
    elif expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    elif expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)

    elif expected == "boolean":
        return isinstance(value, bool)

    elif expected == "object":
        return isinstance(value, dict)

    elif expected == "array":
        return isinstance(value, list)

    # unknown type: reject rather than let unchecked data through
    return False


def _join(path, name):
    return f"{path}.{name}" if path else name


def _check(schema: dict, value, path: str, text: str) -> None:
    """Check one value against its (sub)schema, then recurse into objects and arrays.

    `path` names where we are, e.g. "questions[0].prompt", so errors point at the bad spot.
    """
    expected = schema.get("type")
    if not _matches(expected, value):
        raise InvalidOutput(f"field {path}: expected {expected}", text)

    allowed = schema.get("enum")
    if allowed is not None and value not in allowed:
        raise InvalidOutput(f"field {path}: {value!r} not one of {allowed}", text)

    if expected == "object":
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                raise InvalidOutput(f"missing field: {_join(path, name)}", text)
        for name, item in value.items():
            if name not in props:
                raise InvalidOutput(f"extra field: {_join(path, name)}", text)
            _check(props[name], item, _join(path, name), text)

    elif expected == "array" and "items" in schema:
        for i, item in enumerate(value):
            _check(schema["items"], item, f"{path}[{i}]", text)


def validate(text: str, schema: dict) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise InvalidOutput("not valid JSON", text)

    if not isinstance(data, dict):
        raise InvalidOutput("expected a JSON object", text)

    _check(schema, data, "", text)
    return data
