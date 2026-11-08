"""Topic-shift detection: did the lecture move to a new topic?

The model only classifies how RECENT relates to PREVIOUS; code decides which
relations count as a shift. That keeps the model from applying its own idea of
"shift" (see evals/topic_shift.jsonl and scripts/eval_topic_shift.py).
"""
from dataclasses import dataclass
from pathlib import Path

from app.llm import Message, ModelClient

PROMPT = (Path(__file__).parent / "prompts" / "topic_shift_v3.txt").read_text()

SHIFT_RELATIONS = frozenset({"new_concept", "different_subject"})
SAME_TOPIC_RELATIONS = frozenset({"more_detail", "example", "tangent", "recap", "housekeeping"})
RELATIONS = sorted(SHIFT_RELATIONS | SAME_TOPIC_RELATIONS)

SHIFT_SCHEMA = {
    "type": "object",
    "properties": {
        "previous_topic": {"type": "string"},
        "recent_topic": {"type": "string"},
        "reason": {"type": "string"},
        "relation": {"type": "string", "enum": RELATIONS},
    },
    "required": ["previous_topic", "recent_topic", "reason", "relation"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ShiftResult:
    shift: bool
    relation: str
    reason: str
    previous_topic: str
    recent_topic: str


async def detect_shift(client: ModelClient, previous: str, recent: str) -> ShiftResult:
    text = f"PREVIOUS\n{previous}\n\nRECENT\n{recent}"
    response = await client.generate(system=PROMPT, messages=[Message(role="user", content=text)], schema=SHIFT_SCHEMA)

    out = response.output
    return ShiftResult(
        shift=out["relation"] in SHIFT_RELATIONS,
        relation=out["relation"],
        reason=out["reason"],
        previous_topic=out["previous_topic"],
        recent_topic=out["recent_topic"],
    )
