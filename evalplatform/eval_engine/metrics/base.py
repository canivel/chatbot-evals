"""Base metric interface and core data models for the evaluation engine."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

import structlog

logger = structlog.get_logger(__name__)


class MetricCategory(str, Enum):
    """Categories for organizing evaluation metrics."""

    FAITHFULNESS = "faithfulness"
    RELEVANCE = "relevance"
    SAFETY = "safety"
    QUALITY = "quality"
    PERFORMANCE = "performance"
    COST = "cost"
    CUSTOM = "custom"


class ConversationTurn(BaseModel):
    """A single turn in a chatbot conversation."""

    role: str = Field(..., description="Role of the speaker: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="The text content of this turn")
    timestamp: datetime | None = Field(
        default=None, description="When this turn occurred"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary metadata for this turn"
    )


class EvalContext(BaseModel):
    """Full context provided for evaluating a conversation."""

    conversation: list[ConversationTurn] = Field(
        ..., description="The conversation turns to evaluate"
    )
    ground_truth: str | None = Field(
        default=None, description="Expected correct answer, if available"
    )
    retrieved_context: list[str] = Field(
        default_factory=list,
        description="Retrieved context documents used by the chatbot",
    )
    system_prompt: str | None = Field(
        default=None, description="The system prompt given to the chatbot"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata for evaluation"
    )

    @property
    def last_user_message(self) -> str | None:
        """Return the last user message in the conversation."""
        for turn in reversed(self.conversation):
            if turn.role == "user":
                return turn.content
        return None

    @property
    def last_assistant_message(self) -> str | None:
        """Return the last assistant message in the conversation."""
        for turn in reversed(self.conversation):
            if turn.role == "assistant":
                return turn.content
        return None


class MetricResult(BaseModel):
    """Result of a single metric evaluation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metric_name: str = Field(..., description="Name of the metric that produced this result")
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Normalized score between 0 and 1"
    )
    explanation: str = Field(
        default="", description="Human-readable explanation of the score"
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Metric-specific detailed breakdown"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this result was computed",
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class BaseMetric(ABC):
    """Abstract base class for all evaluation metrics.

    Every metric in the eval engine must inherit from this class and implement
    the ``evaluate`` method.  Metrics are registered with the
    :class:`~platform.eval_engine.registry.MetricRegistry` so the engine can
    discover and invoke them at runtime.
    """

    name: str = "base_metric"
    description: str = "Base metric"
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.CUSTOM

    @abstractmethod
    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate a conversation and return a metric result.

        Args:
            conversation: The full evaluation context including conversation
                turns, retrieved context, ground truth, and metadata.

        Returns:
            A ``MetricResult`` containing the score, explanation, and details.
        """
        ...

    def _build_result(
        self,
        score: float,
        explanation: str = "",
        details: dict[str, Any] | None = None,
    ) -> MetricResult:
        """Helper to construct a ``MetricResult`` pre-filled with this metric's name."""
        return MetricResult(
            metric_name=self.name,
            score=max(0.0, min(1.0, score)),
            explanation=explanation,
            details=details or {},
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} v{self.version}>"
