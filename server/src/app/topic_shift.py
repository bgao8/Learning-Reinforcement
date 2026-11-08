"""Topic-shift detection: did the lecture move to a new topic?"""
from dataclasses import dataclass
from pathlib import Path

from app.llm import Message, ModelClient

PROMPT = (Path(__file__).parent / "prompts" / "topic_shift_v1.txt").read_text()

SHIFT_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "shift": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["reason", "shift", "confidence"],
    "additionalProperties": False
}


@dataclass(frozen=True)
class ShiftResult:
    shift: bool
    confidence: float
    reason: str


async def detect_shift(client: ModelClient, previous: str, recent: str) -> ShiftResult:
    text = f"PREVIOUS\n {previous} \nRECENT\n {recent}"
    response = await client.generate(system=PROMPT, messages=[Message(role="user", content=text)], schema=SHIFT_SCHEMA)

    return ShiftResult(shift=response.output["shift"], confidence=response.output["confidence"], reason=response.output["reason"])