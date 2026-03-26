"""User-facing type definitions for the chatbot-evals SDK.

Provides simplified, ergonomic types that wrap the internal evaluation engine
models.  All types are Pydantic v2 ``BaseModel`` subclasses with helper
class-methods for convenient construction from common data formats.
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Message & Conversation
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A single chat message in a conversation.

    Attributes:
        role: The speaker role -- ``"user"``, ``"assistant"``, or ``"system"``.
        content: The text body of the message.
        metadata: Arbitrary key/value metadata for this message.
        timestamp: When the message was sent (optional).

    Example::

        msg = Message(role="user", content="What is your return policy?")
    """

    role: str = Field(..., description="Role: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="Text content of the message")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")
    timestamp: datetime | None = Field(default=None, description="When the message was sent")

    def __repr__(self) -> str:
        preview = self.content[:60] + "..." if len(self.content) > 60 else self.content
        return f"Message(role={self.role!r}, content={preview!r})"


class Conversation(BaseModel):
    """A full conversation to evaluate.

    Attributes:
        messages: Ordered list of :class:`Message` objects.
        id: Unique identifier (auto-generated if omitted).
        ground_truth: The expected correct answer, if available.
        context: Retrieved context documents the chatbot had access to.
        system_prompt: The system prompt given to the chatbot.
        metadata: Arbitrary key/value metadata for the conversation.

    Example::

        conv = Conversation(
            messages=[
                Message(role="user", content="What is AI?"),
                Message(role="assistant", content="AI is artificial intelligence."),
            ],
            context="AI stands for artificial intelligence.",
        )
    """

    messages: list[Message] = Field(..., description="Ordered messages in the conversation")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique conversation ID")
    ground_truth: str | None = Field(default=None, description="Expected correct answer")
    context: str | list[str] | None = Field(
        default=None, description="Retrieved context document(s)"
    )
    system_prompt: str | None = Field(default=None, description="System prompt for the chatbot")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")

    # -- Convenience constructors --------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Conversation:
        """Create a Conversation from a plain dictionary.

        The dictionary should contain a ``messages`` key (list of dicts with
        ``role`` and ``content``).  All other recognised keys are forwarded.

        Example::

            conv = Conversation.from_dict({
                "messages": [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                ],
                "context": "Greeting context.",
            })
        """
        messages_raw = data.get("messages", [])
        messages = [
            Message(**m) if isinstance(m, dict) else m
            for m in messages_raw
        ]
        return cls(
            messages=messages,
            id=data.get("id", str(uuid.uuid4())),
            ground_truth=data.get("ground_truth"),
            context=data.get("context"),
            system_prompt=data.get("system_prompt"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_messages(cls, messages: list[dict[str, str] | Message], **kwargs: Any) -> Conversation:
        """Create a Conversation from a flat list of messages.

        Each element may be a ``Message`` instance or a dict with at least
        ``role`` and ``content`` keys.

        Example::

            conv = Conversation.from_messages([
                {"role": "user", "content": "Tell me a joke"},
                {"role": "assistant", "content": "Why did the chicken..."},
            ])
        """
        parsed = [
            Message(**m) if isinstance(m, dict) else m
            for m in messages
        ]
        return cls(messages=parsed, **kwargs)

    def __repr__(self) -> str:
        return (
            f"Conversation(id={self.id!r}, messages={len(self.messages)}, "
            f"has_context={self.context is not None})"
        )


# ---------------------------------------------------------------------------
# Evaluation results
# ---------------------------------------------------------------------------


class MetricDetail(BaseModel):
    """Detailed result for a single metric evaluation.

    Attributes:
        score: Normalised score between 0 and 1.
        explanation: Human-readable explanation of the score.
        raw_details: Metric-specific structured details.
    """

    score: float = Field(..., ge=0.0, le=1.0, description="Normalised score 0-1")
    explanation: str = Field(default="", description="Human-readable explanation")
    raw_details: dict[str, Any] = Field(default_factory=dict, description="Metric-specific details")

    def __repr__(self) -> str:
        return f"MetricDetail(score={self.score:.3f})"


class EvalResult(BaseModel):
    """Evaluation result for a single conversation.

    Attributes:
        conversation_id: ID of the evaluated conversation.
        scores: Mapping of metric name to normalised score.
        details: Mapping of metric name to :class:`MetricDetail`.
        overall_score: Mean score across all metrics.
        flags: List of flag strings (e.g. ``"low_faithfulness"``).
        timestamp: When the evaluation was completed.
    """

    conversation_id: str = Field(..., description="ID of the evaluated conversation")
    scores: dict[str, float] = Field(default_factory=dict, description="Metric name -> score")
    details: dict[str, MetricDetail] = Field(
        default_factory=dict, description="Metric name -> detail"
    )
    overall_score: float = Field(default=0.0, description="Mean score across all metrics")
    flags: list[str] = Field(default_factory=list, description="Warning flags")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Evaluation timestamp",
    )

    def __repr__(self) -> str:
        return (
            f"EvalResult(conversation_id={self.conversation_id!r}, "
            f"overall_score={self.overall_score:.3f}, metrics={list(self.scores.keys())})"
        )


class EvalReport(BaseModel):
    """Full evaluation report across a dataset of conversations.

    Attributes:
        results: Per-conversation :class:`EvalResult` list.
        summary: Human-readable summary string.
        metric_averages: Mapping of metric name to mean score.
        recommendations: Actionable improvement recommendations.
        created_at: Timestamp when the report was generated.
    """

    results: list[EvalResult] = Field(default_factory=list, description="Per-conversation results")
    summary: str = Field(default="", description="Human-readable summary")
    metric_averages: dict[str, float] = Field(
        default_factory=dict, description="Metric name -> average score"
    )
    recommendations: list[str] = Field(default_factory=list, description="Improvement suggestions")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Report creation time",
    )

    # -- Export helpers -------------------------------------------------------

    def to_dataframe(self) -> Any:
        """Convert results to a pandas DataFrame.

        Returns:
            A ``pandas.DataFrame`` with one row per conversation.

        Raises:
            ImportError: If pandas is not installed.

        Example::

            df = report.to_dataframe()
            print(df.head())
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "pandas is required for to_dataframe(). Install it with: pip install pandas"
            ) from exc

        rows: list[dict[str, Any]] = []
        for result in self.results:
            row: dict[str, Any] = {
                "conversation_id": result.conversation_id,
                "overall_score": result.overall_score,
                "flags": ", ".join(result.flags) if result.flags else "",
                "timestamp": result.timestamp.isoformat(),
            }
            for metric_name, score in result.scores.items():
                row[f"metric_{metric_name}"] = score
            rows.append(row)

        return pd.DataFrame(rows)

    def to_csv(self, path: str | Path) -> None:
        """Export results to a CSV file.

        Args:
            path: Destination file path.

        Example::

            report.to_csv("eval_results.csv")
        """
        path = Path(path)
        if not self.results:
            path.write_text("")
            return

        # Collect all metric names across all results
        all_metrics: set[str] = set()
        for result in self.results:
            all_metrics.update(result.scores.keys())
        all_metrics_sorted = sorted(all_metrics)

        fieldnames = [
            "conversation_id", "overall_score", "flags", "timestamp",
        ] + [f"metric_{m}" for m in all_metrics_sorted]

        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for result in self.results:
                row: dict[str, Any] = {
                    "conversation_id": result.conversation_id,
                    "overall_score": f"{result.overall_score:.4f}",
                    "flags": "; ".join(result.flags),
                    "timestamp": result.timestamp.isoformat(),
                }
                for metric in all_metrics_sorted:
                    row[f"metric_{metric}"] = (
                        f"{result.scores[metric]:.4f}" if metric in result.scores else ""
                    )
                writer.writerow(row)

    def to_html(self, path: str | Path) -> None:
        """Export results to a standalone HTML report.

        Args:
            path: Destination HTML file path.

        Example::

            report.to_html("eval_report.html")
        """
        path = Path(path)
        all_metrics: set[str] = set()
        for result in self.results:
            all_metrics.update(result.scores.keys())
        all_metrics_sorted = sorted(all_metrics)

        metric_headers = "".join(f"<th>{m}</th>" for m in all_metrics_sorted)

        rows_html: list[str] = []
        for result in self.results:
            cells = [
                f"<td>{result.conversation_id}</td>",
                f"<td>{result.overall_score:.4f}</td>",
            ]
            for metric in all_metrics_sorted:
                score = result.scores.get(metric)
                if score is not None:
                    colour = _score_colour(score)
                    cells.append(f'<td style="color:{colour}">{score:.4f}</td>')
                else:
                    cells.append("<td>-</td>")
            flags_str = ", ".join(result.flags) if result.flags else "-"
            cells.append(f"<td>{flags_str}</td>")
            rows_html.append("<tr>" + "".join(cells) + "</tr>")

        avg_cells = "".join(
            f'<td style="font-weight:bold">{self.metric_averages.get(m, 0):.4f}</td>'
            for m in all_metrics_sorted
        )

        recs_html = "".join(f"<li>{r}</li>" for r in self.recommendations)

        html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Chatbot Evaluation Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 2rem; background: #fafafa; }}
  h1 {{ color: #1a1a2e; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; background: #fff; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #1a1a2e; color: #fff; }}
  tr:nth-child(even) {{ background: #f2f2f2; }}
  .summary {{ background: #e8f5e9; padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }}
  .recs {{ background: #fff3e0; padding: 1rem; border-radius: 8px; margin-top: 1rem; }}
</style>
</head>
<body>
<h1>Chatbot Evaluation Report</h1>
<div class="summary">
  <strong>Summary:</strong> {self.summary or "No summary available."}<br>
  <strong>Conversations:</strong> {len(self.results)}<br>
  <strong>Generated:</strong> {self.created_at.isoformat()}
</div>
<h2>Results</h2>
<table>
  <thead>
    <tr><th>Conversation ID</th><th>Overall</th>{metric_headers}<th>Flags</th></tr>
  </thead>
  <tbody>
    {"".join(rows_html)}
  </tbody>
  <tfoot>
    <tr><td><strong>Average</strong></td><td><strong>{sum(r.overall_score for r in self.results) / max(len(self.results), 1):.4f}</strong></td>{avg_cells}<td></td></tr>
  </tfoot>
</table>
{"<div class='recs'><h3>Recommendations</h3><ul>" + recs_html + "</ul></div>" if self.recommendations else ""}
</body>
</html>"""
        path.write_text(html, encoding="utf-8")

    def __repr__(self) -> str:
        return (
            f"EvalReport(conversations={len(self.results)}, "
            f"metrics={list(self.metric_averages.keys())})"
        )


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class Dataset(BaseModel):
    """A collection of conversations for batch evaluation.

    Attributes:
        conversations: List of :class:`Conversation` objects.
        name: Human-readable dataset name.
        description: Description of the dataset.
        metadata: Arbitrary key/value metadata.

    Example::

        ds = Dataset(conversations=[conv1, conv2], name="support-v1")
    """

    conversations: list[Conversation] = Field(
        default_factory=list, description="Conversations in this dataset"
    )
    name: str | None = Field(default=None, description="Dataset name")
    description: str | None = Field(default=None, description="Dataset description")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")

    # -- Convenience constructors --------------------------------------------

    @classmethod
    def from_list(cls, conversations: list[Conversation | dict[str, Any]], **kwargs: Any) -> Dataset:
        """Create a Dataset from a list of Conversations or dicts.

        Example::

            ds = Dataset.from_list([
                {"messages": [{"role": "user", "content": "Hi"}]},
            ])
        """
        parsed: list[Conversation] = []
        for item in conversations:
            if isinstance(item, Conversation):
                parsed.append(item)
            elif isinstance(item, dict):
                parsed.append(Conversation.from_dict(item))
            else:
                raise TypeError(f"Expected Conversation or dict, got {type(item)}")
        return cls(conversations=parsed, **kwargs)

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        mapping: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Dataset:
        """Load a Dataset from a CSV file.

        Each row is treated as a single-turn conversation.  Use *mapping* to
        specify which CSV columns map to ``user_message``,
        ``assistant_message``, ``context``, and ``ground_truth``.

        Args:
            path: Path to the CSV file.
            mapping: Column name mapping.  Recognised keys:
                ``user`` (default ``"user_message"``),
                ``assistant`` (default ``"assistant_message"``),
                ``context`` (default ``"context"``),
                ``ground_truth`` (default ``"ground_truth"``),
                ``id`` (default ``"id"``).

        Example::

            ds = Dataset.from_csv("data.csv", mapping={"user": "question", "assistant": "answer"})
        """
        path = Path(path)
        mapping = mapping or {}
        col_user = mapping.get("user", "user_message")
        col_assistant = mapping.get("assistant", "assistant_message")
        col_context = mapping.get("context", "context")
        col_ground_truth = mapping.get("ground_truth", "ground_truth")
        col_id = mapping.get("id", "id")

        conversations: list[Conversation] = []
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                messages: list[Message] = []
                if col_user in row and row[col_user]:
                    messages.append(Message(role="user", content=row[col_user]))
                if col_assistant in row and row[col_assistant]:
                    messages.append(Message(role="assistant", content=row[col_assistant]))
                if not messages:
                    continue

                conv = Conversation(
                    messages=messages,
                    id=row.get(col_id, str(uuid.uuid4())),
                    context=row.get(col_context) or None,
                    ground_truth=row.get(col_ground_truth) or None,
                )
                conversations.append(conv)

        return cls(conversations=conversations, **kwargs)

    @classmethod
    def from_jsonl(cls, path: str | Path, **kwargs: Any) -> Dataset:
        """Load a Dataset from a JSON Lines file.

        Each line should be a JSON object with a ``messages`` key (and
        optionally ``context``, ``ground_truth``, ``id``, etc.).

        Example::

            ds = Dataset.from_jsonl("conversations.jsonl")
        """
        path = Path(path)
        conversations: list[Conversation] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                conversations.append(Conversation.from_dict(data))
        return cls(conversations=conversations, **kwargs)

    def __len__(self) -> int:
        return len(self.conversations)

    def __iter__(self):  # type: ignore[override]
        return iter(self.conversations)

    def __getitem__(self, idx: int) -> Conversation:
        return self.conversations[idx]

    def __repr__(self) -> str:
        return (
            f"Dataset(name={self.name!r}, conversations={len(self.conversations)})"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _score_colour(score: float) -> str:
    """Return an HTML colour based on score value."""
    if score >= 0.8:
        return "#2e7d32"  # green
    if score >= 0.5:
        return "#f57f17"  # amber
    return "#c62828"  # red
