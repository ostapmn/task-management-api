from pydantic import field_validator
from pydantic_settings import BaseSettings

MIN_SECRET_BYTES = 32
PLACEHOLDER_SECRETS = {"dev-secret", "change-me", "change-me-in-production", "secret", "changeme"}


class Settings(BaseSettings):
    # Both are required: there is deliberately no built-in default for credentials.
    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    worker_enabled: bool = True
    worker_interval_seconds: int = 60
    max_active_tasks: int = 10

    @field_validator("secret_key")
    @classmethod
    def _strong_secret(cls, value: str) -> str:
        if value.lower() in PLACEHOLDER_SECRETS or len(value.encode()) < MIN_SECRET_BYTES:
            raise ValueError(
                f"SECRET_KEY must be a random value of at least {MIN_SECRET_BYTES} bytes "
                "(generate one with: openssl rand -hex 32)"
            )
        return value


settings = Settings()
