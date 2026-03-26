"""Pairwise comparison judge for A/B testing chatbot responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

import structlog

from evalplatform.eval_engine.judges.llm_judge import LLMJudge
from evalplatform.eval_engine.judges.base_judge import JudgeVerdict
from evalplatform.eval_engine.judges.prompts import PAIRWISE_COMPARISON_PROMPT

logger = structlog.get_logger(__name__)


class PairwiseResult(BaseModel):
    """Extended result for pairwise comparisons."""

    winner: str = Field(
        ..., description="'A', 'B', or 'tie'"
    )
    score_a: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Score for response A"
    )
    score_b: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Score for response B"
    )
    reasoning: str = Field(default="", description="Overall comparison reasoning")
    confidence: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Confidence in the comparison"
    )
    criteria_comparison: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-criterion breakdown of the comparison",
    )
    raw_response: str = Field(default="")


class PairwiseJudge:
    """Compares two chatbot responses and determines which is better.

    Useful for A/B testing chatbot versions, comparing model outputs, or
    ranking responses.

    Args:
        model: The model identifier for the judge LLM (e.g. ``"gpt-4o"``).
        temperature: Sampling temperature.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.0,
    ) -> None:
        self._llm_judge = LLMJudge(model=model, temperature=temperature)

    async def compare(
        self,
        question: str,
        response_a: str,
        response_b: str,
        context: str | None = None,
    ) -> PairwiseResult:
        """Compare two responses for the same question.

        Args:
            question: The user question both responses address.
            response_a: First chatbot response.
            response_b: Second chatbot response.
            context: Optional reference context for factual comparisons.

        Returns:
            A :class:`PairwiseResult` indicating the winner and reasoning.
        """
        context_section = ""
        if context:
            context_section = f"**Reference Context:**\n{context}"

        prompt = PAIRWISE_COMPARISON_PROMPT.format(
            question=question,
            response_a=response_a,
            response_b=response_b,
            context_section=context_section,
        )

        verdict: JudgeVerdict = await self._llm_judge.judge({"prompt": prompt})

        # Extract pairwise-specific fields from the metadata
        metadata = verdict.metadata
        winner = str(metadata.get("winner", "tie")).upper()
        if winner not in ("A", "B", "TIE"):
            winner = "tie"

        return PairwiseResult(
            winner=winner,
            score_a=float(metadata.get("score_a", 0.5)),
            score_b=float(metadata.get("score_b", 0.5)),
            reasoning=verdict.reasoning,
            confidence=verdict.confidence,
            criteria_comparison=metadata.get("criteria_comparison", {}),
            raw_response=verdict.raw_response,
        )

    async def compare_batch(
        self,
        comparisons: list[dict[str, Any]],
        max_concurrency: int = 5,
    ) -> list[PairwiseResult]:
        """Run multiple pairwise comparisons concurrently.

        Each item in *comparisons* should be a dict with keys: ``question``,
        ``response_a``, ``response_b``, and optionally ``context``.
        """
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _limited(comp: dict[str, Any]) -> PairwiseResult:
            async with semaphore:
                return await self.compare(
                    question=comp["question"],
                    response_a=comp["response_a"],
                    response_b=comp["response_b"],
                    context=comp.get("context"),
                )

        tasks = [_limited(c) for c in comparisons]
        return list(await asyncio.gather(*tasks))

    def __repr__(self) -> str:
        return f"<PairwiseJudge model={self._llm_judge.model!r}>"
