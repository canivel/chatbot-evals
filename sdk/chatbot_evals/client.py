"""Main SDK client for chatbot evaluation.

The :class:`ChatbotEvals` client is the primary object-oriented interface for
running evaluations.  It wraps the internal evaluation engine, converts
between SDK and engine types, and provides both async and sync APIs.

Example::

    import chatbot_evals as ce

    client = ce.ChatbotEvals(judge_model="gpt-4o")

    conversation = ce.Conversation(
        messages=[
            ce.Message(role="user", content="What is your return policy?"),
            ce.Message(role="assistant", content="We accept returns within 30 days."),
        ],
        context="Return policy: 30 day returns with receipt.",
    )

    result = client.evaluate_sync(conversation, metrics=["faithfulness", "relevance"])
    print(result.overall_score)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import structlog

from chatbot_evals.callbacks import BaseCallback
from chatbot_evals.config import Config, get_config
from chatbot_evals.types import (
    Conversation,
    Dataset,
    EvalReport,
    EvalResult,
    Message,
    MetricDetail,
)

logger = structlog.get_logger(__name__)


class ChatbotEvals:
    """Main SDK client for chatbot evaluation.

    Provides methods to evaluate individual conversations or entire datasets
    against a configurable set of quality metrics.

    Args:
        api_key: Platform API key (falls back to env / global config).
        api_url: Platform API URL (falls back to env / global config).
        judge_model: LLM model to use as the evaluation judge.
        project: Optional project name for grouping runs.

    Example::

        ce = ChatbotEvals(judge_model="gpt-4o")

        # Evaluate a single conversation
        result = await ce.evaluate(conversation)

        # Evaluate a dataset
        report = await ce.evaluate_dataset(dataset, metrics=["faithfulness"])

        # Full run with tracking
        report = await ce.run(
            dataset=dataset,
            metrics=["faithfulness", "relevance", "toxicity"],
            judge_model="claude-sonnet-4-20250514",
        )
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        judge_model: str | None = None,
        project: str | None = None,
    ) -> None:
        cfg = get_config()
        self._api_key = api_key or cfg.api_key
        self._api_url = api_url or cfg.api_url
        self._judge_model = judge_model or cfg.judge_model
        self._project = project
        self._config = cfg

        # Ensure built-in metrics are registered on first use
        _ensure_metrics_loaded()

    # -- Public async API ----------------------------------------------------

    async def evaluate(
        self,
        conversation: Conversation,
        metrics: list[str] | None = None,
    ) -> EvalResult:
        """Evaluate a single conversation.

        Args:
            conversation: The conversation to evaluate.
            metrics: List of metric names to compute.  If ``None``, uses
                the SDK default metrics (or all registered metrics).

        Returns:
            An :class:`~chatbot_evals.types.EvalResult` for this conversation.

        Example::

            result = await client.evaluate(conversation, metrics=["faithfulness"])
            print(result.scores)
        """
        from evalplatform.eval_engine.engine import EvalConfig, EvalEngine

        engine = EvalEngine()
        eval_ctx = _conversation_to_eval_context(conversation)
        metric_names = metrics or self._config.default_metrics or []

        config = EvalConfig(
            metric_names=metric_names,
            max_concurrency=self._config.max_concurrency,
        )

        run = await engine.run_eval(conversations=[eval_ctx], config=config)

        if not run.conversation_results:
            return EvalResult(
                conversation_id=conversation.id,
                scores={},
                details={},
                overall_score=0.0,
                flags=[],
            )

        return _conversation_result_to_eval_result(
            run.conversation_results[0],
            conversation_id=conversation.id,
        )

    async def evaluate_dataset(
        self,
        dataset: Dataset,
        metrics: list[str] | None = None,
        callbacks: list[BaseCallback] | None = None,
    ) -> EvalReport:
        """Evaluate an entire dataset of conversations.

        Args:
            dataset: The dataset to evaluate.
            metrics: Metric names to compute.
            callbacks: Optional progress callbacks.

        Returns:
            An :class:`~chatbot_evals.types.EvalReport` with all results.

        Example::

            report = await client.evaluate_dataset(
                dataset, metrics=["faithfulness", "relevance"]
            )
            print(report.metric_averages)
        """
        return await self.run(
            dataset=dataset,
            metrics=metrics,
            callbacks=callbacks,
        )

    async def run(
        self,
        dataset: Dataset | list[Conversation],
        metrics: list[str] | None = None,
        judge_model: str | None = None,
        name: str | None = None,
        callbacks: list[BaseCallback] | None = None,
    ) -> EvalReport:
        """Full evaluation run with tracking and callbacks.

        This is the most feature-complete evaluation method.  It supports
        progress callbacks, named runs, and judge model overrides.

        Args:
            dataset: A :class:`Dataset` or list of :class:`Conversation`.
            metrics: Metric names to compute.
            judge_model: Override the judge model for this run.
            name: Human-readable run name.
            callbacks: Progress callbacks.

        Returns:
            An :class:`~chatbot_evals.types.EvalReport`.

        Example::

            report = await client.run(
                dataset=dataset,
                metrics=["faithfulness", "relevance", "toxicity"],
                judge_model="claude-sonnet-4-20250514",
                name="v2-regression-test",
            )
        """
        from evalplatform.eval_engine.engine import EvalConfig, EvalEngine

        # Normalise input
        if isinstance(dataset, list):
            conversations = dataset
        else:
            conversations = dataset.conversations

        metric_names = metrics or self._config.default_metrics or []
        cbs = callbacks or []

        # Notify callbacks
        for cb in cbs:
            try:
                cb.on_eval_start(len(conversations), metric_names)
            except Exception as exc:
                logger.warning("callback_error", callback=type(cb).__name__, error=str(exc))

        # Build engine config
        config = EvalConfig(
            metric_names=metric_names,
            max_concurrency=self._config.max_concurrency,
        )

        # Convert conversations
        eval_contexts = [_conversation_to_eval_context(c) for c in conversations]

        # Progress callback adapter
        results: list[EvalResult] = []

        def progress_adapter(current: int, total: int, message: str) -> None:
            if not cbs or current < 1:
                return
            # Build the EvalResult for the latest conversation
            from evalplatform.eval_engine.engine import EvalEngine as _EE
            # We reconstruct the result from the run later; fire callbacks eagerly
            pass

        engine = EvalEngine()
        run = await engine.run_eval(
            conversations=eval_contexts,
            config=config,
        )

        # Convert all results
        for idx, conv_result in enumerate(run.conversation_results):
            conv_id = conversations[idx].id if idx < len(conversations) else str(uuid.uuid4())
            eval_result = _conversation_result_to_eval_result(conv_result, conversation_id=conv_id)
            results.append(eval_result)

            # Fire per-conversation callbacks
            for cb in cbs:
                try:
                    cb.on_conversation_evaluated(idx + 1, len(conversations), eval_result)
                    for metric_name, score in eval_result.scores.items():
                        cb.on_metric_computed(metric_name, score, conv_id)
                except Exception as exc:
                    logger.warning("callback_error", callback=type(cb).__name__, error=str(exc))

        # Build the report
        report = _build_report(results, run, name=name)

        # Notify callbacks of completion
        for cb in cbs:
            try:
                cb.on_eval_complete(report)
            except Exception as exc:
                logger.warning("callback_error", callback=type(cb).__name__, error=str(exc))

        return report

    # -- Sync wrappers -------------------------------------------------------

    def evaluate_sync(
        self,
        conversation: Conversation,
        metrics: list[str] | None = None,
    ) -> EvalResult:
        """Synchronous wrapper for :meth:`evaluate`.

        Creates or reuses an event loop to run the async method.

        Example::

            result = client.evaluate_sync(conversation, metrics=["faithfulness"])
        """
        return _run_sync(self.evaluate(conversation, metrics=metrics))

    def run_sync(
        self,
        dataset: Dataset | list[Conversation],
        **kwargs: Any,
    ) -> EvalReport:
        """Synchronous wrapper for :meth:`run`.

        Example::

            report = client.run_sync(dataset, metrics=["faithfulness"])
        """
        return _run_sync(self.run(dataset=dataset, **kwargs))

    # -- Metric introspection ------------------------------------------------

    async def list_metrics(self) -> list[dict[str, Any]]:
        """List all available metrics.

        Returns:
            A list of dicts with ``name``, ``description``, ``version``,
            and ``category`` for each registered metric.

        Example::

            metrics = await client.list_metrics()
            for m in metrics:
                print(m["name"], m["description"])
        """
        from evalplatform.eval_engine.registry import metric_registry
        _ensure_metrics_loaded()
        return metric_registry.list_metrics()

    async def get_metric(self, name: str) -> dict[str, Any]:
        """Get information about a specific metric.

        Args:
            name: The metric name.

        Returns:
            A dict with ``name``, ``description``, ``version``, and ``category``.

        Raises:
            KeyError: If no metric with that name is registered.

        Example::

            info = await client.get_metric("faithfulness")
            print(info["description"])
        """
        from evalplatform.eval_engine.registry import metric_registry
        _ensure_metrics_loaded()
        metric = metric_registry.get_metric(name)
        return {
            "name": metric.name,
            "description": metric.description,
            "version": metric.version,
            "category": metric.category.value if hasattr(metric.category, "value") else str(metric.category),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_metrics_loaded = False


def _ensure_metrics_loaded() -> None:
    """Import the metrics package once to trigger metric registration."""
    global _metrics_loaded
    if not _metrics_loaded:
        try:
            import evalplatform.eval_engine.metrics  # noqa: F401 -- triggers registration
            _metrics_loaded = True
        except Exception as exc:
            logger.warning("metrics_import_failed", error=str(exc))


def _conversation_to_eval_context(conversation: Conversation) -> Any:
    """Convert an SDK Conversation to an internal EvalContext."""
    from evalplatform.eval_engine.metrics.base import ConversationTurn, EvalContext

    turns = [
        ConversationTurn(
            role=msg.role,
            content=msg.content,
            metadata=msg.metadata,
            timestamp=msg.timestamp,
        )
        for msg in conversation.messages
    ]

    # Normalise context to list[str]
    retrieved_context: list[str] = []
    if isinstance(conversation.context, str):
        retrieved_context = [conversation.context]
    elif isinstance(conversation.context, list):
        retrieved_context = conversation.context

    return EvalContext(
        conversation=turns,
        ground_truth=conversation.ground_truth,
        retrieved_context=retrieved_context,
        system_prompt=conversation.system_prompt,
        metadata={
            "conversation_id": conversation.id,
            **conversation.metadata,
        },
    )


def _conversation_result_to_eval_result(
    conv_result: Any,
    conversation_id: str,
    pass_threshold: float = 0.7,
) -> EvalResult:
    """Convert an internal ConversationResult to an SDK EvalResult."""
    scores: dict[str, float] = {}
    details: dict[str, MetricDetail] = {}

    for metric_result in conv_result.metric_results:
        scores[metric_result.metric_name] = metric_result.score
        details[metric_result.metric_name] = MetricDetail(
            score=metric_result.score,
            explanation=metric_result.explanation,
            raw_details=metric_result.details,
        )

    # Generate flags for low-scoring metrics
    flags = [
        f"low_{name}" for name, score in scores.items() if score < pass_threshold
    ]

    overall = conv_result.aggregate_score if conv_result.aggregate_score is not None else 0.0

    return EvalResult(
        conversation_id=conversation_id,
        scores=scores,
        details=details,
        overall_score=overall,
        flags=flags,
    )


def _build_report(
    results: list[EvalResult],
    eval_run: Any,
    name: str | None = None,
) -> EvalReport:
    """Build an SDK EvalReport from a list of EvalResults and engine run."""
    from evalplatform.reports.generator import ReportGenerator

    # Flatten results into the format ReportGenerator expects
    flat_results: list[dict[str, Any]] = []
    for result in results:
        for metric_name, score in result.scores.items():
            explanation = ""
            if metric_name in result.details:
                explanation = result.details[metric_name].explanation
            flat_results.append({
                "conversation_id": result.conversation_id,
                "metric_name": metric_name,
                "score": score,
                "explanation": explanation,
            })

    generator = ReportGenerator()
    internal_report = generator.generate_eval_report(
        eval_run_id=eval_run.id,
        results=flat_results,
    )

    # Build summary text
    n = len(results)
    avg_overall = sum(r.overall_score for r in results) / max(n, 1)
    summary_parts = [
        f"Evaluated {n} conversation{'s' if n != 1 else ''}.",
        f"Overall average score: {avg_overall:.3f}.",
    ]
    if name:
        summary_parts.insert(0, f"Run: {name}.")
    if eval_run.aggregate_scores:
        best = max(eval_run.aggregate_scores, key=eval_run.aggregate_scores.get)  # type: ignore[arg-type]
        worst = min(eval_run.aggregate_scores, key=eval_run.aggregate_scores.get)  # type: ignore[arg-type]
        summary_parts.append(
            f"Best metric: {best} ({eval_run.aggregate_scores[best]:.3f}). "
            f"Worst metric: {worst} ({eval_run.aggregate_scores[worst]:.3f})."
        )

    return EvalReport(
        results=results,
        summary=" ".join(summary_parts),
        metric_averages=eval_run.aggregate_scores,
        recommendations=internal_report.recommendations,
    )


def _run_sync(coro: Any) -> Any:
    """Run a coroutine synchronously, handling existing event loops gracefully."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We are inside an already-running loop (e.g. Jupyter).
        # Use nest_asyncio if available, otherwise create a new thread.
        try:
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        except ImportError:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
    else:
        return asyncio.run(coro)
