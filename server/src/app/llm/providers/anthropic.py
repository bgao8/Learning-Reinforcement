"""AnthropicProvider: the only module that imports the anthropic SDK."""
import anthropic

from app.llm.provider import Request
from app.llm.types import RawResponse, Usage
from app.llm.errors import InvalidOutput, ModelError, ModelTimeout, ModelUnavailable


class AnthropicProvider:
    def __init__(self, api_key: str):
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    async def complete(self, request: Request) -> RawResponse:
        extra = {}
        if request.schema is not None:
            extra["output_config"] = {"format": {"type": "json_schema", "schema": request.schema}}

        try:
            response = await self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                **extra,
            )

        except anthropic.APITimeoutError as e:
            raise ModelTimeout(str(e)) from e

        except (anthropic.APIConnectionError, anthropic.AuthenticationError, anthropic.RateLimitError) as e:
            raise ModelUnavailable(str(e)) from e

        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise ModelUnavailable(str(e)) from e
            raise ModelError(str(e)) from e

        text = None
        for b in response.content:
            if b.type == "text":
                text = b.text
                break
        if text is None:
            raise InvalidOutput("no text block in response.", "")

        return RawResponse(
            text=text,
            model=response.model,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason
        )