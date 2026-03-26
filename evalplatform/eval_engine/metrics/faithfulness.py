"""Faithfulness / Groundedness metric.

Evaluates whether a chatbot's response is grounded in the provided context by
extracting claims and checking each against the retrieved context documents.
"""

from __future__ import annotations

from typing import Any

import structlog

from evalplatform.eval_engine.judges.llm_judge import LLMJudge
from evalplatform.eval_engine.judges.prompts import FAITHFULNESS_JUDGE_PROMPT
from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)


@metric_registry.register
class FaithfulnessMetric(BaseMetric):
    """Measures how faithful the chatbot response is to the provided context.

    The metric works by:
    1. Extracting distinct factual claims from the assistant's response.
    2. Checking each claim against the retrieved context.
    3. Computing a score as the fraction of claims that are supported.

    A score of 1.0 means every claim is supported by the context.
    A score of 0.0 means no claims are supported.
    """

    name: str = "faithfulness"
    description: str = (
        "Evaluates whether the chatbot response is grounded in the provided context"
    )
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.FAITHFULNESS

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0) -> None:
        self._judge = LLMJudge(model=model, temperature=temperature)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate faithfulness of the last assistant response.

        Args:
            conversation: Evaluation context containing the conversation and
                retrieved context documents.

        Returns:
            A ``MetricResult`` with the faithfulness score and per-claim details.
        """
        response = conversation.last_assistant_message
        question = conversation.last_user_message

        if not response:
            return self._build_result(
                score=0.0,
                explanation="No assistant response found to evaluate.",
            )

        if not conversation.retrieved_context:
            logger.warning("faithfulness_no_context", metric=self.name)
            return self._build_result(
                score=0.0,
                explanation="No retrieved context provided; cannot assess faithfulness.",
            )

        context_text = "\n\n---\n\n".join(conversation.retrieved_context)

        prompt = FAITHFULNESS_JUDGE_PROMPT.format(
            question=question or "(no question)",
            context=context_text,
            response=response,
        )

        verdict = await self._judge.judge({"prompt": prompt})
        metadata: dict[str, Any] = verdict.metadata

        claims: list[dict[str, Any]] = metadata.get("claims", [])
        total = len(claims)
        supported = sum(
            1 for c in claims if c.get("verdict") == "supported"
        )
        contradicted = sum(
            1 for c in claims if c.get("verdict") == "contradicted"
        )

        score = verdict.score if total == 0 else supported / total

        return self._build_result(
            score=score,
            explanation=verdict.reasoning,
            details={
                "claims": claims,
                "total_claims": total,
                "supported_claims": supported,
                "contradicted_claims": contradicted,
                "not_mentioned_claims": total - supported - contradicted,
                "confidence": verdict.confidence,
            },
        )
