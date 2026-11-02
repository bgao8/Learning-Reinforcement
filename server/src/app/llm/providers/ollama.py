"""OllamaProvider: the only module that imports the ollama SDK."""
import ollama

from app.llm.errors import ModelError, ModelUnavailable
from app.llm.provider import Request
from app.llm.types import RawResponse, Usage


class OllamaProvider:
    def __init__(self, host: str = "http://localhost:11434"):
        self._client = ollama.AsyncClient(host=host)

    async def complete(self, request: Request) -> RawResponse:
        # Ollama has no separate system argument; it goes first in the message list
        messages = [{"role": "system", "content": request.system}] + [
            {"role": m.role, "content": m.content} for m in request.messages
        ]

        extra = {}
        if request.schema is not None:
            extra["format"] = request.schema

        try:
            response = await self._client.chat(
                model=request.model,
                messages=messages,
                options={"num_predict": request.max_tokens},
                **extra,
            )

        except ConnectionError as e:
            raise ModelUnavailable(str(e)) from e

        except ollama.ResponseError as e:
            if e.status_code >= 500:
                raise ModelUnavailable(str(e)) from e
            raise ModelError(str(e)) from e

        return RawResponse(
            text=response.message.content,
            model=response.model,
            usage=Usage(
                # None when Ollama reused a cached prompt
                input_tokens=response.prompt_eval_count or 0,
                output_tokens=response.eval_count or 0,
            ),
            stop_reason=response.done_reason,
        )
