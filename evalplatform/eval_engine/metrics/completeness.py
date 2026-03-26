"""Completeness metric.

Evaluates whether the chatbot's response fully addresses all aspects of the
user's query, identifying any missed topics or partial answers.
"""

from __future__ import annotations

from typing import Any

import structlog

from evalplatform.eval_engine.judges.llm_judge import LLMJudge
from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)

_COMPLETENESS_PROMPT = """\
You are an expert judge evaluating whether a chatbot's response completely \
addresses all aspects of the user's question.

## Task
1. Identify every distinct topic, sub-question, or aspect in the **Question**.
2. For each aspect, determine whether the **Response** addresses it: \
fully, partially, or not at all.
3. Identify any important topics the response missed entirely.

## Input
**Question:** {question}

**Response:**
{response}

{context_section}

## Output Format
Respond with ONLY a JSON object:
{{
  "aspects": [
    {{
      "aspect": "<description of the topic/sub-question>",
      "coverage": "full" | "partial" | "missing",
      "explanation": "<how the response handles this aspect>"
    }}
  ],
  "missed_topics": ["<topic1>", ...],
  "total_aspects": <int>,
  "fully_covered": <int>,
  "partially_covered": <int>,
  "missing": <int>,
  "score": <float 0-1>,
  "reasoning": "<brief overall explanation>"
}}
"""


@metric_registry.register
class CompletenessMetric(BaseMetric):
    """Evaluates whether the response fully addresses all aspects of the query.

    The metric:
    1. Identifies distinct topics / sub-questions in the user's query.
    2. Checks whether each is fully, partially, or not addressed.
    3. Computes a weighted score: full = 1.0, partial = 0.5, missing = 0.0.
    """

    name: str = "completeness"
    description: str = (
        "Evaluates whether the response fully addresses all aspects of the query"
    )
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.QUALITY

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0) -> None:
        self._judge = LLMJudge(model=model, temperature=temperature)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate completeness of the last assistant response.

        Args:
            conversation: Evaluation context with the conversation.

        Returns:
            A ``MetricResult`` with the completeness score and per-aspect
            breakdown.
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
                explanation="No user question found to assess completeness against.",
            )

        context_section = ""
        if conversation.ground_truth:
            context_section = f"**Expected Answer (ground truth):**\n{conversation.ground_truth}"

        prompt = _COMPLETENESS_PROMPT.format(
            question=question,
            response=response,
            context_section=context_section,
        )

        verdict = await self._judge.judge({"prompt": prompt})
        metadata: dict[str, Any] = verdict.metadata

        aspects: list[dict[str, Any]] = metadata.get("aspects", [])
        missed_topics: list[str] = metadata.get("missed_topics", [])

        # Compute weighted score from aspects
        total = len(aspects) or 1
        weighted_sum = 0.0
        for aspect in aspects:
            coverage = aspect.get("coverage", "missing")
            if coverage == "full":
                weighted_sum += 1.0
            elif coverage == "partial":
                weighted_sum += 0.5
            # "missing" contributes 0.0

        computed_score = weighted_sum / total
        score = verdict.score if verdict.score > 0 else computed_score

        return self._build_result(
            score=score,
            explanation=verdict.reasoning,
            details={
                "aspects": aspects,
                "missed_topics": missed_topics,
                "total_aspects": metadata.get("total_aspects", total),
                "fully_covered": metadata.get("fully_covered", 0),
                "partially_covered": metadata.get("partially_covered", 0),
                "missing": metadata.get("missing", 0),
                "confidence": verdict.confidence,
            },
        )
