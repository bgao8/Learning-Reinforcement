from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives at the repo root, three levels up from this file:
#   server/src/server/config.py -> server/src -> server -> <repo root>
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    database_url: str

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy needs the driver named explicitly; we use psycopg (v3)."""
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        return self.database_url


settings = Settings()
