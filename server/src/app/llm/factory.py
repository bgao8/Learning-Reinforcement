"""make_client(role): build a ModelClient for a role ("smart" or "fast") from config."""
from app.config import Settings, settings as default_settings
from app.llm.client import ModelClient
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.ollama import OllamaProvider


def make_provider(name: str, s: Settings):
    if name == "anthropic":
        if not s.anthropic_api_key:
            raise ValueError("provider 'anthropic' needs ANTHROPIC_API_KEY in .env")
        return AnthropicProvider(api_key=s.anthropic_api_key)
    if name == "ollama":
        return OllamaProvider(host=s.ollama_host)
    raise ValueError(f"unknown provider {name!r} (expected 'anthropic' or 'ollama')")


def make_client(role: str, s: Settings = default_settings) -> ModelClient:
    if role == "smart":
        return ModelClient(make_provider(s.smart_provider, s), model=s.smart_model, max_tokens=s.smart_max_tokens, timeout_s=s.smart_timeout_s)
    if role == "fast":
        return ModelClient(make_provider(s.fast_provider, s), model=s.fast_model, max_tokens=s.fast_max_tokens, timeout_s=s.fast_timeout_s)
    raise ValueError(f"unknown role {role!r} (expected 'smart' or 'fast')")