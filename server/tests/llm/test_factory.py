"""make_client threads each role's max_tokens and timeout from Settings into the ModelClient."""
from app.config import Settings
from app.llm.factory import make_client


def settings(**overrides) -> Settings:
    # _env_file=None so the repo .env can't change what we're asserting;
    # ollama for both roles so no API key is needed
    base = dict(_env_file=None, database_url="postgresql://x", smart_provider="ollama", fast_provider="ollama")
    return Settings(**(base | overrides))


def test_smart_defaults_leave_room_for_thinking():
    client = make_client("smart", settings())
    assert client.max_tokens == 16000
    assert client.timeout_s == 90.0


def test_fast_defaults():
    client = make_client("fast", settings())
    assert client.max_tokens == 1024
    assert client.timeout_s == 60.0


def test_roles_read_their_own_settings():
    s = settings(smart_max_tokens=5000, smart_timeout_s=12.0, fast_max_tokens=300, fast_timeout_s=7.0)
    smart, fast = make_client("smart", s), make_client("fast", s)
    assert (smart.max_tokens, smart.timeout_s) == (5000, 12.0)
    assert (fast.max_tokens, fast.timeout_s) == (300, 7.0)
