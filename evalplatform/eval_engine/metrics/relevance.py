"""Answer Relevance metric.

Evaluates whether the chatbot's response actually answers the user's question
by generating hypothetical questions the answer addresses and comparing them
with the actual question.
"""

from __future__ import annotations

from typing import Any

import structlog

from evalplatform.eval_engine.judges.llm_judge import LLMJudge
from evalplatform.eval_engine.judges.prompts import RELEVANCE_JUDGE_PROMPT
from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)


@metric_registry.register
class RelevanceMetric(BaseMetric):
    """Measures how relevant the chatbot's response is to the user's question.

    The metric works by:
    1. Asking an LLM to generate hypothetical questions that the response
       would perfectly answer.
    2. Assessing how well those hypothetical questions align with the actual
       user question (conceptual cosine-similarity).
    3. Returning a 0-1 score where 1.0 means the response directly and
       completely addresses the question.
    """

    name: str = "relevance"
    description: str = (
        "Evaluates whether the response actually answers the user's question"
    )
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.RELEVANCE

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0) -> None:
        self._judge = LLMJudge(model=model, temperature=temperature)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate answer relevance for the last Q/A pair.

        Args:
            conversation: Evaluation context with the conversation.

        Returns:
            A ``MetricResult`` with the relevance score and analysis details.
        """
        response = conversation.last_assistant_message
        question = conversation.last_user_message

        if not response:
            return self._build_result(
                score=0.0,
                explanation="No assistant response found to evaluate.",
            )

        if not question:
            return self._build_result(
                score=0.0,
                explanation="No user question found to evaluate relevance against.",
            )

        prompt = RELEVANCE_JUDGE_PROMPT.format(
            question=question,
            response=response,
        )

        verdict = await self._judge.judge({"prompt": prompt})
        metadata: dict[str, Any] = verdict.metadata

        return self._build_result(
            score=verdict.score,
            explanation=verdict.reasoning,
            details={
                "hypothetical_questions": metadata.get("hypothetical_questions", []),
                "alignment_reasoning": metadata.get("alignment_reasoning", ""),
                "addresses_question": metadata.get("addresses_question", False),
                "completeness": metadata.get("completeness", ""),
                "confidence": verdict.confidence,
            },
        )
