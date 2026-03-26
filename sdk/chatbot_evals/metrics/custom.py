"""Custom metric creation helpers for the chatbot-evals SDK.

Provides two decorator-based approaches to creating custom metrics:

1. :func:`custom_metric` -- wraps an arbitrary Python function.
2. :func:`llm_metric` -- uses an LLM-as-judge with a custom prompt template.

Both decorators register the metric with the evaluation engine's global
registry so it can be referenced by name in ``evaluate()`` calls.

Examples
--------
::

    from chatbot_evals.metrics.custom import custom_metric, llm_metric
    from chatbot_evals.types import Conversation

    @custom_metric(name="brand_voice", description="Checks brand voice consistency")
    async def brand_voice(conversation: Conversation) -> float:
        # Custom scoring logic
        return 0.85

    @llm_metric(
        name="helpfulness",
        prompt="Rate how helpful this response is on a scale of 0-1: {response}",
        judge_model="gpt-4o",
    )
    def helpfulness():
        pass  # LLM handles the evaluation

    # Both can now be used by name:
    # report = await evaluate(conversations, metrics=["faithfulness", "brand_voice", "helpfulness"])
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

import structlog

from chatbot_evals.types import Conversation, Message

logger = structlog.get_logger(__name__)


def custom_metric(
    name: str,
    description: str = "",
    version: str = "1.0.0",
) -> Callable:
    """Decorator that registers a Python function as a custom metric.

    The decorated function receives a :class:`~chatbot_evals.types.Conversation`
    and must return a ``float`` score between 0 and 1.  It may be sync or async.

    Args:
        name: Unique metric name.
        description: Human-readable description.
        version: Metric version string.

    Returns:
        A decorator that registers the function.

    Example::

        @custom_metric(name="brand_voice", description="Checks brand voice")
        async def brand_voice(conversation: Conversation) -> float:
            return 0.85
    """

    def decorator(fn: Callable) -> Callable:
        from evalplatform.eval_engine.metrics.base import (
            BaseMetric,
            EvalContext,
            MetricCategory,
            MetricResult,
        )
        from evalplatform.eval_engine.registry import metric_registry

        class _SDKCustomMetric(BaseMetric):
            """Dynamically created metric wrapping an SDK user function."""

            # Class-level attributes required by BaseMetric / registry
            name: str = name  # type: ignore[assignment]
            description: str = description or f"Custom metric: {name}"  # type: ignore[assignment]
            version: str = version  # type: ignore[assignment]
            category: MetricCategory = MetricCategory.CUSTOM

            def __init__(self) -> None:
                self._fn = fn

            async def evaluate(self, conversation: EvalContext) -> MetricResult:
                """Convert EvalContext -> SDK Conversation, call user fn, wrap result."""
                sdk_conv = _eval_context_to_conversation(conversation)
                try:
                    if asyncio.iscoroutinefunction(self._fn):
                        score = await self._fn(sdk_conv)
                    else:
                        score = self._fn(sdk_conv)
                    score = float(score)
                    score = max(0.0, min(1.0, score))
                except Exception as exc:
                    logger.error("custom_metric_error", metric=name, error=str(exc))
                    return self._build_result(
                        score=0.0,
                        explanation=f"Custom metric '{name}' raised: {exc}",
                        details={"error": str(exc)},
                    )
                return self._build_result(score=score)

        # Give the dynamic class a unique name for the registry
        _SDKCustomMetric.__name__ = f"SDKCustom_{name}"
        _SDKCustomMetric.__qualname__ = f"SDKCustom_{name}"

        # Assign class-level attributes (overriding the class body for safety)
        _SDKCustomMetric.name = name  # type: ignore[assignment]
        _SDKCustomMetric.description = description or f"Custom metric: {name}"  # type: ignore[assignment]
        _SDKCustomMetric.version = version  # type: ignore[assignment]

        # Register only if not already registered
        if name not in metric_registry:
            metric_registry.register(_SDKCustomMetric)
            logger.debug("sdk_custom_metric_registered", name=name)
        else:
            logger.debug("sdk_custom_metric_already_registered", name=name)

        # Return the original function unchanged so it can still be called directly
        fn._metric_name = name  # type: ignore[attr-defined]
        return fn

    return decorator


def llm_metric(
    name: str,
    prompt: str,
    description: str = "",
    judge_model: str = "gpt-4o",
    temperature: float = 0.0,
    version: str = "1.0.0",
) -> Callable:
    """Decorator that registers an LLM-as-judge custom metric.

    The prompt template may contain these placeholders:
    - ``{question}`` -- the last user message
    - ``{response}`` -- the last assistant message
    - ``{context}`` -- retrieved context (joined)
    - ``{system_prompt}`` -- the chatbot's system prompt
    - ``{ground_truth}`` -- the expected answer

    The decorated function body is ignored (the LLM does the evaluation).

    Args:
        name: Unique metric name.
        prompt: Prompt template string with placeholders.
        description: Human-readable description.
        judge_model: LLM model to use as judge.
        temperature: Sampling temperature.
        version: Metric version string.

    Returns:
        A decorator that registers the LLM metric.

    Example::

        @llm_metric(
            name="helpfulness",
            prompt="Rate how helpful this response is on 0-1: {response}",
        )
        def helpfulness():
            pass
    """

    def decorator(fn: Callable) -> Callable:
        from evalplatform.eval_engine.metrics.custom import register_llm_custom_metric

        # register_llm_custom_metric creates and registers the metric
        if name not in _get_registry():
            register_llm_custom_metric(
                name=name,
                description=description or f"LLM metric: {name}",
                custom_instructions=prompt,
                model=judge_model,
                temperature=temperature,
                version=version,
            )
            logger.debug("sdk_llm_metric_registered", name=name)
        else:
            logger.debug("sdk_llm_metric_already_registered", name=name)

        fn._metric_name = name  # type: ignore[attr-defined]
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _eval_context_to_conversation(ctx: Any) -> Conversation:
    """Convert an internal EvalContext to an SDK Conversation."""
    messages = [
        Message(
            role=turn.role,
            content=turn.content,
            metadata=turn.metadata,
            timestamp=turn.timestamp,
        )
        for turn in ctx.conversation
    ]
    context: str | list[str] | None = None
    if ctx.retrieved_context:
        context = ctx.retrieved_context if len(ctx.retrieved_context) > 1 else ctx.retrieved_context[0]

    return Conversation(
        messages=messages,
        id=ctx.metadata.get("conversation_id", ""),
        ground_truth=ctx.ground_truth,
        context=context,
        system_prompt=ctx.system_prompt,
        metadata=ctx.metadata,
    )


def _get_registry() -> Any:
    """Lazy import to avoid circular imports."""
    from evalplatform.eval_engine.registry import metric_registry
    return metric_registry
