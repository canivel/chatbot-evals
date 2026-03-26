"""Custom metric support.

Provides two ways to create custom metrics at runtime:
1. ``CustomMetric`` -- wraps a user-defined async evaluation function.
2. ``LLMCustomMetric`` -- uses a custom prompt template with LLM-as-judge.
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable

import structlog

from evalplatform.eval_engine.judges.llm_judge import LLMJudge
from evalplatform.eval_engine.judges.prompts import CUSTOM_JUDGE_TEMPLATE
from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)

# Type alias for user-supplied evaluation functions
EvalFunction = Callable[[EvalContext], Awaitable[MetricResult]]


class CustomMetric(BaseMetric):
    """A metric backed by a user-defined async evaluation function.

    Usage::

        async def my_eval_fn(ctx: EvalContext) -> MetricResult:
            ...
            return MetricResult(metric_name="my_metric", score=0.9, ...)

        metric = CustomMetric(
            name="my_metric",
            description="My custom check",
            eval_fn=my_eval_fn,
        )
        metric_registry.register(type(metric))  # or register the class
    """

    # Defaults -- overridden in __init__
    name: str = "custom"
    description: str = "User-defined custom metric"
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.CUSTOM

    def __init__(
        self,
        name: str,
        description: str,
        eval_fn: EvalFunction,
        version: str = "1.0.0",
        category: MetricCategory = MetricCategory.CUSTOM,
    ) -> None:
        self.name = name
        self.description = description
        self.version = version
        self.category = category
        self._eval_fn = eval_fn

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Delegate to the user-supplied evaluation function.

        Args:
            conversation: The evaluation context.

        Returns:
            A ``MetricResult`` produced by the user function.
        """
        try:
            result = await self._eval_fn(conversation)
            # Ensure the metric name is set correctly
            result.metric_name = self.name
            return result
        except Exception as exc:
            logger.error(
                "custom_metric_error",
                metric=self.name,
                error=str(exc),
            )
            return self._build_result(
                score=0.0,
                explanation=f"Custom metric evaluation failed: {exc}",
                details={"error": str(exc)},
            )


class LLMCustomMetric(BaseMetric):
    """A metric that uses a custom prompt template with LLM-as-judge.

    The prompt template can use these placeholders:
    - ``{question}`` -- the last user message
    - ``{response}`` -- the last assistant message
    - ``{context}`` -- retrieved context (joined)
    - ``{system_prompt}`` -- the chatbot's system prompt
    - ``{ground_truth}`` -- the expected answer

    Usage::

        metric = LLMCustomMetric(
            name="brand_voice",
            description="Checks brand voice consistency",
            custom_instructions="Evaluate if the response matches the brand voice guidelines...",
        )
    """

    name: str = "llm_custom"
    description: str = "LLM-based custom metric with user-defined prompt"
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.CUSTOM

    def __init__(
        self,
        name: str,
        description: str,
        custom_instructions: str,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        version: str = "1.0.0",
        category: MetricCategory = MetricCategory.CUSTOM,
    ) -> None:
        self.name = name
        self.description = description
        self.version = version
        self.category = category
        self._custom_instructions = custom_instructions
        self._judge = LLMJudge(model=model, temperature=temperature)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        """Run the custom LLM judge evaluation.

        Args:
            conversation: The evaluation context.

        Returns:
            A ``MetricResult`` with the LLM judge's assessment.
        """
        response = conversation.last_assistant_message or ""
        question = conversation.last_user_message or ""

        extra_parts: list[str] = []
        if conversation.retrieved_context:
            ctx = "\n\n---\n\n".join(conversation.retrieved_context)
            extra_parts.append(f"**Context:**\n{ctx}")
        if conversation.ground_truth:
            extra_parts.append(f"**Expected Answer:**\n{conversation.ground_truth}")
        if conversation.system_prompt:
            extra_parts.append(f"**System Prompt:**\n{conversation.system_prompt}")

        extra_context = "\n\n".join(extra_parts) if extra_parts else ""

        prompt = CUSTOM_JUDGE_TEMPLATE.format(
            custom_instructions=self._custom_instructions,
            question=question,
            response=response,
            extra_context=extra_context,
        )

        verdict = await self._judge.judge({"prompt": prompt})

        return self._build_result(
            score=verdict.score,
            explanation=verdict.reasoning,
            details={
                "raw_details": verdict.metadata.get("details", {}),
                "confidence": verdict.confidence,
            },
        )


def register_custom_metric(
    name: str,
    description: str,
    eval_fn: EvalFunction,
    version: str = "1.0.0",
    category: MetricCategory = MetricCategory.CUSTOM,
) -> CustomMetric:
    """Convenience function to create and register a custom metric at runtime.

    Args:
        name: Unique metric name.
        description: Human-readable description.
        eval_fn: Async function that takes ``EvalContext`` and returns
            ``MetricResult``.
        version: Metric version string.
        category: Metric category.

    Returns:
        The instantiated ``CustomMetric``.
    """
    # Dynamically create a subclass so the registry stores a unique type
    metric_cls = type(
        f"Custom_{name}",
        (CustomMetric,),
        {
            "name": name,
            "description": description,
            "version": version,
            "category": category,
        },
    )
    instance = metric_cls(
        name=name,
        description=description,
        eval_fn=eval_fn,
        version=version,
        category=category,
    )
    metric_registry.register(metric_cls)
    # Store the instance so get_metric returns it with the eval_fn attached
    metric_registry._instances[name] = instance
    return instance


def register_llm_custom_metric(
    name: str,
    description: str,
    custom_instructions: str,
    model: str = "gpt-4o",
    temperature: float = 0.0,
    version: str = "1.0.0",
    category: MetricCategory = MetricCategory.CUSTOM,
) -> LLMCustomMetric:
    """Convenience function to create and register an LLM custom metric at runtime.

    Args:
        name: Unique metric name.
        description: Human-readable description.
        custom_instructions: Evaluation instructions for the LLM judge.
        model: The model identifier (e.g. ``"gpt-4o"``).
        temperature: Sampling temperature.
        version: Metric version string.
        category: Metric category.

    Returns:
        The instantiated ``LLMCustomMetric``.
    """
    metric_cls = type(
        f"LLMCustom_{name}",
        (LLMCustomMetric,),
        {
            "name": name,
            "description": description,
            "version": version,
            "category": category,
        },
    )
    instance = metric_cls(
        name=name,
        description=description,
        custom_instructions=custom_instructions,
        model=model,
        temperature=temperature,
        version=version,
        category=category,
    )
    metric_registry.register(metric_cls)
    metric_registry._instances[name] = instance
    return instance
