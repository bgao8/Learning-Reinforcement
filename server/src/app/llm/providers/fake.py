"""FakeProvider: returns canned responses, for tests."""
from app.llm.provider import Request
from app.llm.types import RawResponse, Usage, Response


class FakeProvider():
    def __init__(self, script: list[str | Exception]):
        self._script = iter(script)
        self.requests = []

    async def complete(self, request: Request) -> Response:
        self.requests.append(request)
        item = next(self._script, None)

        if item is None:
            raise AssertionError("FakeProvider script exhausted: client made more calls than expected")

        if isinstance(item, Exception):
            raise item
        
        return RawResponse(
            text=item, 
            model="fake",
            usage=Usage(0, 0),
            stop_reason="end_turn"
        )

