from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "test", "staging", "production"] = "dev"

    # Neon pooled endpoint (host contains "-pooler"): API requests.
    database_url: str
    # Neon direct endpoint: migrations, job worker, concurrency tests.
    database_url_direct: str


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
