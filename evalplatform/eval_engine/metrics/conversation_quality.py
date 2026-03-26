"""Multi-turn Conversation Quality metric.

Evaluates quality across multiple conversation turns rather than a single Q/A
pair, checking topic consistency, context retention, and escalation handling.
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

_CONVERSATION_QUALITY_PROMPT = """\
You are an expert judge evaluating the quality of a multi-turn chatbot \
conversation.

## Task
Evaluate the entire conversation (not just the last turn) on these dimensions:
1. **Topic consistency** - Does the chatbot stay on topic or drift?
2. **Context retention** - Does the chatbot remember and correctly use \
information from earlier turns?
3. **Escalation handling** - When the user shows frustration or asks for \
help beyond the chatbot's ability, does it handle this well?
4. **Turn-level quality** - Rate each assistant turn for helpfulness.
5. **Overall flow** - Does the conversation feel natural and productive?

## Conversation
{conversation}

## Output Format
Respond with ONLY a JSON object:
{{
  "dimensions": {{
    "topic_consistency": {{"score": <float 0-1>, "explanation": "<text>"}},
    "context_retention": {{"score": <float 0-1>, "explanation": "<text>"}},
    "escalation_handling": {{"score": <float 0-1>, "explanation": "<text>"}},
    "overall_flow": {{"score": <float 0-1>, "explanation": "<text>"}}
  }},
  "turn_scores": [
    {{
      "turn_index": <int>,
      "role": "assistant",
      "score": <float 0-1>,
      "explanation": "<text>"
    }}
  ],
  "issues_found": ["<issue1>", ...],
  "score": <float 0-1>,
  "reasoning": "<brief overall explanation>"
}}
"""


@metric_registry.register
class ConversationQualityMetric(BaseMetric):
    """Evaluates quality across multiple turns of a conversation.

    Unlike single-turn metrics, this looks at the conversation holistically:
    - **Topic consistency**: Does the chatbot maintain topical coherence?
    - **Context retention**: Are earlier turns remembered and used?
    - **Escalation handling**: Are difficult situations handled gracefully?
    - **Turn-level quality**: Per-turn helpfulness scores.

    The overall score aggregates dimension and per-turn scores.
    """

    name: str = "conversation_quality"
    description: str = (
        "Evaluates quality across multiple conversation turns"
    )
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.QUALITY

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0) -> None:
        self._judge = LLMJudge(model=model, temperature=temperature, max_tokens=8192)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate the overall quality of a multi-turn conversation.

        Args:
            conversation: Evaluation context with the full conversation.

        Returns:
            A ``MetricResult`` with the conversation quality score and
            per-dimension / per-turn breakdown.
        """
        if len(conversation.conversation) < 2:
            return self._build_result(
                score=0.0,
                explanation="Conversation has fewer than 2 turns; cannot assess multi-turn quality.",
            )

        # Format conversation for the prompt
        formatted_turns: list[str] = []
        for i, turn in enumerate(conversation.conversation):
            formatted_turns.append(f"[Turn {i + 1}] {turn.role}: {turn.content}")
        conversation_text = "\n\n".join(formatted_turns)

        prompt = _CONVERSATION_QUALITY_PROMPT.format(
            conversation=conversation_text,
        )

        verdict = await self._judge.judge({"prompt": prompt})
        metadata: dict[str, Any] = verdict.metadata

        dimensions: dict[str, Any] = metadata.get("dimensions", {})
        turn_scores: list[dict[str, Any]] = metadata.get("turn_scores", [])
        issues: list[str] = metadata.get("issues_found", [])

        # Compute per-dimension scores
        dimension_scores: dict[str, float] = {}
        for dim_name, dim_data in dimensions.items():
            dimension_scores[dim_name] = float(dim_data.get("score", 0.0))

        # Aggregate per-turn scores
        assistant_turn_scores = [
            ts["score"] for ts in turn_scores if ts.get("role") == "assistant"
        ]
        avg_turn_score = (
            sum(assistant_turn_scores) / len(assistant_turn_scores)
            if assistant_turn_scores
            else 0.0
        )

        return self._build_result(
            score=verdict.score,
            explanation=verdict.reasoning,
            details={
                "dimensions": dimensions,
                "dimension_scores": dimension_scores,
                "turn_scores": turn_scores,
                "average_turn_score": round(avg_turn_score, 4),
                "issues_found": issues,
                "total_turns": len(conversation.conversation),
                "confidence": verdict.confidence,
            },
        )
