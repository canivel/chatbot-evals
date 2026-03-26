"""Reporting and analytics routes."""

from __future__ import annotations

import io
import math
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from evalplatform.api.deps import get_current_org, get_db
from evalplatform.api.models.conversation import Conversation
from evalplatform.api.models.eval_result import EvalResult
from evalplatform.api.models.eval_run import EvalRun
from evalplatform.api.models.organization import Organization
from evalplatform.api.schemas.report import (
    AggregateScores,
    ComparisonReport,
    DashboardResponse,
    MetricDataPoint,
    MetricTimeSeries,
    ReportRequest,
    ReportResponse,
    RunComparison,
    TrendsResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _aggregate_for_run(
    eval_run_id: uuid.UUID,
    db: AsyncSession,
) -> list[AggregateScores]:
    """Compute per-metric aggregate statistics for a single eval run."""
    result = await db.execute(
        select(
            EvalResult.metric_name,
            func.avg(EvalResult.score).label("mean"),
            func.min(EvalResult.score).label("min_score"),
            func.max(EvalResult.score).label("max_score"),
            func.count(EvalResult.id).label("cnt"),
            # SQLAlchemy's func.stddev_pop maps to the SQL standard
            func.coalesce(func.stddev_pop(EvalResult.score), 0.0).label("std"),
        )
        .where(EvalResult.eval_run_id == eval_run_id)
        .group_by(EvalResult.metric_name)
    )
    rows = result.all()

    aggregates: list[AggregateScores] = []
    for row in rows:
        # Median requires a separate query (or window function).  For
        # simplicity we approximate it with the average of min and max when
        # count is small, or compute via percentile_cont when available.
        # Here we fall back to a simple sorted-fetch approach.
        med_result = await db.execute(
            select(EvalResult.score)
            .where(
                EvalResult.eval_run_id == eval_run_id,
                EvalResult.metric_name == row.metric_name,
            )
            .order_by(EvalResult.score)
        )
        scores = [r for (r,) in med_result.all()]
        n = len(scores)
        if n == 0:
            median = 0.0
        elif n % 2 == 1:
            median = scores[n // 2]
        else:
            median = (scores[n // 2 - 1] + scores[n // 2]) / 2.0

        aggregates.append(
            AggregateScores(
                metric_name=row.metric_name,
                mean=round(float(row.mean), 4),
                median=round(median, 4),
                min=round(float(row.min_score), 4),
                max=round(float(row.max_score), 4),
                std_dev=round(float(row.std), 4),
                count=int(row.cnt),
            )
        )

    return aggregates


async def _validate_run_belongs_to_org(
    run_id: uuid.UUID,
    org: Organization,
    db: AsyncSession,
) -> EvalRun:
    result = await db.execute(
        select(EvalRun).where(EvalRun.id == run_id, EvalRun.organization_id == org.id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Eval run {run_id} not found",
        )
    return run


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Organisation-level dashboard metrics",
)
async def dashboard(
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardResponse:
    """Return high-level aggregate metrics across the entire organization."""
    # Counts
    run_count_result = await db.execute(
        select(func.count(EvalRun.id)).where(EvalRun.organization_id == org.id)
    )
    eval_run_count = run_count_result.scalar_one()

    conv_count_result = await db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.organization_id == org.id
        )
    )
    conversation_count = conv_count_result.scalar_one()

    # Aggregate scores across all runs in the org
    result = await db.execute(
        select(
            EvalResult.metric_name,
            func.avg(EvalResult.score).label("mean"),
            func.min(EvalResult.score).label("min_score"),
            func.max(EvalResult.score).label("max_score"),
            func.count(EvalResult.id).label("cnt"),
            func.coalesce(func.stddev_pop(EvalResult.score), 0.0).label("std"),
        )
        .join(EvalRun, EvalResult.eval_run_id == EvalRun.id)
        .where(EvalRun.organization_id == org.id)
        .group_by(EvalResult.metric_name)
    )
    rows = result.all()

    aggregates = [
        AggregateScores(
            metric_name=r.metric_name,
            mean=round(float(r.mean), 4),
            median=round(float(r.mean), 4),  # approximation for dashboard
            min=round(float(r.min_score), 4),
            max=round(float(r.max_score), 4),
            std_dev=round(float(r.std), 4),
            count=int(r.cnt),
        )
        for r in rows
    ]

    return DashboardResponse(
        organization_id=org.id,
        eval_run_count=eval_run_count,
        conversation_count=conversation_count,
        aggregate_scores=aggregates,
    )


@router.get(
    "/eval/{eval_run_id}",
    response_model=ReportResponse,
    summary="Detailed report for a single eval run",
)
async def eval_report(
    eval_run_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReportResponse:
    """Generate a detailed report for a given evaluation run."""
    await _validate_run_belongs_to_org(eval_run_id, org, db)
    aggregates = await _aggregate_for_run(eval_run_id, db)

    return ReportResponse(
        eval_run_ids=[eval_run_id],
        generated_at=datetime.now(timezone.utc),
        aggregate_scores=aggregates,
    )


@router.get(
    "/compare",
    response_model=ComparisonReport,
    summary="Compare two evaluation runs side-by-side",
)
async def compare_runs(
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
    run_a: uuid.UUID = Query(..., description="First eval run ID"),
    run_b: uuid.UUID = Query(..., description="Second eval run ID"),
) -> ComparisonReport:
    """Compare aggregate scores between two evaluation runs."""
    await _validate_run_belongs_to_org(run_a, org, db)
    await _validate_run_belongs_to_org(run_b, org, db)

    agg_a = {a.metric_name: a for a in await _aggregate_for_run(run_a, db)}
    agg_b = {b.metric_name: b for b in await _aggregate_for_run(run_b, db)}

    all_metrics = sorted(set(agg_a.keys()) | set(agg_b.keys()))
    comparisons: list[RunComparison] = []
    for metric in all_metrics:
        score_a = agg_a[metric].mean if metric in agg_a else 0.0
        score_b = agg_b[metric].mean if metric in agg_b else 0.0
        delta = round(score_b - score_a, 4)
        pct = round((delta / score_a) * 100, 2) if score_a != 0 else None
        comparisons.append(
            RunComparison(
                metric_name=metric,
                run_a_score=round(score_a, 4),
                run_b_score=round(score_b, 4),
                delta=delta,
                percent_change=pct,
            )
        )

    return ComparisonReport(run_a_id=run_a, run_b_id=run_b, comparisons=comparisons)


@router.get(
    "/trends",
    response_model=TrendsResponse,
    summary="Metric scores over time",
)
async def trends(
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
    metric_name: str | None = None,
    limit: int = Query(default=30, le=365, description="Number of most recent runs"),
) -> TrendsResponse:
    """Return time-series data showing how metric scores evolve across eval runs."""
    base = (
        select(
            EvalRun.id.label("run_id"),
            EvalRun.created_at.label("ts"),
            EvalResult.metric_name,
            func.avg(EvalResult.score).label("avg_score"),
        )
        .join(EvalResult, EvalResult.eval_run_id == EvalRun.id)
        .where(EvalRun.organization_id == org.id)
    )
    if metric_name is not None:
        base = base.where(EvalResult.metric_name == metric_name)

    base = (
        base.group_by(EvalRun.id, EvalRun.created_at, EvalResult.metric_name)
        .order_by(EvalRun.created_at.desc())
        .limit(limit)
    )

    result = await db.execute(base)
    rows = result.all()

    # Group by metric
    series_map: dict[str, list[MetricDataPoint]] = {}
    for row in rows:
        pts = series_map.setdefault(row.metric_name, [])
        pts.append(MetricDataPoint(timestamp=row.ts, value=round(float(row.avg_score), 4)))

    # Sort points chronologically
    series = [
        MetricTimeSeries(
            metric_name=name,
            data_points=sorted(pts, key=lambda p: p.timestamp),
        )
        for name, pts in sorted(series_map.items())
    ]

    return TrendsResponse(series=series)


@router.post(
    "/export",
    summary="Export report as CSV or PDF",
)
async def export_report(
    body: ReportRequest,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Export evaluation data as CSV (PDF generation is a future enhancement).

    Returns a streaming file download.
    """
    # Validate all referenced runs
    for run_id in body.eval_run_ids:
        await _validate_run_belongs_to_org(run_id, org, db)

    if body.format not in ("csv", "json", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format: {body.format}",
        )

    # Fetch results
    query = select(EvalResult).where(
        EvalResult.eval_run_id.in_(body.eval_run_ids)
    )
    if body.metrics:
        query = query.where(EvalResult.metric_name.in_(body.metrics))
    query = query.order_by(EvalResult.eval_run_id, EvalResult.metric_name)

    result = await db.execute(query)
    rows = list(result.scalars().all())

    if body.format == "csv":
        lines = ["eval_run_id,conversation_id,metric_name,score,explanation"]
        for r in rows:
            explanation_escaped = r.explanation.replace('"', '""')
            lines.append(
                f'{r.eval_run_id},{r.conversation_id},{r.metric_name},'
                f'{r.score},"{explanation_escaped}"'
            )
        content = "\n".join(lines)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=report.csv"},
        )

    # Default to JSON
    import json as _json

    data = [
        {
            "eval_run_id": str(r.eval_run_id),
            "conversation_id": str(r.conversation_id),
            "metric_name": r.metric_name,
            "score": r.score,
            "explanation": r.explanation,
            "details": r.details,
        }
        for r in rows
    ]
    content = _json.dumps(data, indent=2)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=report.json"},
    )
