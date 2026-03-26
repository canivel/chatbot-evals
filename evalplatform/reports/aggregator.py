"""Aggregation engine for eval metrics across conversations and time."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class TimeSeriesPoint(BaseModel):
    timestamp: datetime
    value: float
    count: int = 1


class MetricTimeSeries(BaseModel):
    metric_name: str
    points: list[TimeSeriesPoint] = Field(default_factory=list)


class DashboardMetrics(BaseModel):
    """Aggregate metrics for the dashboard."""

    total_conversations_evaluated: int = 0
    total_eval_runs: int = 0
    overall_health_score: float = 0.0
    metric_averages: dict[str, float] = Field(default_factory=dict)
    metric_trends: dict[str, str] = Field(default_factory=dict)  # "improving"/"declining"/"stable"
    top_issues: list[dict[str, Any]] = Field(default_factory=list)
    recent_runs: list[dict[str, Any]] = Field(default_factory=list)


class Aggregator:
    """Aggregates eval results for dashboards and trends."""

    def compute_dashboard_metrics(
        self,
        eval_runs: list[dict[str, Any]],
        results: list[dict[str, Any]],
    ) -> DashboardMetrics:
        """Compute aggregate dashboard metrics."""
        if not results:
            return DashboardMetrics()

        # Unique conversations
        conv_ids = {r["conversation_id"] for r in results}

        # Metric averages
        by_metric: dict[str, list[float]] = {}
        for r in results:
            by_metric.setdefault(r["metric_name"], []).append(r["score"])

        metric_averages = {
            name: round(sum(scores) / len(scores), 4)
            for name, scores in by_metric.items()
        }

        # Overall health = mean of all metric averages
        all_avgs = list(metric_averages.values())
        overall_health = sum(all_avgs) / len(all_avgs) if all_avgs else 0

        # Compute trends (requires multiple eval runs)
        metric_trends = self._compute_trends(eval_runs, results)

        # Top issues
        top_issues = []
        for name, avg in sorted(metric_averages.items(), key=lambda x: x[1]):
            if avg < 0.7:
                top_issues.append({
                    "metric": name,
                    "score": avg,
                    "severity": "critical" if avg < 0.4 else "warning",
                })

        # Recent runs
        recent_runs = sorted(eval_runs, key=lambda r: r.get("created_at", ""), reverse=True)[:5]

        return DashboardMetrics(
            total_conversations_evaluated=len(conv_ids),
            total_eval_runs=len(eval_runs),
            overall_health_score=round(overall_health, 4),
            metric_averages=metric_averages,
            metric_trends=metric_trends,
            top_issues=top_issues[:5],
            recent_runs=recent_runs,
        )

    def compute_time_series(
        self,
        results: list[dict[str, Any]],
        metric_name: str,
        bucket_size: str = "day",  # "hour", "day", "week"
    ) -> MetricTimeSeries:
        """Compute time series for a specific metric."""
        metric_results = [r for r in results if r["metric_name"] == metric_name]
        if not metric_results:
            return MetricTimeSeries(metric_name=metric_name)

        # Group by time bucket
        buckets: dict[str, list[float]] = {}
        for r in metric_results:
            ts = r.get("created_at", datetime.now(timezone.utc).isoformat())
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            bucket_key = self._get_bucket_key(ts, bucket_size)
            buckets.setdefault(bucket_key, []).append(r["score"])

        points = []
        for key in sorted(buckets.keys()):
            scores = buckets[key]
            points.append(TimeSeriesPoint(
                timestamp=datetime.fromisoformat(key),
                value=round(sum(scores) / len(scores), 4),
                count=len(scores),
            ))

        return MetricTimeSeries(metric_name=metric_name, points=points)

    def _compute_trends(
        self,
        eval_runs: list[dict[str, Any]],
        results: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Determine if each metric is improving, declining, or stable."""
        if len(eval_runs) < 2:
            return {}

        # Sort runs by creation time
        sorted_runs = sorted(eval_runs, key=lambda r: r.get("created_at", ""))

        # Get first half and second half of results
        mid = len(sorted_runs) // 2
        first_half_ids = {r.get("id") for r in sorted_runs[:mid]}
        second_half_ids = {r.get("id") for r in sorted_runs[mid:]}

        first_by_metric: dict[str, list[float]] = {}
        second_by_metric: dict[str, list[float]] = {}

        for r in results:
            run_id = r.get("eval_run_id")
            metric = r["metric_name"]
            score = r["score"]
            if run_id in first_half_ids:
                first_by_metric.setdefault(metric, []).append(score)
            elif run_id in second_half_ids:
                second_by_metric.setdefault(metric, []).append(score)

        trends = {}
        all_metrics = set(first_by_metric.keys()) | set(second_by_metric.keys())
        for metric in all_metrics:
            first_avg = (
                sum(first_by_metric.get(metric, [0])) / max(len(first_by_metric.get(metric, [1])), 1)
            )
            second_avg = (
                sum(second_by_metric.get(metric, [0])) / max(len(second_by_metric.get(metric, [1])), 1)
            )
            diff = second_avg - first_avg
            if diff > 0.05:
                trends[metric] = "improving"
            elif diff < -0.05:
                trends[metric] = "declining"
            else:
                trends[metric] = "stable"

        return trends

    def _get_bucket_key(self, ts: datetime, bucket_size: str) -> str:
        if bucket_size == "hour":
            return ts.replace(minute=0, second=0, microsecond=0).isoformat()
        elif bucket_size == "week":
            # Start of week (Monday)
            days_since_monday = ts.weekday()
            start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
            from datetime import timedelta
            start = start - timedelta(days=days_since_monday)
            return start.isoformat()
        else:  # day
            return ts.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
