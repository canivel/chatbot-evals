"""Application settings loaded from environment variables using pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the chatbot-evals API.

    Values are read from environment variables (case-insensitive) and fall back
    to the defaults defined here.  A ``.env`` file in the project root is loaded
    automatically when present.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database -----------------------------------------------------------
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/chatbot_evals"
    )

    # --- Redis / Celery -----------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- JWT Auth -----------------------------------------------------------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration: int = 60  # minutes

    # --- Agent / LLM --------------------------------------------------------
    agent_model: str = "gpt-4o-mini"

    # --- Eval Engine --------------------------------------------------------
    eval_judge_model: str = "gpt-4o"
    eval_batch_size: int = 10

    # --- CORS ---------------------------------------------------------------
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Using ``lru_cache`` ensures the ``.env`` file is read only once and the
    same ``Settings`` object is reused across the lifetime of the process.
    """
    return Settings()
