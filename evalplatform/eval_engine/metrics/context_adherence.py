"""Context Adherence metric.

Checks whether the chatbot stays within its knowledge boundary and does not
answer questions it should not, which is critical for enterprise chatbots with
specific scopes.
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

_CONTEXT_ADHERENCE_PROMPT = """\
You are an expert judge evaluating whether a chatbot stays within its \
knowledge boundary.

## Task
An enterprise chatbot should ONLY answer questions it has context for. \
Evaluate whether the chatbot:
1. Only uses information from the provided context and system prompt.
2. Appropriately declines to answer when the question is out of scope.
3. Does not make assumptions beyond what the context supports.
4. Stays within its defined role (if a system prompt is provided).

## Input
**System Prompt (chatbot's role):**
{system_prompt}

**User Question:** {question}

**Available Context:**
{context}

**Chatbot Response:**
{response}

## Output Format
Respond with ONLY a JSON object:
{{
  "within_scope": true | false,
  "uses_only_provided_context": true | false,
  "appropriately_declines_out_of_scope": true | false | "not_applicable",
  "boundary_violations": [
    {{
      "violation": "<description of boundary violation>",
      "severity": "low" | "medium" | "high"
    }}
  ],
  "score": <float 0-1, 1 = perfect adherence>,
  "reasoning": "<brief overall explanation>"
}}
"""


@metric_registry.register
class ContextAdherenceMetric(BaseMetric):
    """Checks if the chatbot stays within its knowledge boundary.

    Critical for enterprise chatbots with specific scopes.  Evaluates:
    - Whether the response only uses information from provided context.
    - Whether out-of-scope questions are properly declined.
    - Whether the chatbot stays within its defined role.

    A score of 1.0 means perfect adherence to the knowledge boundary.
    """

    name: str = "context_adherence"
    description: str = (
        "Checks if the chatbot stays within its knowledge boundary and scope"
    )
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.FAITHFULNESS

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0) -> None:
        self._judge = LLMJudge(model=model, temperature=temperature)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Evaluate context adherence of the last assistant response.

        Args:
            conversation: Evaluation context with conversation, system prompt,
                and retrieved context.

        Returns:
            A ``MetricResult`` with the adherence score and violation details.
        """
        response = conversation.last_assistant_message
        question = conversation.last_user_message

        if not response:
            return self._build_result(
                score=1.0,
                explanation="No assistant response found; nothing to evaluate.",
            )

        context_text = (
            "\n\n---\n\n".join(conversation.retrieved_context)
            if conversation.retrieved_context
            else "(no context provided)"
        )

        system_prompt = conversation.system_prompt or "(no system prompt provided)"

        prompt = _CONTEXT_ADHERENCE_PROMPT.format(
            system_prompt=system_prompt,
            question=question or "(no question)",
            context=context_text,
            response=response,
        )

        verdict = await self._judge.judge({"prompt": prompt})
        metadata: dict[str, Any] = verdict.metadata

        violations: list[dict[str, Any]] = metadata.get("boundary_violations", [])

        return self._build_result(
            score=verdict.score,
            explanation=verdict.reasoning,
            details={
                "within_scope": metadata.get("within_scope", True),
                "uses_only_provided_context": metadata.get(
                    "uses_only_provided_context", True
                ),
                "appropriately_declines_out_of_scope": metadata.get(
                    "appropriately_declines_out_of_scope", "not_applicable"
                ),
                "boundary_violations": violations,
                "violation_count": len(violations),
                "confidence": verdict.confidence,
            },
        )
