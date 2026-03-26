"""Export eval reports to various formats (CSV, JSON, HTML)."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from evalplatform.reports.generator import ComparisonReport, EvalReport


class ReportExporter:
    """Export eval reports to various formats."""

    def to_json(self, report: EvalReport) -> str:
        return report.model_dump_json(indent=2)

    def to_csv(self, report: EvalReport) -> str:
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        if report.metric_summaries:
            metric_names = [ms.metric_name for ms in report.metric_summaries]
        else:
            metric_names = []

        writer.writerow(["conversation_id", "overall_score", *metric_names, "flags"])

        # Rows
        for conv in report.conversation_summaries:
            row = [
                conv.conversation_id,
                f"{conv.overall_score:.4f}",
                *[f"{conv.metric_scores.get(m, 0):.4f}" for m in metric_names],
                "; ".join(conv.flags),
            ]
            writer.writerow(row)

        # Summary section
        writer.writerow([])
        writer.writerow(["--- Summary ---"])
        writer.writerow(["Metric", "Mean", "Median", "Min", "Max", "StdDev", "Pass Rate"])
        for ms in report.metric_summaries:
            writer.writerow([
                ms.metric_name,
                f"{ms.mean_score:.4f}",
                f"{ms.median_score:.4f}",
                f"{ms.min_score:.4f}",
                f"{ms.max_score:.4f}",
                f"{ms.std_dev:.4f}",
                f"{ms.pass_rate:.2%}",
            ])

        return output.getvalue()

    def to_html(self, report: EvalReport) -> str:
        """Generate a standalone HTML report."""
        metric_names = [ms.metric_name for ms in report.metric_summaries]

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Eval Report - {report.eval_run_id}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; color: #1a1a1a; }}
h1 {{ color: #1e40af; }}
h2 {{ color: #374151; border-bottom: 2px solid #e5e7eb; padding-bottom: 0.5rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #e5e7eb; padding: 0.5rem 0.75rem; text-align: left; }}
th {{ background: #f9fafb; font-weight: 600; }}
.score {{ font-weight: 600; }}
.score-good {{ color: #059669; }}
.score-warn {{ color: #d97706; }}
.score-bad {{ color: #dc2626; }}
.summary-card {{ display: inline-block; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem 1.5rem; margin: 0.5rem; }}
.summary-value {{ font-size: 2rem; font-weight: 700; color: #1e40af; }}
.flag {{ background: #fef2f2; color: #991b1b; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem; }}
.recommendation {{ background: #eff6ff; border-left: 4px solid #3b82f6; padding: 0.75rem; margin: 0.5rem 0; }}
</style>
</head>
<body>
<h1>Chatbot Evaluation Report</h1>
<p>Run ID: {report.eval_run_id} | Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}</p>

<div>
<div class="summary-card">
<div>Conversations</div>
<div class="summary-value">{report.total_conversations}</div>
</div>
<div class="summary-card">
<div>Overall Score</div>
<div class="summary-value {self._score_class(report.overall_score)}">{report.overall_score:.2%}</div>
</div>
</div>

<h2>Metric Summary</h2>
<table>
<tr><th>Metric</th><th>Mean</th><th>Median</th><th>Min</th><th>Max</th><th>Pass Rate</th></tr>
"""
        for ms in report.metric_summaries:
            cls = self._score_class(ms.mean_score)
            html += f"""<tr>
<td>{ms.metric_name}</td>
<td class="score {cls}">{ms.mean_score:.4f}</td>
<td>{ms.median_score:.4f}</td>
<td>{ms.min_score:.4f}</td>
<td>{ms.max_score:.4f}</td>
<td class="score {self._score_class(ms.pass_rate)}">{ms.pass_rate:.2%}</td>
</tr>"""

        html += """</table>

<h2>Top Issues</h2>
"""
        if report.top_issues:
            for issue in report.top_issues:
                severity = issue.get("severity", "warning")
                html += f'<div class="recommendation"><strong>[{severity.upper()}]</strong> '
                if issue["type"] == "low_metric":
                    html += f'Metric "{issue["metric"]}" has low score: {issue["mean_score"]:.4f}'
                elif issue["type"] == "multi_flag_conversation":
                    html += f'Conversation {issue["conversation_id"]} flagged: {", ".join(issue["flags"])}'
                html += "</div>\n"
        else:
            html += "<p>No critical issues detected.</p>"

        html += "\n<h2>Recommendations</h2>\n"
        for rec in report.recommendations:
            html += f'<div class="recommendation">{rec}</div>\n'

        html += f"""
<h2>Conversation Details</h2>
<table>
<tr><th>Conversation</th><th>Overall</th>{"".join(f"<th>{m}</th>" for m in metric_names)}<th>Flags</th></tr>
"""
        for conv in report.conversation_summaries[:50]:
            cls = self._score_class(conv.overall_score)
            html += f'<tr><td>{conv.conversation_id}</td><td class="score {cls}">{conv.overall_score:.4f}</td>'
            for m in metric_names:
                s = conv.metric_scores.get(m, 0)
                html += f'<td class="score {self._score_class(s)}">{s:.4f}</td>'
            flags_html = " ".join(f'<span class="flag">{f}</span>' for f in conv.flags)
            html += f"<td>{flags_html}</td></tr>\n"

        html += """</table>
</body>
</html>"""
        return html

    def comparison_to_json(self, report: ComparisonReport) -> str:
        return report.model_dump_json(indent=2)

    def _score_class(self, score: float) -> str:
        if score >= 0.7:
            return "score-good"
        elif score >= 0.4:
            return "score-warn"
        return "score-bad"
