"""End-to-end evaluation pipeline.

Provides a staged pipeline: ingest -> preprocess -> evaluate -> aggregate ->
report.  Each stage is independently configurable and skippable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Callable, Awaitable

from pydantic import BaseModel, Field

import structlog

from evalplatform.eval_engine.engine import (
    ConversationResult,
    EvalConfig,
    EvalEngine,
    EvalRun,
)
from evalplatform.eval_engine.metrics.base import EvalContext, MetricResult

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


class PipelineStage(str, Enum):
    """Pipeline stages that can be individually enabled or disabled."""

    INGEST = "ingest"
    PREPROCESS = "preprocess"
    EVALUATE = "evaluate"
    AGGREGATE = "aggregate"
    REPORT = "report"


class PipelineConfig(BaseModel):
    """Configuration for an evaluation pipeline."""

    eval_config: EvalConfig = Field(default_factory=EvalConfig)
    skip_stages: list[PipelineStage] = Field(
        default_factory=list, description="Stages to skip"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineEvent(BaseModel):
    """Event emitted during pipeline execution for streaming consumers."""

    stage: str
    event_type: str  # "started", "progress", "completed", "error"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class PipelineResult(BaseModel):
    """Final output of the evaluation pipeline."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    eval_run: EvalRun | None = Field(default=None)
    report: dict[str, Any] = Field(default_factory=dict)
    stages_executed: list[str] = Field(default_factory=list)
    stages_skipped: list[str] = Field(default_factory=list)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = Field(default=None)


