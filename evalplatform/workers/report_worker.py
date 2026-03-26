"""Worker for async report generation."""

from __future__ import annotations

from typing import Any

import structlog

from evalplatform.reports.generator import ReportGenerator
from evalplatform.reports.exporters import ReportExporter

logger = structlog.get_logger()


async def generate_report_task(
    eval_run_id: str,
    results: list[dict[str, Any]],
    export_format: str = "json",
) -> dict[str, Any]:
    """Generate and export an eval report.

    Args:
        eval_run_id: The eval run to report on.
        results: Raw eval results.
        export_format: Output format (json, csv, html).

    Returns:
        Dict with report_id, format, and content.
    """
    logger.info("report_generation_started", eval_run_id=eval_run_id, format=export_format)

    try:
        generator = ReportGenerator()
        report = generator.generate_eval_report(eval_run_id, results)

        exporter = ReportExporter()
        if export_format == "csv":
            content = exporter.to_csv(report)
        elif export_format == "html":
            content = exporter.to_html(report)
        else:
            content = exporter.to_json(report)

        logger.info("report_generation_completed", report_id=report.id)

        return {
            "report_id": report.id,
            "eval_run_id": eval_run_id,
            "format": export_format,
            "content": content,
            "total_conversations": report.total_conversations,
            "overall_score": report.overall_score,
        }

    except Exception as e:
        logger.error("report_generation_failed", eval_run_id=eval_run_id, error=str(e))
        return {
            "eval_run_id": eval_run_id,
            "status": "failed",
            "error": str(e),
        }


async def generate_comparison_report_task(
    results_a: list[dict[str, Any]],
    results_b: list[dict[str, Any]],
    eval_run_a_id: str,
    eval_run_b_id: str,
) -> dict[str, Any]:
    """Generate a comparison report between two eval runs."""
    logger.info(
        "comparison_report_started",
        run_a=eval_run_a_id,
        run_b=eval_run_b_id,
    )

    try:
        generator = ReportGenerator()
        report = generator.generate_comparison_report(
            results_a, results_b, eval_run_a_id, eval_run_b_id,
        )

        exporter = ReportExporter()
        content = exporter.comparison_to_json(report)

        return {
            "report_id": report.id,
            "run_a": eval_run_a_id,
            "run_b": eval_run_b_id,
            "winner": report.winner,
            "summary": report.summary,
            "content": content,
        }

    except Exception as e:
        logger.error("comparison_report_failed", error=str(e))
        return {"status": "failed", "error": str(e)}
