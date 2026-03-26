"""Evaluation run and result routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from evalplatform.api.deps import get_current_org, get_db
from evalplatform.api.models.eval_result import EvalResult
from evalplatform.api.models.eval_run import EvalRun, EvalRunStatus
from evalplatform.api.models.organization import Organization
from evalplatform.api.schemas.eval import (
    EvalResultListResponse,
    EvalResultResponse,
    EvalRunCreate,
    EvalRunListResponse,
    EvalRunResponse,
    MetricInfo,
    MetricListResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/evals", tags=["evals"])

# ---------------------------------------------------------------------------
# Built-in metric catalogue (static for now; a registry would replace this)
# ---------------------------------------------------------------------------

_AVAILABLE_METRICS: list[MetricInfo] = [
    MetricInfo(
        name="faithfulness",
        description="Measures whether the assistant's response is faithful to provided context",
        category="faithfulness",
        version="1.0.0",
    ),
    MetricInfo(
        name="answer_relevance",
        description="Measures how relevant the assistant's answer is to the user's question",
        category="relevance",
        version="1.0.0",
    ),
    MetricInfo(
        name="context_precision",
        description="Measures precision of retrieved context relative to ground truth",
        category="relevance",
        version="1.0.0",
    ),
    MetricInfo(
        name="context_recall",
        description="Measures recall of retrieved context relative to ground truth",
        category="relevance",
        version="1.0.0",
    ),
    MetricInfo(
        name="harmfulness",
        description="Detects potentially harmful or unsafe content in responses",
        category="safety",
        version="1.0.0",
    ),
    MetricInfo(
        name="coherence",
        description="Evaluates logical coherence and clarity of the response",
        category="quality",
        version="1.0.0",
    ),
    MetricInfo(
        name="response_completeness",
        description="Checks whether the response fully addresses the user's question",
        category="quality",
        version="1.0.0",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_eval_run_or_404(
    eval_run_id: uuid.UUID,
    org: Organization,
    db: AsyncSession,
) -> EvalRun:
    result = await db.execute(
        select(EvalRun).where(
            EvalRun.id == eval_run_id,
            EvalRun.organization_id == org.id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Eval run not found",
        )
    return run


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/metrics",
    response_model=MetricListResponse,
    summary="List available evaluation metrics",
)
async def list_metrics() -> MetricListResponse:
    """Return the catalogue of metrics the platform can evaluate."""
    return MetricListResponse(metrics=_AVAILABLE_METRICS)


@router.get(
    "",
    response_model=EvalRunListResponse,
    summary="List evaluation runs",
)
async def list_eval_runs(
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: EvalRunStatus | None = None,
    skip: int = 0,
    limit: int = 50,
) -> EvalRunListResponse:
    """Return a paginated list of eval runs for the organization."""
    base = select(EvalRun).where(EvalRun.organization_id == org.id)
    if status_filter is not None:
        base = base.where(EvalRun.status == status_filter)

    total_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_result.scalar_one()

    items_result = await db.execute(
        base.order_by(EvalRun.created_at.desc()).offset(skip).limit(limit)
    )
    items = list(items_result.scalars().all())

    return EvalRunListResponse(items=items, total=total)


@router.post(
    "",
    response_model=EvalRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new evaluation run",
)
async def create_eval_run(
    body: EvalRunCreate,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvalRun:
    """Create and enqueue a new evaluation run.

    The run is created with status ``pending``.  In a full deployment a Celery
    worker picks it up and advances the status through ``running`` to
    ``completed`` or ``failed``.
    """
    # Validate requested metrics
    known_names = {m.name for m in _AVAILABLE_METRICS}
    unknown = set(body.metrics) - known_names
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown metrics: {', '.join(sorted(unknown))}",
        )

    run = EvalRun(
        name=body.name,
        organization_id=org.id,
        connector_id=body.connector_id,
        config={
            "metrics": body.metrics,
            "conversation_ids": (
                [str(cid) for cid in body.conversation_ids]
                if body.conversation_ids
                else None
            ),
            **body.config,
        },
        status=EvalRunStatus.PENDING,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)

    # TODO: enqueue Celery eval task
    logger.info("Eval run created", eval_run_id=str(run.id), metrics=body.metrics)
    return run


@router.get(
    "/{eval_run_id}",
    response_model=EvalRunResponse,
    summary="Get an evaluation run by ID",
)
async def get_eval_run(
    eval_run_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvalRun:
    """Return detail for a single eval run."""
    return await _get_eval_run_or_404(eval_run_id, org, db)


@router.get(
    "/{eval_run_id}/results",
    response_model=EvalResultListResponse,
    summary="List results for an evaluation run",
)
async def list_eval_results(
    eval_run_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
    metric_name: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> EvalResultListResponse:
    """Return paginated eval results, optionally filtered by metric."""
    # Validate the run belongs to this org
    await _get_eval_run_or_404(eval_run_id, org, db)

    base = select(EvalResult).where(EvalResult.eval_run_id == eval_run_id)
    if metric_name is not None:
        base = base.where(EvalResult.metric_name == metric_name)

    total_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_result.scalar_one()

    items_result = await db.execute(
        base.order_by(EvalResult.created_at.desc()).offset(skip).limit(limit)
    )
    items = list(items_result.scalars().all())

    return EvalResultListResponse(items=items, total=total)


@router.post(
    "/{eval_run_id}/cancel",
    response_model=EvalRunResponse,
    summary="Cancel a running evaluation",
)
async def cancel_eval_run(
    eval_run_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvalRun:
    """Cancel a pending or running evaluation run.

    Sets the status to ``failed`` and records the completion timestamp.
    """
    run = await _get_eval_run_or_404(eval_run_id, org, db)

    if run.status not in (EvalRunStatus.PENDING, EvalRunStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel eval run with status '{run.status.value}'",
        )

    run.status = EvalRunStatus.FAILED
    run.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(run)

    # TODO: revoke Celery task if running
    logger.info("Eval run cancelled", eval_run_id=str(run.id))
    return run
