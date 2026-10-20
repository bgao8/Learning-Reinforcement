"""Provider-neutral data types (dataclasses): Message, Usage, RawResponse, Response."""
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

T = TypeVar("T")

@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class RawResponse:
    text: str
    model: str
    usage: Usage
    stop_reason: str


@dataclass(frozen=True)
class Response(Generic[T]):
    output: T
    raw: RawResponse
    latency_ms: float
    attempts: int