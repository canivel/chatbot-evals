"""Main evaluation orchestrator.

The :class:`EvalEngine` is the primary entry point for running evaluations.
It supports batch evaluation with parallel metric computation and progress
tracking.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, Field

import structlog

from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class EvalConfig(BaseModel):
    """Configuration for an evaluation run."""

    metric_names: list[str] = Field(
        default_factory=list,
        description="Names of metrics to run. Empty means run all registered metrics.",
    )
    max_concurrency: int = Field(
        default=10, ge=1, description="Max concurrent metric evaluations"
    )
    fail_on_error: bool = Field(
        default=False,
        description="If True, raise on the first metric error instead of recording it.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary run-level metadata"
    )


class ConversationResult(BaseModel):
    """All metric results for a single conversation."""

    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metric_results: list[MetricResult] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    aggregate_score: float | None = Field(
        default=None, description="Mean score across all metrics"
    )


class EvalRun(BaseModel):
    """Complete results of an evaluation run."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversations_evaluated: int = Field(default=0)
    conversation_results: list[ConversationResult] = Field(default_factory=list)
    aggregate_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Per-metric aggregate scores across all conversations",
    )
    overall_score: float | None = Field(
        default=None, description="Grand mean of all metric scores"
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = Field(default=None)
    config: EvalConfig = Field(default_factory=EvalConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Type for optional progress callback
ProgressCallback = Callable[[int, int, str], None]  # (current, total, message)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class EvalEngine:
    """Orchestrates evaluation of chatbot conversations against metrics.

    Usage::

        engine = EvalEngine()
        run = await engine.run_eval(
            conversations=[ctx1, ctx2],
            config=EvalConfig(metric_names=["faithfulness", "relevance"]),
        )
        print(run.aggregate_scores)
    """

    def __init__(self) -> None:
        self._registry = metric_registry

    async def run_eval(
        self,
        conversations: list[EvalContext],
        config: EvalConfig | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> EvalRun:
        """Run a full evaluation across conversations and metrics.

        Args:
            conversations: List of conversation contexts to evaluate.
            config: Evaluation configuration.  Uses defaults if not supplied.
            progress_callback: Optional ``(current, total, message)`` callback
                invoked after each conversation is evaluated.

        Returns:
            An ``EvalRun`` containing all results and aggregate scores.
        """
        config = config or EvalConfig()
        run = EvalRun(config=config)

        metrics = self._resolve_metrics(config.metric_names)
        if not metrics:
            logger.warning("eval_engine_no_metrics")
            run.completed_at = datetime.now(timezone.utc)
            return run

        total = len(conversations)
        logger.info(
            "eval_run_started",
            run_id=run.id,
            conversations=total,
            metrics=[m.name for m in metrics],
        )

        semaphore = asyncio.Semaphore(config.max_concurrency)

        for idx, ctx in enumerate(conversations):
            conv_result = await self._evaluate_conversation(
                ctx, metrics, semaphore, config.fail_on_error
            )
            run.conversation_results.append(conv_result)

            if progress_callback:
                progress_callback(idx + 1, total, f"Evaluated conversation {idx + 1}/{total}")

        run.conversations_evaluated = total
        run.aggregate_scores = self._compute_aggregates(run.conversation_results, metrics)
        all_scores = [s for s in run.aggregate_scores.values() if s is not None]
        run.overall_score = (
            sum(all_scores) / len(all_scores) if all_scores else None
        )
        run.completed_at = datetime.now(timezone.utc)

        logger.info(
            "eval_run_completed",
            run_id=run.id,
            overall_score=run.overall_score,
            duration_seconds=(
                (run.completed_at - run.started_at).total_seconds()
            ),
        )

        return run

    # -- Internals -----------------------------------------------------------

    def _resolve_metrics(self, metric_names: list[str]) -> list[BaseMetric]:
        """Resolve metric names to instances, or return all if list is empty."""
        if not metric_names:
            all_info = self._registry.list_metrics()
            return [self._registry.get_metric(m["name"]) for m in all_info]

        metrics: list[BaseMetric] = []
        for name in metric_names:
            try:
                metrics.append(self._registry.get_metric(name))
            except KeyError:
                logger.error("metric_not_found", name=name)
                raise
        return metrics

    async def _evaluate_conversation(
        self,
        ctx: EvalContext,
        metrics: list[BaseMetric],
        semaphore: asyncio.Semaphore,
        fail_on_error: bool,
    ) -> ConversationResult:
        """Run all metrics for a single conversation, with concurrency control."""
        conv_result = ConversationResult(
            conversation_id=ctx.metadata.get("conversation_id", str(uuid.uuid4()))
        )

        async def _run_metric(metric: BaseMetric) -> MetricResult | None:
            async with semaphore:
                try:
                    return await metric.evaluate(ctx)
                except Exception as exc:
                    if fail_on_error:
                        raise
                    logger.error(
                        "metric_evaluation_error",
                        metric=metric.name,
                        error=str(exc),
                    )
                    conv_result.errors.append(
                        {"metric": metric.name, "error": str(exc)}
                    )
                    return None

        tasks = [_run_metric(m) for m in metrics]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for result in results:
            if result is not None:
                conv_result.metric_results.append(result)

        # Compute per-conversation aggregate
        scores = [r.score for r in conv_result.metric_results]
        conv_result.aggregate_score = (
            sum(scores) / len(scores) if scores else None
        )

        return conv_result

    @staticmethod
    def _compute_aggregates(
        conversation_results: list[ConversationResult],
        metrics: list[BaseMetric],
    ) -> dict[str, float]:
        """Compute per-metric aggregate scores across all conversations."""
        aggregates: dict[str, list[float]] = {m.name: [] for m in metrics}

        for conv in conversation_results:
            for result in conv.metric_results:
                if result.metric_name in aggregates:
                    aggregates[result.metric_name].append(result.score)

        return {
            name: (sum(scores) / len(scores) if scores else 0.0)
            for name, scores in aggregates.items()
        }
