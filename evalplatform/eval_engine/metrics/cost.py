"""Cost metric (computation-based, no LLM calls).

Tracks token usage and estimated cost per conversation, scoring against
configurable cost thresholds.
"""

from __future__ import annotations

from typing import Any

import structlog

from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)

# Pricing per 1 000 tokens (input, output) in USD.
# Kept as a simple dict so callers can override or extend.
DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.0025, "output": 0.0100},
    "gpt-4o-mini": {"input": 0.000150, "output": 0.000600},
    "gpt-4-turbo": {"input": 0.0100, "output": 0.0300},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "claude-3-opus": {"input": 0.0150, "output": 0.0750},
    "claude-3-sonnet": {"input": 0.0030, "output": 0.0150},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-3.5-sonnet": {"input": 0.0030, "output": 0.0150},
}

# Default cost thresholds per conversation (USD)
_DEFAULT_COST_THRESHOLDS = {
    "excellent": 0.01,
    "good": 0.05,
    "acceptable": 0.15,
    "expensive": 0.50,
    # anything above 0.50 is "very_expensive"
}


@metric_registry.register
class CostMetric(BaseMetric):
    """Tracks token usage and estimated cost per conversation.

    This is a **computation-based** metric that does not use an LLM.  It
    expects token-usage information in turn or conversation metadata:

    - ``turn.metadata["input_tokens"]`` / ``turn.metadata["output_tokens"]``
    - ``conversation.metadata["model"]`` (to look up pricing)
    - Or ``conversation.metadata["total_cost"]`` as a pre-computed override.

    Scoring thresholds (USD per conversation):
    - Excellent (1.0): < $0.01
    - Good (0.8): < $0.05
    - Acceptable (0.6): < $0.15
    - Expensive (0.3): < $0.50
    - Very expensive (0.1): >= $0.50
    """

    name: str = "cost"
    description: str = "Tracks token usage and estimated cost per conversation"
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.COST

    def __init__(
        self,
        model_pricing: dict[str, dict[str, float]] | None = None,
        cost_thresholds: dict[str, float] | None = None,
    ) -> None:
        self._pricing = model_pricing or DEFAULT_MODEL_PRICING
        self._thresholds = cost_thresholds or _DEFAULT_COST_THRESHOLDS

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate token usage and cost for a conversation.

        Args:
            conversation: Evaluation context with token metadata.

        Returns:
            A ``MetricResult`` with cost breakdown and score.
        """
        # Check for pre-computed cost
        precomputed = conversation.metadata.get("total_cost")
        if precomputed is not None:
            total_cost = float(precomputed)
            return self._build_cost_result(
                total_cost=total_cost,
                details={"source": "precomputed", "total_cost_usd": total_cost},
            )

        model = conversation.metadata.get("model", "gpt-4o")
        pricing = self._pricing.get(model, self._pricing.get("gpt-4o", {"input": 0.0025, "output": 0.01}))

        total_input_tokens = 0
        total_output_tokens = 0

        for turn in conversation.conversation:
            input_tokens = turn.metadata.get("input_tokens", 0)
            output_tokens = turn.metadata.get("output_tokens", 0)
            total_input_tokens += int(input_tokens)
            total_output_tokens += int(output_tokens)

        # Fallback to conversation-level totals
        if total_input_tokens == 0 and total_output_tokens == 0:
            total_input_tokens = int(conversation.metadata.get("total_input_tokens", 0))
            total_output_tokens = int(conversation.metadata.get("total_output_tokens", 0))

        input_cost = (total_input_tokens / 1000.0) * pricing["input"]
        output_cost = (total_output_tokens / 1000.0) * pricing["output"]
        total_cost = input_cost + output_cost

        if total_input_tokens == 0 and total_output_tokens == 0:
            return self._build_result(
                score=0.0,
                explanation="No token usage data found in conversation metadata.",
                details={"error": "missing_token_data"},
            )

        return self._build_cost_result(
            total_cost=total_cost,
            details={
                "source": "computed",
                "model": model,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
                "input_cost_usd": round(input_cost, 6),
                "output_cost_usd": round(output_cost, 6),
                "total_cost_usd": round(total_cost, 6),
                "pricing_per_1k": pricing,
            },
        )

    # -- Helpers -------------------------------------------------------------

    def _build_cost_result(
        self, total_cost: float, details: dict[str, Any]
    ) -> MetricResult:
        """Build a MetricResult from the total cost."""
        score = self._score_from_cost(total_cost)
        grade = self._grade_from_cost(total_cost)
        details["grade"] = grade
        details["thresholds"] = self._thresholds

        return self._build_result(
            score=score,
            explanation=f"Estimated cost ${total_cost:.4f} ({grade}).",
            details=details,
        )

    def _score_from_cost(self, cost: float) -> float:
        """Convert cost to a 0-1 score using thresholds."""
        if cost < self._thresholds.get("excellent", 0.01):
            return 1.0
        if cost < self._thresholds.get("good", 0.05):
            return 0.8
        if cost < self._thresholds.get("acceptable", 0.15):
            return 0.6
        if cost < self._thresholds.get("expensive", 0.50):
            return 0.3
        return 0.1

    def _grade_from_cost(self, cost: float) -> str:
        """Convert cost to a human-readable grade."""
        if cost < self._thresholds.get("excellent", 0.01):
            return "excellent"
        if cost < self._thresholds.get("good", 0.05):
            return "good"
        if cost < self._thresholds.get("acceptable", 0.15):
            return "acceptable"
        if cost < self._thresholds.get("expensive", 0.50):
            return "expensive"
        return "very_expensive"
