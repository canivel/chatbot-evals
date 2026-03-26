"""SDK configuration management.

Provides a global configuration singleton that can be set via environment
variables or programmatically with :func:`configure`.

Environment variables
---------------------
- ``CHATBOT_EVALS_API_KEY`` -- Platform API key.
- ``CHATBOT_EVALS_API_URL`` -- Platform API base URL.
- ``OPENAI_API_KEY`` -- OpenAI API key (used by the judge model).
- ``ANTHROPIC_API_KEY`` -- Anthropic API key.
- ``GOOGLE_API_KEY`` -- Google Gemini API key.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from pydantic import BaseModel, Field

import structlog

logger = structlog.get_logger(__name__)


class Config(BaseModel):
    """Global SDK configuration.

    Attributes:
        api_key: Platform API key for authenticated endpoints.
        api_url: Platform API base URL.
        judge_model: Default LLM model used as the evaluation judge.
        default_metrics: Metrics to run when none are explicitly specified.
        max_concurrency: Maximum number of concurrent evaluations.
        timeout: Per-request timeout in seconds.
        verbose: If ``True``, emit debug-level log output.

    Example::

        from chatbot_evals.config import Config
        cfg = Config(judge_model="claude-sonnet-4-20250514", verbose=True)
    """

    api_key: str | None = Field(default=None, description="Platform API key")
    api_url: str | None = Field(default=None, description="Platform API base URL")
    judge_model: str = Field(default="gpt-4o", description="Default judge model")
    default_metrics: list[str] = Field(
        default_factory=list,
        description="Metrics to run when none specified (empty = all registered)",
    )
    max_concurrency: int = Field(default=10, ge=1, description="Max concurrent evaluations")
    timeout: float = Field(default=60.0, gt=0, description="Per-request timeout in seconds")
    verbose: bool = Field(default=False, description="Enable verbose/debug logging")


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_config: Config | None = None
_lock = threading.Lock()


def _load_from_env() -> Config:
    """Build a :class:`Config` from environment variables."""
    return Config(
        api_key=os.environ.get("CHATBOT_EVALS_API_KEY"),
        api_url=os.environ.get("CHATBOT_EVALS_API_URL"),
        judge_model=os.environ.get("CHATBOT_EVALS_JUDGE_MODEL", "gpt-4o"),
        verbose=os.environ.get("CHATBOT_EVALS_VERBOSE", "").lower() in ("1", "true", "yes"),
    )


def get_config() -> Config:
    """Return the current global :class:`Config`, loading from env on first access.

    Example::

        from chatbot_evals.config import get_config
        cfg = get_config()
        print(cfg.judge_model)
    """
    global _config
    if _config is None:
        with _lock:
            if _config is None:
                _config = _load_from_env()
                logger.debug("config_loaded_from_env", judge_model=_config.judge_model)
    return _config


def configure(**kwargs: Any) -> Config:
    """Set global SDK configuration.

    Any keyword accepted by :class:`Config` can be passed.  Values not
    provided keep their current (or default) value.

    Args:
        **kwargs: Configuration values to set.

    Returns:
        The updated :class:`Config`.

    Example::

        import chatbot_evals as ce
        from chatbot_evals.config import configure

        configure(judge_model="claude-sonnet-4-20250514", verbose=True)
    """
    global _config
    with _lock:
        current = _config or _load_from_env()
        merged = current.model_dump()
        merged.update({k: v for k, v in kwargs.items() if v is not None})
        _config = Config(**merged)
        logger.debug("config_updated", **{k: v for k, v in kwargs.items() if v is not None})
    return _config


def reset_config() -> None:
    """Reset the global configuration to ``None`` (primarily for testing)."""
    global _config
    with _lock:
        _config = None
