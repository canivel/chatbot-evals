"""Report generation engine for eval results.

Generates detailed reports from eval runs including per-conversation
breakdowns, aggregate scores, trends, and comparisons.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class MetricSummary(BaseModel):
    metric_name: str
    mean_score: float
    median_score: float
    min_score: float
    max_score: float
    std_dev: float
    pass_rate: float  # % of conversations above threshold
    threshold: float = 0.7
    sample_count: int = 0


class ConversationEvalSummary(BaseModel):
    conversation_id: str
    overall_score: float
    metric_scores: dict[str, float]
    flags: list[str] = Field(default_factory=list)  # e.g., "hallucination_detected"
    summary: str = ""


class EvalReport(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    eval_run_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_conversations: int = 0
    overall_score: float = 0.0
    metric_summaries: list[MetricSummary] = Field(default_factory=list)
    conversation_summaries: list[ConversationEvalSummary] = Field(default_factory=list)
    top_issues: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ComparisonReport(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    eval_run_a_id: str
    eval_run_b_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metric_comparisons: dict[str, dict[str, float]] = Field(default_factory=dict)
    winner: str | None = None
    summary: str = ""


class ReportGenerator:
    """Generates evaluation reports from raw eval results."""

    def __init__(self, pass_threshold: float = 0.7) -> None:
        self.pass_threshold = pass_threshold

    def generate_eval_report(
        self,
        eval_run_id: str,
        results: list[dict[str, Any]],
    ) -> EvalReport:
        """Generate a comprehensive eval report from raw results.

        Args:
            eval_run_id: The eval run to report on.
            results: List of dicts with conversation_id, metric_name, score, explanation.
        """
        if not results:
            return EvalReport(eval_run_id=eval_run_id)

        # Group results by metric
        by_metric: dict[str, list[float]] = {}
        # Group results by conversation
        by_conversation: dict[str, dict[str, float]] = {}

        for r in results:
            metric = r["metric_name"]
            score = r["score"]
            conv_id = r["conversation_id"]

            by_metric.setdefault(metric, []).append(score)
            by_conversation.setdefault(conv_id, {})[metric] = score

        # Generate metric summaries
        metric_summaries = []
        for metric_name, scores in by_metric.items():
            summary = self._compute_metric_summary(metric_name, scores)
            metric_summaries.append(summary)

        # Generate conversation summaries
        conversation_summaries = []
        for conv_id, metric_scores in by_conversation.items():
            overall = sum(metric_scores.values()) / len(metric_scores) if metric_scores else 0
            flags = [
                f"low_{metric}" for metric, score in metric_scores.items()
                if score < self.pass_threshold
            ]
            conversation_summaries.append(ConversationEvalSummary(
                conversation_id=conv_id,
                overall_score=overall,
                metric_scores=metric_scores,
                flags=flags,
            ))

        # Sort by score ascending (worst first)
        conversation_summaries.sort(key=lambda c: c.overall_score)

        # Identify top issues
        top_issues = self._identify_top_issues(metric_summaries, conversation_summaries)

        # Generate recommendations
        recommendations = self._generate_recommendations(metric_summaries)

        # Overall score
        all_scores = [c.overall_score for c in conversation_summaries]
        overall_score = sum(all_scores) / len(all_scores) if all_scores else 0

        return EvalReport(
            eval_run_id=eval_run_id,
            total_conversations=len(by_conversation),
            overall_score=overall_score,
            metric_summaries=metric_summaries,
            conversation_summaries=conversation_summaries,
            top_issues=top_issues,
            recommendations=recommendations,
        )

    def generate_comparison_report(
        self,
        results_a: list[dict[str, Any]],
        results_b: list[dict[str, Any]],
        eval_run_a_id: str,
        eval_run_b_id: str,
    ) -> ComparisonReport:
        """Compare two eval runs."""
        metrics_a = self._aggregate_by_metric(results_a)
        metrics_b = self._aggregate_by_metric(results_b)

        all_metrics = set(metrics_a.keys()) | set(metrics_b.keys())
        comparisons: dict[str, dict[str, float]] = {}

        a_wins = 0
        b_wins = 0

        for metric in all_metrics:
            mean_a = sum(metrics_a.get(metric, [0])) / max(len(metrics_a.get(metric, [1])), 1)
            mean_b = sum(metrics_b.get(metric, [0])) / max(len(metrics_b.get(metric, [1])), 1)
            diff = mean_b - mean_a
            comparisons[metric] = {
                "run_a": round(mean_a, 4),
                "run_b": round(mean_b, 4),
                "difference": round(diff, 4),
                "improved": diff > 0.01,
                "regressed": diff < -0.01,
            }
            if diff > 0.01:
                b_wins += 1
            elif diff < -0.01:
                a_wins += 1

        winner = None
        if a_wins > b_wins:
            winner = eval_run_a_id
        elif b_wins > a_wins:
            winner = eval_run_b_id

        return ComparisonReport(
            eval_run_a_id=eval_run_a_id,
            eval_run_b_id=eval_run_b_id,
            metric_comparisons=comparisons,
            winner=winner,
            summary=f"Run B {'improved' if b_wins > a_wins else 'regressed' if a_wins > b_wins else 'tied'} on {max(a_wins, b_wins)}/{len(all_metrics)} metrics",
        )

    def _compute_metric_summary(self, name: str, scores: list[float]) -> MetricSummary:
        n = len(scores)
        sorted_scores = sorted(scores)
        mean = sum(scores) / n
        median = sorted_scores[n // 2] if n % 2 == 1 else (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
        variance = sum((s - mean) ** 2 for s in scores) / n
        std_dev = variance ** 0.5
        pass_count = sum(1 for s in scores if s >= self.pass_threshold)

        return MetricSummary(
            metric_name=name,
            mean_score=round(mean, 4),
            median_score=round(median, 4),
            min_score=round(min(scores), 4),
            max_score=round(max(scores), 4),
            std_dev=round(std_dev, 4),
            pass_rate=round(pass_count / n, 4) if n > 0 else 0,
            threshold=self.pass_threshold,
            sample_count=n,
        )

    def _identify_top_issues(
        self,
        metric_summaries: list[MetricSummary],
        conversation_summaries: list[ConversationEvalSummary],
    ) -> list[dict[str, Any]]:
        issues = []

        # Low-scoring metrics
        for ms in metric_summaries:
            if ms.mean_score < self.pass_threshold:
                issues.append({
                    "type": "low_metric",
                    "metric": ms.metric_name,
                    "mean_score": ms.mean_score,
                    "pass_rate": ms.pass_rate,
                    "severity": "critical" if ms.mean_score < 0.4 else "warning",
                })

        # Conversations with many flags
        for cs in conversation_summaries[:5]:
            if len(cs.flags) >= 3:
                issues.append({
                    "type": "multi_flag_conversation",
                    "conversation_id": cs.conversation_id,
                    "flags": cs.flags,
                    "overall_score": cs.overall_score,
                    "severity": "critical" if cs.overall_score < 0.4 else "warning",
                })

        return sorted(issues, key=lambda i: 0 if i["severity"] == "critical" else 1)

    def _generate_recommendations(self, metric_summaries: list[MetricSummary]) -> list[str]:
        recommendations = []

        for ms in metric_summaries:
            if ms.metric_name == "hallucination" and ms.mean_score < 0.8:
                recommendations.append(
                    "High hallucination rate detected. Review retrieval pipeline and consider "
                    "adding stricter grounding constraints to the chatbot."
                )
            elif ms.metric_name == "toxicity" and ms.mean_score < 0.95:
                recommendations.append(
                    "Toxicity issues detected. Add safety guardrails and content filtering."
                )
            elif ms.metric_name == "relevance" and ms.mean_score < 0.7:
                recommendations.append(
                    "Low relevance scores. Review intent classification and retrieval quality."
                )
            elif ms.metric_name == "faithfulness" and ms.mean_score < 0.7:
                recommendations.append(
                    "Low faithfulness. Chatbot may be generating responses not grounded in context."
                )
            elif ms.pass_rate < 0.5:
                recommendations.append(
                    f"Metric '{ms.metric_name}' has <50% pass rate. Investigate root cause."
                )

        return recommendations

    def _aggregate_by_metric(self, results: list[dict[str, Any]]) -> dict[str, list[float]]:
        by_metric: dict[str, list[float]] = {}
        for r in results:
            by_metric.setdefault(r["metric_name"], []).append(r["score"])
        return by_metric
