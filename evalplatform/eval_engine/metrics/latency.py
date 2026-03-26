"""Latency metric (computation-based, no LLM calls).

Measures response time statistics and scores them against configurable
thresholds.
"""

from __future__ import annotations

import statistics
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

# Default thresholds in seconds
_DEFAULT_THRESHOLDS = {
    "excellent": 1.0,  # < 1s
    "good": 3.0,       # < 3s
    "acceptable": 5.0, # < 5s
    "slow": 10.0,      # < 10s
    # anything above 10s is "very_slow"
}


@metric_registry.register
class LatencyMetric(BaseMetric):
    """Measures response time statistics and scores against thresholds.

    This is a **computation-based** metric that does not use an LLM.  It
    expects latency values (in seconds) to be provided in turn metadata
    under the key ``latency_seconds``.

    Default scoring thresholds:
    - Excellent (1.0): < 1 s
    - Good (0.8): < 3 s
    - Acceptable (0.6): < 5 s
    - Slow (0.3): < 10 s
    - Very slow (0.1): >= 10 s
    """

    name: str = "latency"
    description: str = "Measures response time statistics and scores against thresholds"
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.PERFORMANCE

    def __init__(
        self,
        thresholds: dict[str, float] | None = None,
    ) -> None:
        self._thresholds = thresholds or _DEFAULT_THRESHOLDS

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate latency across assistant turns.

        Latency values are read from ``turn.metadata["latency_seconds"]`` for
        each assistant turn.  If no latency data is found, a fallback value
        from ``conversation.metadata["latency_seconds"]`` (single value or
        list) is used.

        Args:
            conversation: Evaluation context with conversation turns.

        Returns:
            A ``MetricResult`` with percentile statistics and latency grade.
        """
        latencies = self._collect_latencies(conversation)

        if not latencies:
            return self._build_result(
                score=0.0,
                explanation="No latency data found in conversation metadata.",
                details={"error": "missing_latency_data"},
            )

        # Compute statistics
        p50 = self._percentile(latencies, 50)
        p95 = self._percentile(latencies, 95)
        p99 = self._percentile(latencies, 99)
        mean = statistics.mean(latencies)
        stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

        # Score based on median latency
        score = self._score_from_latency(p50)
        grade = self._grade_from_latency(p50)

        return self._build_result(
            score=score,
            explanation=f"Median latency {p50:.3f}s ({grade}). p95={p95:.3f}s, p99={p99:.3f}s.",
            details={
                "p50": round(p50, 4),
                "p95": round(p95, 4),
                "p99": round(p99, 4),
                "mean": round(mean, 4),
                "stdev": round(stdev, 4),
                "min": round(min(latencies), 4),
                "max": round(max(latencies), 4),
                "sample_count": len(latencies),
                "grade": grade,
                "thresholds": self._thresholds,
            },
        )

    # -- Helpers -------------------------------------------------------------

    def _collect_latencies(self, conversation: EvalContext) -> list[float]:
        """Extract latency values from conversation turns and metadata."""
        latencies: list[float] = []

        # Try per-turn metadata first
        for turn in conversation.conversation:
            if turn.role == "assistant" and "latency_seconds" in turn.metadata:
                val = turn.metadata["latency_seconds"]
                if isinstance(val, (int, float)) and val >= 0:
                    latencies.append(float(val))

        # Fallback to conversation-level metadata
        if not latencies:
            meta_val = conversation.metadata.get("latency_seconds")
            if isinstance(meta_val, list):
                latencies = [float(v) for v in meta_val if isinstance(v, (int, float)) and v >= 0]
            elif isinstance(meta_val, (int, float)) and meta_val >= 0:
                latencies = [float(meta_val)]

        return latencies

    def _score_from_latency(self, latency_seconds: float) -> float:
        """Convert a latency value to a 0-1 score using thresholds."""
        if latency_seconds < self._thresholds.get("excellent", 1.0):
            return 1.0
        if latency_seconds < self._thresholds.get("good", 3.0):
            return 0.8
        if latency_seconds < self._thresholds.get("acceptable", 5.0):
            return 0.6
        if latency_seconds < self._thresholds.get("slow", 10.0):
            return 0.3
        return 0.1

    def _grade_from_latency(self, latency_seconds: float) -> str:
        """Convert a latency value to a human-readable grade."""
        if latency_seconds < self._thresholds.get("excellent", 1.0):
            return "excellent"
        if latency_seconds < self._thresholds.get("good", 3.0):
            return "good"
        if latency_seconds < self._thresholds.get("acceptable", 5.0):
            return "acceptable"
        if latency_seconds < self._thresholds.get("slow", 10.0):
            return "slow"
        return "very_slow"

    @staticmethod
    def _percentile(data: list[float], pct: float) -> float:
        """Compute the *pct*-th percentile of *data*."""
        sorted_data = sorted(data)
        n = len(sorted_data)
        if n == 1:
            return sorted_data[0]
        k = (pct / 100.0) * (n - 1)
        f = int(k)
        c = f + 1 if f + 1 < n else f
        d = k - f
        return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])
