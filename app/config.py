from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://app:app@db:5432/app"
    secret_key: str = "dev-secret"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    worker_enabled: bool = True
    worker_interval_seconds: int = 60
    max_active_tasks: int = 10


settings = Settings()
