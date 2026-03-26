"""Pydantic v2 schemas for reporting and analytics endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ReportRequest(BaseModel):
    """Generic request to generate or export a report."""

    eval_run_ids: list[uuid.UUID] = Field(
        ..., min_length=1, description="Eval run(s) to include in the report"
    )
    metrics: list[str] | None = Field(
        default=None, description="Subset of metrics; None means all"
    )
    format: str = Field(
        default="json", description="Output format: json, csv, or pdf"
    )


# ---------------------------------------------------------------------------
# Aggregate / dashboard
# ---------------------------------------------------------------------------

class AggregateScores(BaseModel):
    """Aggregated scores for a single metric across an eval run."""

    metric_name: str
    mean: float
    median: float
    min: float
    max: float
    std_dev: float
    count: int


class DashboardResponse(BaseModel):
    """Top-level dashboard response with aggregate metrics."""

    organization_id: uuid.UUID
    eval_run_count: int
    conversation_count: int
    aggregate_scores: list[AggregateScores]


# ---------------------------------------------------------------------------
# Time-series
# ---------------------------------------------------------------------------

class MetricDataPoint(BaseModel):
    """A single time-series data point."""

    timestamp: datetime
    value: float


class MetricTimeSeries(BaseModel):
    """Time-series data for a single metric."""

    metric_name: str
    data_points: list[MetricDataPoint]


class TrendsResponse(BaseModel):
    """Collection of metric time-series for trend analysis."""

    series: list[MetricTimeSeries]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

class RunComparison(BaseModel):
    """Score comparison for a single metric between two runs."""

    metric_name: str
    run_a_score: float
    run_b_score: float
    delta: float
    percent_change: float | None = None


class ComparisonReport(BaseModel):
    """Side-by-side comparison of two evaluation runs."""

    run_a_id: uuid.UUID
    run_b_id: uuid.UUID
    comparisons: list[RunComparison]


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

class ReportResponse(BaseModel):
    """Detailed report for one or more evaluation runs."""

    eval_run_ids: list[uuid.UUID]
    generated_at: datetime
    aggregate_scores: list[AggregateScores]
    time_series: list[MetricTimeSeries] | None = None
    comparison: ComparisonReport | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
