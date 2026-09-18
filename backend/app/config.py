from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "test", "staging", "production"] = "dev"

    # Neon pooled endpoint (host contains "-pooler"): API requests.
    # Empty is allowed so that unit tests and tooling can import the settings without a
    # database; asking for an engine without a URL fails with a clear message instead.
    database_url: str = ""
    # Neon direct endpoint: migrations, job worker, concurrency tests.
    database_url_direct: str = ""

    # Where this deployment is reachable; used for invitation links and the origin check.
    public_base_url: str = "http://localhost:5173"
    # Comma-separated extra origins allowed to send cookie-authenticated writes.
    extra_accepted_origins: str = ""

    # Sessions
    session_cookie_name: str = "sid"
    session_cookie_secure: bool = True
    session_idle_hours: int = 12
    session_absolute_days: int = 7

    # Login throttling
    login_attempt_limit: int = 10
    login_attempt_window_minutes: int = 15

    # Invitations
    invitation_expiry_days: int = 7

    # Outbound mail. With no host configured, invitation emails go to the log instead.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    mail_from: str = "FinanceBoard <no-reply@financeboard.local>"

    @property
    def accepted_origins(self) -> frozenset[str]:
        origins = {self.public_base_url.rstrip("/")}
        origins.update(
            origin.strip().rstrip("/")
            for origin in self.extra_accepted_origins.split(",")
            if origin.strip()
        )
        return frozenset(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
