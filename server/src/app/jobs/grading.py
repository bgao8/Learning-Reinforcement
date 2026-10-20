"""Grading job (#22): GradeResult, its schema, and grade(...)."""

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "feedback": {"type": "string"},
    },
    "required": ["score", "feedback"],
}
