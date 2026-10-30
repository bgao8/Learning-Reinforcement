"""FakeProvider: returns canned responses, for tests."""
from app.llm.provider import Request
from app.llm.types import RawResponse, Usage
from app.llm.errors import InvalidOutput, ModelError, ModelTimeout, ModelUnavailable

class FakeProvider():
    def __init__(self, script: list[str | Exception]):
        self.script = script
        self._script = iter(script)
        self.requests = []

    async def complete(self, request: Request):
        self.requests.append(request)
        item = next(self._script)

        if isinstance(item, Exception):
            raise item
        
        return RawResponse(
            text=item, 
            model="fake",
            usage=Usage(0, 0),
            stop_reason="end_turn"
        )

