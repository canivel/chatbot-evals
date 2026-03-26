"""Tests for the report generation engine."""

import pytest
from evalplatform.reports.generator import ReportGenerator, EvalReport
from evalplatform.reports.aggregator import Aggregator
from evalplatform.reports.alerting import AlertEngine, AlertRule, AlertSeverity
from evalplatform.reports.exporters import ReportExporter


@pytest.fixture
def sample_results():
    return [
        {"conversation_id": "c1", "metric_name": "faithfulness", "score": 0.85, "explanation": "Good"},
        {"conversation_id": "c1", "metric_name": "relevance", "score": 0.90, "explanation": "Very relevant"},
        {"conversation_id": "c1", "metric_name": "hallucination", "score": 0.95, "explanation": "No hallucinations"},
        {"conversation_id": "c2", "metric_name": "faithfulness", "score": 0.40, "explanation": "Low grounding"},
        {"conversation_id": "c2", "metric_name": "relevance", "score": 0.60, "explanation": "Partially relevant"},
        {"conversation_id": "c2", "metric_name": "hallucination", "score": 0.30, "explanation": "Multiple hallucinations"},
        {"conversation_id": "c3", "metric_name": "faithfulness", "score": 0.75, "explanation": "Mostly grounded"},
        {"conversation_id": "c3", "metric_name": "relevance", "score": 0.80, "explanation": "Relevant"},
        {"conversation_id": "c3", "metric_name": "hallucination", "score": 0.70, "explanation": "Minor issues"},
    ]


def test_generate_eval_report(sample_results):
    gen = ReportGenerator()
    report = gen.generate_eval_report("run-001", sample_results)

    assert report.eval_run_id == "run-001"
    assert report.total_conversations == 3
    assert len(report.metric_summaries) == 3
    assert len(report.conversation_summaries) == 3
    assert 0 <= report.overall_score <= 1


def test_metric_summaries(sample_results):
    gen = ReportGenerator()
    report = gen.generate_eval_report("run-001", sample_results)

    faith_summary = next(ms for ms in report.metric_summaries if ms.metric_name == "faithfulness")
    assert faith_summary.sample_count == 3
    assert faith_summary.min_score == 0.40
    assert faith_summary.max_score == 0.85


def test_conversation_flags(sample_results):
    gen = ReportGenerator()
    report = gen.generate_eval_report("run-001", sample_results)

    # c2 has low scores, should have flags
    c2 = next(cs for cs in report.conversation_summaries if cs.conversation_id == "c2")
    assert len(c2.flags) > 0


def test_empty_results():
    gen = ReportGenerator()
    report = gen.generate_eval_report("empty-run", [])
    assert report.total_conversations == 0
    assert report.overall_score == 0


def test_comparison_report(sample_results):
    gen = ReportGenerator()
    results_a = sample_results
    results_b = [
        {**r, "score": min(r["score"] + 0.1, 1.0)}
        for r in sample_results
    ]

    comparison = gen.generate_comparison_report(results_a, results_b, "run-a", "run-b")
    assert comparison.eval_run_a_id == "run-a"
    assert comparison.eval_run_b_id == "run-b"
    assert len(comparison.metric_comparisons) == 3


def test_report_exporter_json(sample_results):
    gen = ReportGenerator()
    report = gen.generate_eval_report("run-001", sample_results)
    exporter = ReportExporter()

    json_output = exporter.to_json(report)
    assert "run-001" in json_output
    assert "faithfulness" in json_output


def test_report_exporter_csv(sample_results):
    gen = ReportGenerator()
    report = gen.generate_eval_report("run-001", sample_results)
    exporter = ReportExporter()

    csv_output = exporter.to_csv(report)
    assert "conversation_id" in csv_output
    assert "faithfulness" in csv_output


def test_report_exporter_html(sample_results):
    gen = ReportGenerator()
    report = gen.generate_eval_report("run-001", sample_results)
    exporter = ReportExporter()

    html_output = exporter.to_html(report)
    assert "<html" in html_output
    assert "Chatbot Evaluation Report" in html_output


def test_alert_engine():
    engine = AlertEngine()
    rules = engine.get_default_rules()
    for rule in rules:
        engine.add_rule(rule)

    # Should trigger hallucination alert
    alerts = engine.evaluate({"hallucination": 0.5, "toxicity": 0.95, "relevance": 0.8})
    assert len(alerts) >= 1
    assert any(a.metric_name == "hallucination" for a in alerts)


def test_alert_cooldown():
    engine = AlertEngine()
    engine.add_rule(AlertRule(
        id="test-rule",
        name="Test",
        metric_name="test_metric",
        condition="below_threshold",
        threshold=0.5,
        cooldown_minutes=60,
    ))

    alerts1 = engine.evaluate({"test_metric": 0.3})
    assert len(alerts1) == 1

    # Second evaluation should be within cooldown
    alerts2 = engine.evaluate({"test_metric": 0.3})
    assert len(alerts2) == 0


def test_aggregator_dashboard():
    agg = Aggregator()
    eval_runs = [{"id": "run-1", "created_at": "2024-01-01T00:00:00"}]
    results = [
        {"eval_run_id": "run-1", "conversation_id": "c1", "metric_name": "faithfulness", "score": 0.8},
        {"eval_run_id": "run-1", "conversation_id": "c1", "metric_name": "relevance", "score": 0.9},
        {"eval_run_id": "run-1", "conversation_id": "c2", "metric_name": "faithfulness", "score": 0.7},
    ]

    dashboard = agg.compute_dashboard_metrics(eval_runs, results)
    assert dashboard.total_conversations_evaluated == 2
    assert dashboard.total_eval_runs == 1
    assert "faithfulness" in dashboard.metric_averages
