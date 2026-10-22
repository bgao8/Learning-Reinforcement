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

    # unknown type: reject rather than let unchecked data through
    return False


def validate(text: str, schema: dict) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise InvalidOutput("not valid JSON", text)

    if not isinstance(data, dict):
        raise InvalidOutput("expected a JSON object", text)

    for name in schema.get("required", []):
        if name not in data:
            raise InvalidOutput(f"missing field: {name}", text)

    for name in data:
        if name not in schema.get("properties", {}):
            raise InvalidOutput(f"extra field: {name}", text)

    for prop, value in data.items():
        expected = schema["properties"][prop]["type"]
        if not _matches(expected, value):
            raise InvalidOutput(f"field {prop}: expected {expected}", text)

    return data
