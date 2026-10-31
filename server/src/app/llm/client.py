"""ModelClient: wraps a Provider with timeout, schema validation, 1 retry, typed errors."""
import time
import asyncio

from app.llm.errors import InvalidOutput, ModelError, ModelTimeout, ModelUnavailable
from app.llm.types import Message, Response
from app.llm.provider import Request
from app.llm.schema import validate

RETRYABLE = (InvalidOutput, ModelTimeout)

class ModelClient:
    def __init__(self, provider, model: str, max_tokens: int=1024, timeout_s: float=30.0):
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    async def generate(self, system: str, messages: list[Message], schema: dict | None = None) -> Response:
        request = Request(
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=self.max_tokens,
            schema=schema
        )

        start = time.perf_counter()

        for attempt in (1, 2):
            try:
                try:
                    raw = await asyncio.wait_for(self.provider.complete(request), timeout=self.timeout_s)
                except TimeoutError as e:
                    raise ModelTimeout(f"No response after {self.timeout_s}s") from e


                output = validate(raw.text, schema) if schema is not None else raw.text
                return Response(
                    output=output,
                    raw=raw,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    attempts=attempt,
                )

            # except InvalidOutput or ModelTimeout
            except RETRYABLE:
                if attempt == 2:
                    raise