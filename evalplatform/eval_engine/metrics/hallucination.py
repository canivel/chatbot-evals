"""Hallucination Detection metric.

Detects fabricated information in the chatbot's response that is not present
in the provided context or common knowledge.
"""

from __future__ import annotations

from typing import Any

import structlog

from evalplatform.eval_engine.judges.llm_judge import LLMJudge
from evalplatform.eval_engine.judges.prompts import HALLUCINATION_JUDGE_PROMPT
from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)


@metric_registry.register
class HallucinationMetric(BaseMetric):
    """Detects hallucinations (fabricated information) in chatbot responses.

    The metric works by:
    1. Extracting all factual claims from the response.
    2. Checking each claim against the provided context and common knowledge.
    3. Flagging claims that are fabricated with severity levels.
    4. Computing score = 1 - (hallucinated_claims / total_claims).

    A score of 1.0 means no hallucinations were detected.
    A score of 0.0 means every claim was hallucinated.
    """

    name: str = "hallucination"
    description: str = (
        "Detects fabricated information not present in context or common knowledge"
    )
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.FAITHFULNESS

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0) -> None:
        self._judge = LLMJudge(model=model, temperature=temperature)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate the response for hallucinated content.

        Args:
            conversation: Evaluation context with conversation and retrieved
                context documents.

        Returns:
            A ``MetricResult`` with the hallucination score and per-claim
            breakdown.
        """
        response = conversation.last_assistant_message
        question = conversation.last_user_message

        if not response:
            return self._build_result(
                score=1.0,
                explanation="No assistant response found; nothing to check for hallucinations.",
            )

        context_text = (
            "\n\n---\n\n".join(conversation.retrieved_context)
            if conversation.retrieved_context
            else "(no context provided)"
        )

        prompt = HALLUCINATION_JUDGE_PROMPT.format(
            question=question or "(no question)",
            context=context_text,
            response=response,
        )

        verdict = await self._judge.judge({"prompt": prompt})
        metadata: dict[str, Any] = verdict.metadata

        claims: list[dict[str, Any]] = metadata.get("claims", [])
        total_claims = metadata.get("total_claims", len(claims))
        hallucinated_claims = metadata.get(
            "hallucinated_claims",
            sum(1 for c in claims if c.get("is_hallucinated")),
        )

        # score = 1 - (hallucinated / total), where 1 = no hallucinations
        if total_claims > 0:
            score = 1.0 - (hallucinated_claims / total_claims)
        else:
            score = verdict.score

        hallucinated_statements = [
            {
                "claim": c.get("claim", ""),
                "reason": c.get("reason", ""),
                "severity": c.get("severity", "medium"),
            }
            for c in claims
            if c.get("is_hallucinated")
        ]

        return self._build_result(
            score=score,
            explanation=verdict.reasoning,
            details={
                "claims": claims,
                "total_claims": total_claims,
                "hallucinated_claims": hallucinated_claims,
                "hallucinated_statements": hallucinated_statements,
                "severity_breakdown": self._severity_breakdown(claims),
                "confidence": verdict.confidence,
            },
        )

    @staticmethod
    def _severity_breakdown(claims: list[dict[str, Any]]) -> dict[str, int]:
        """Count hallucinated claims by severity level."""
        breakdown: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        for claim in claims:
            if claim.get("is_hallucinated"):
                severity = claim.get("severity", "medium")
                if severity in breakdown:
                    breakdown[severity] += 1
        return breakdown
