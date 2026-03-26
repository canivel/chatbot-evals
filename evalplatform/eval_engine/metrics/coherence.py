"""Coherence metric.

Evaluates the logical structure, flow, and internal consistency of a chatbot's
response.
"""

from __future__ import annotations

from typing import Any

import structlog

from evalplatform.eval_engine.judges.llm_judge import LLMJudge
from evalplatform.eval_engine.judges.prompts import COHERENCE_JUDGE_PROMPT
from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)

_COHERENCE_DIMENSIONS = (
    "logical_flow",
    "internal_consistency",
    "clarity",
    "completeness_of_thought",
    "structure",
)


@metric_registry.register
class CoherenceMetric(BaseMetric):
    """Evaluates the coherence of a chatbot's response.

    Assessed dimensions:
    - **logical_flow**: Ideas follow a logical sequence.
    - **internal_consistency**: No self-contradictions.
    - **clarity**: Language is clear and understandable.
    - **completeness_of_thought**: Ideas are fully developed.
    - **structure**: Response is well-organized.

    The overall score is the weighted average of dimension scores.
    """

    name: str = "coherence"
    description: str = (
        "Evaluates logical structure, flow, and consistency of the response"
    )
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.QUALITY

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0) -> None:
        self._judge = LLMJudge(model=model, temperature=temperature)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate coherence of the last assistant response.

        Args:
            conversation: Evaluation context with the conversation.

        Returns:
            A ``MetricResult`` with the coherence score and per-dimension
            breakdown.
        """
        response = conversation.last_assistant_message
        question = conversation.last_user_message

        if not response:
            return self._build_result(
                score=0.0,
                explanation="No assistant response found to evaluate.",
            )

        prompt = COHERENCE_JUDGE_PROMPT.format(
            question=question or "(no question)",
            response=response,
        )

        verdict = await self._judge.judge({"prompt": prompt})
        metadata: dict[str, Any] = verdict.metadata

        dimensions: dict[str, Any] = metadata.get("dimensions", {})
        contradictions: list[str] = metadata.get("contradictions_found", [])

        # Compute per-dimension scores
        dimension_scores: dict[str, float] = {}
        for dim in _COHERENCE_DIMENSIONS:
            dim_data = dimensions.get(dim, {})
            dimension_scores[dim] = float(dim_data.get("score", 0.0))

        # Use LLM's overall score, falling back to mean of dimensions
        if dimension_scores:
            avg = sum(dimension_scores.values()) / len(dimension_scores)
        else:
            avg = 0.0
        score = verdict.score if verdict.score > 0 else avg

        return self._build_result(
            score=score,
            explanation=verdict.reasoning,
            details={
                "dimensions": dimensions,
                "dimension_scores": dimension_scores,
                "contradictions_found": contradictions,
                "confidence": verdict.confidence,
            },
        )
