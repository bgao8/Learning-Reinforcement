"""Topic-shift detection: did the lecture move to a new topic?

The model only classifies how RECENT relates to PREVIOUS; code decides which
relations count as a shift. That keeps the model from applying its own idea of
"shift" (see evals/topic_shift.jsonl and scripts/eval_topic_shift.py).
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from app.llm import Message, ModelClient, ModelError
from app.stt.live import LiveSession

log = logging.getLogger(__name__)

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


async def run_checkpoint(live: LiveSession, client: ModelClient) -> str | None:
    """One round of "should a quiz happen now?".

    Returns the trigger_reason for a new quiz ("length" or "topic_shift"), or None.
    Saving the quiz row is the caller's job; this only decides.
    """
    now = live.buffer.last_end
    decision = live.gate.decide(now)

    if decision is None:
        return None

    if decision == "length":
        live.gate.mark_quiz(now)
        return "length"

    previous = live.buffer.between(now - 120, now - 60)
    recent = live.buffer.last(60)
    if not previous or not recent:
        return None  # a silent minute: nothing to compare

    try:
        result = await detect_shift(client, previous, recent)
    except ModelError as e:
        log.warning("topic-shift check skipped: %s", e)
        return None

    if not result.shift:
        return None

    live.gate.mark_quiz(now)
    return "topic_shift"
