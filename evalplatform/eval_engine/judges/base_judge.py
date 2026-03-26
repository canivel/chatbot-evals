"""Abstract judge interface for the evaluation engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

import structlog

logger = structlog.get_logger(__name__)


class JudgeVerdict(BaseModel):
    """The output of a judge evaluation."""

    score: float = Field(
        ..., ge=0.0, le=1.0, description="Normalized score between 0 and 1"
    )
    reasoning: str = Field(
        default="", description="Step-by-step reasoning for the verdict"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the verdict (0-1)",
    )
    raw_response: str = Field(
        default="", description="Raw LLM response before parsing"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional judge-specific metadata"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class BaseJudge(ABC):
    """Abstract base class for all judge implementations.

    A judge takes input data (e.g. a conversation, a claim, a pair of
    responses) and produces a :class:`JudgeVerdict` containing a score,
    reasoning, and confidence level.
    """

    @abstractmethod
    async def judge(self, input_data: dict[str, Any]) -> JudgeVerdict:
        """Evaluate the input data and return a verdict.

        Args:
            input_data: A dictionary whose schema depends on the concrete
                judge implementation.

        Returns:
            A ``JudgeVerdict`` with score, reasoning, and confidence.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
