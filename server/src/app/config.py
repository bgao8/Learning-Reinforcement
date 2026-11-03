from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root, three levels up from this file:
#   server/src/server/config.py -> server/src -> server -> <repo root>
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    database_url: str
    anthropic_api_key: str | None = None
    ollama_host: str = "http://localhost:11434"

    smart_provider: str = "anthropic"
    smart_model: str = "claude-sonnet-5"
    smart_timeout_s: float = 30.0

    fast_provider: str = "ollama"
    fast_model: str = "llama3.2:3b"
    fast_timeout_s: float = 60.0

    stt_provider: str = "mlx"
    stt_model: str = "mlx-community/whisper-large-v3-turbo"
    stt_language: str = "en"

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy needs the driver named explicitly; we use psycopg (v3)."""
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        return self.database_url


settings = Settings()