# Type aliases for custom stage hooks
IngestHook = Callable[[list[dict[str, Any]]], Awaitable[list[EvalContext]]]
PreprocessHook = Callable[[list[EvalContext]], Awaitable[list[EvalContext]]]
ReportHook = Callable[[EvalRun], Awaitable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class EvalPipeline:
    """Configurable end-to-end evaluation pipeline.

    The pipeline runs through five stages:

    1. **Ingest** -- convert raw data into ``EvalContext`` objects.
    2. **Preprocess** -- clean, filter, or augment conversations.
    3. **Evaluate** -- run metrics via :class:`EvalEngine`.
    4. **Aggregate** -- compute summary statistics (handled by engine).
    5. **Report** -- produce a structured report from results.

    Each stage can be skipped via :attr:`PipelineConfig.skip_stages` and
    hooks allow injecting custom logic for ingest, preprocess, and report
    stages.

    Usage::

        pipeline = EvalPipeline()
        result = await pipeline.run(conversations, config)

    Or for streaming::

        async for event in pipeline.run_streaming(conversations, config):
            print(event)
    """

    def __init__(
        self,
        ingest_hook: IngestHook | None = None,
        preprocess_hook: PreprocessHook | None = None,
        report_hook: ReportHook | None = None,
    ) -> None:
        self._engine = EvalEngine()
        self._ingest_hook = ingest_hook
        self._preprocess_hook = preprocess_hook
        self._report_hook = report_hook

    # -- Synchronous (full) run ----------------------------------------------

    async def run(
        self,
        conversations: list[EvalContext] | list[dict[str, Any]],
        config: PipelineConfig | None = None,
    ) -> PipelineResult:
        """Run the full pipeline and return results.

        Args:
            conversations: Either pre-built ``EvalContext`` objects or raw
                dicts that the ingest hook will convert.
            config: Pipeline configuration.

        Returns:
            A ``PipelineResult`` with the evaluation results and report.
        """
        config = config or PipelineConfig()
        result = PipelineResult()
        skipped = {s.value for s in config.skip_stages}

        # -- Ingest --
        contexts: list[EvalContext]
        if PipelineStage.INGEST.value not in skipped:
            contexts = await self._ingest(conversations)
            result.stages_executed.append(PipelineStage.INGEST.value)
        else:
            contexts = self._ensure_eval_contexts(conversations)
            result.stages_skipped.append(PipelineStage.INGEST.value)

        # -- Preprocess --
        if PipelineStage.PREPROCESS.value not in skipped:
            contexts = await self._preprocess(contexts)
            result.stages_executed.append(PipelineStage.PREPROCESS.value)
        else:
            result.stages_skipped.append(PipelineStage.PREPROCESS.value)

        # -- Evaluate --
        eval_run: EvalRun | None = None
        if PipelineStage.EVALUATE.value not in skipped:
            eval_run = await self._engine.run_eval(contexts, config.eval_config)
            result.eval_run = eval_run
            result.stages_executed.append(PipelineStage.EVALUATE.value)
        else:
            result.stages_skipped.append(PipelineStage.EVALUATE.value)

        # -- Aggregate (handled inside engine, but mark stage) --
        if PipelineStage.AGGREGATE.value not in skipped and eval_run:
            result.stages_executed.append(PipelineStage.AGGREGATE.value)
        else:
            result.stages_skipped.append(PipelineStage.AGGREGATE.value)

        # -- Report --
        if PipelineStage.REPORT.value not in skipped and eval_run:
            result.report = await self._report(eval_run)
            result.stages_executed.append(PipelineStage.REPORT.value)
        else:
            result.stages_skipped.append(PipelineStage.REPORT.value)

        result.completed_at = datetime.now(timezone.utc)
        logger.info(
            "pipeline_completed",
            pipeline_id=result.id,
            stages_executed=result.stages_executed,
        )
        return result

    # -- Streaming run -------------------------------------------------------

    async def run_streaming(
        self,
        conversations: list[EvalContext] | list[dict[str, Any]],
        config: PipelineConfig | None = None,
    ) -> AsyncIterator[PipelineEvent]:
        """Run the pipeline and yield events as stages progress.

        Yields:
            ``PipelineEvent`` objects for each stage transition and progress
            update.
        """
        config = config or PipelineConfig()
        skipped = {s.value for s in config.skip_stages}

        # -- Ingest --
        if PipelineStage.INGEST.value not in skipped:
            yield PipelineEvent(
                stage="ingest", event_type="started", message="Starting ingest stage"
            )
            contexts = await self._ingest(conversations)
            yield PipelineEvent(
                stage="ingest",
                event_type="completed",
                message=f"Ingested {len(contexts)} conversations",
                data={"count": len(contexts)},
            )
        else:
            contexts = self._ensure_eval_contexts(conversations)
            yield PipelineEvent(
                stage="ingest", event_type="skipped", message="Ingest stage skipped"
            )

        # -- Preprocess --
        if PipelineStage.PREPROCESS.value not in skipped:
            yield PipelineEvent(
                stage="preprocess", event_type="started", message="Starting preprocess stage"
            )
            contexts = await self._preprocess(contexts)
            yield PipelineEvent(
                stage="preprocess",
                event_type="completed",
                message=f"Preprocessed {len(contexts)} conversations",
            )
        else:
            yield PipelineEvent(
                stage="preprocess", event_type="skipped", message="Preprocess stage skipped"
            )

        # -- Evaluate --
        eval_run: EvalRun | None = None
        if PipelineStage.EVALUATE.value not in skipped:
            yield PipelineEvent(
                stage="evaluate", event_type="started", message="Starting evaluation"
            )

            def _progress(current: int, total: int, msg: str) -> None:
                # Note: we cannot yield from a sync callback; events are
                # emitted after the engine completes.
                pass

            eval_run = await self._engine.run_eval(
                contexts, config.eval_config, progress_callback=_progress
            )
            yield PipelineEvent(
                stage="evaluate",
                event_type="completed",
                message=f"Evaluated {eval_run.conversations_evaluated} conversations",
                data={
                    "overall_score": eval_run.overall_score,
                    "aggregate_scores": eval_run.aggregate_scores,
                },
            )
        else:
            yield PipelineEvent(
                stage="evaluate", event_type="skipped", message="Evaluate stage skipped"
            )

        # -- Aggregate --
        if PipelineStage.AGGREGATE.value not in skipped and eval_run:
            yield PipelineEvent(
                stage="aggregate",
                event_type="completed",
                message="Aggregation complete",
                data={"aggregate_scores": eval_run.aggregate_scores},
            )
        else:
            yield PipelineEvent(
                stage="aggregate", event_type="skipped", message="Aggregate stage skipped"
            )

        # -- Report --
        if PipelineStage.REPORT.value not in skipped and eval_run:
            yield PipelineEvent(
                stage="report", event_type="started", message="Generating report"
            )
            report = await self._report(eval_run)
            yield PipelineEvent(
                stage="report",
                event_type="completed",
                message="Report generated",
                data={"report": report},
            )
        else:
            yield PipelineEvent(
                stage="report", event_type="skipped", message="Report stage skipped"
            )

    # -- Stage implementations -----------------------------------------------

    async def _ingest(
        self, raw_data: list[EvalContext] | list[dict[str, Any]]
    ) -> list[EvalContext]:
        """Convert raw data to EvalContext objects."""
        if self._ingest_hook:
            # raw_data might be dicts; let the hook handle it
            return await self._ingest_hook(raw_data)  # type: ignore[arg-type]

        return self._ensure_eval_contexts(raw_data)

    async def _preprocess(self, contexts: list[EvalContext]) -> list[EvalContext]:
        """Apply preprocessing transformations."""
        if self._preprocess_hook:
            return await self._preprocess_hook(contexts)

        # Default: filter out empty conversations
        filtered = [ctx for ctx in contexts if ctx.conversation]
        if len(filtered) < len(contexts):
            logger.info(
                "pipeline_preprocess_filtered",
                removed=len(contexts) - len(filtered),
            )
        return filtered

    async def _report(self, eval_run: EvalRun) -> dict[str, Any]:
        """Generate a report from the eval run."""
        if self._report_hook:
            return await self._report_hook(eval_run)

        # Default report structure
        return self._default_report(eval_run)

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _ensure_eval_contexts(
        data: list[EvalContext] | list[dict[str, Any]],
    ) -> list[EvalContext]:
        """Coerce a list of dicts or EvalContext objects to EvalContext."""
        contexts: list[EvalContext] = []
        for item in data:
            if isinstance(item, EvalContext):
                contexts.append(item)
            elif isinstance(item, dict):
                contexts.append(EvalContext(**item))
            else:
                raise TypeError(
                    f"Expected EvalContext or dict, got {type(item).__name__}"
                )
        return contexts

    @staticmethod
    def _default_report(eval_run: EvalRun) -> dict[str, Any]:
        """Build a default summary report."""
        per_metric: dict[str, dict[str, Any]] = {}
        for name, score in eval_run.aggregate_scores.items():
            per_metric[name] = {
                "aggregate_score": round(score, 4),
            }

        # Collect per-conversation summaries
        conversation_summaries: list[dict[str, Any]] = []
        for conv in eval_run.conversation_results:
            summary: dict[str, Any] = {
                "conversation_id": conv.conversation_id,
                "aggregate_score": (
                    round(conv.aggregate_score, 4)
                    if conv.aggregate_score is not None
                    else None
                ),
                "metric_scores": {
                    r.metric_name: round(r.score, 4) for r in conv.metric_results
                },
                "errors": conv.errors,
            }
            conversation_summaries.append(summary)

        return {
            "run_id": eval_run.id,
            "conversations_evaluated": eval_run.conversations_evaluated,
            "overall_score": (
                round(eval_run.overall_score, 4)
                if eval_run.overall_score is not None
                else None
            ),
            "per_metric": per_metric,
            "conversations": conversation_summaries,
            "started_at": eval_run.started_at.isoformat(),
            "completed_at": (
                eval_run.completed_at.isoformat()
                if eval_run.completed_at
                else None
            ),
        }
