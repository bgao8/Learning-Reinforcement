"""Provider protocol: complete(request) -> RawResponse. One adapter per backend."""

from dataclasses import dataclass
from typing import Protocol

from app.llm.types import Message, RawResponse

@dataclass(frozen=True)
class Request:
    """Everything a provider needs for a model call."""
    model: str
    system: str
    messages: list[Message]
    max_tokens: int
    schema: dict | None = None


class Provider(Protocol):
    """Anything with this method counts as a provider."""
    async def complete(self, request: Request) -> RawResponse:
        pass