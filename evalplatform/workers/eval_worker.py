"""Celery worker for async eval execution."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger()

# Celery app will be initialized when Redis is available
# For now, provide the task functions that can work standalone

async def run_eval_task(
    eval_run_id: str,
    conversation_ids: list[str],
    metric_names: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Execute an evaluation run asynchronously.

    This function can be called directly or wrapped in a Celery task.

    Args:
        eval_run_id: Unique identifier for this eval run.
        conversation_ids: List of conversation IDs to evaluate.
        metric_names: List of metric names to compute.
        config: Eval configuration (judge model, batch size, etc.).

    Returns:
        Dict with eval_run_id, status, results count, and errors.
    """
    from evalplatform.eval_engine.engine import EvalEngine, EvalConfig
    from evalplatform.eval_engine.registry import MetricRegistry

    logger.info(
        "eval_worker_started",
        eval_run_id=eval_run_id,
        conversations=len(conversation_ids),
        metrics=metric_names,
    )

    try:
        registry = MetricRegistry()
        engine = EvalEngine(registry=registry)

        eval_config = EvalConfig(
            metrics=metric_names,
            judge_model=config.get("judge_model", "gpt-4o-mini"),
            batch_size=config.get("batch_size", 10),
            max_concurrent=config.get("max_concurrent", 5),
        )

        # Run evaluation
        results = await engine.run_eval(
            conversation_ids=conversation_ids,
            config=eval_config,
        )

        logger.info(
            "eval_worker_completed",
            eval_run_id=eval_run_id,
            results_count=len(results),
        )

        return {
            "eval_run_id": eval_run_id,
            "status": "completed",
            "results_count": len(results),
            "errors": [],
        }

    except Exception as e:
        logger.error("eval_worker_failed", eval_run_id=eval_run_id, error=str(e))
        return {
            "eval_run_id": eval_run_id,
            "status": "failed",
            "results_count": 0,
            "errors": [str(e)],
        }


async def run_single_metric_task(
    conversation_data: dict[str, Any],
    metric_name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run a single metric on a single conversation."""
    from evalplatform.eval_engine.registry import MetricRegistry
    from evalplatform.eval_engine.metrics.base import EvalContext, ConversationTurn

    registry = MetricRegistry()
    metric = registry.get_metric(metric_name)
    if not metric:
        return {"error": f"Unknown metric: {metric_name}"}

    turns = [
        ConversationTurn(**turn)
        for turn in conversation_data.get("messages", [])
    ]
    context = EvalContext(
        conversation=turns,
        ground_truth=conversation_data.get("ground_truth"),
        retrieved_context=conversation_data.get("retrieved_context"),
        system_prompt=conversation_data.get("system_prompt"),
        metadata=conversation_data.get("metadata", {}),
    )

    result = await metric.evaluate(context)
    return result.model_dump()
