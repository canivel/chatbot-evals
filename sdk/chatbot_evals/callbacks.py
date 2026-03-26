"""Callback system for evaluation progress tracking.

Provides an abstract :class:`BaseCallback` interface and several concrete
implementations for reporting progress during batch evaluation runs.

Example::

    from chatbot_evals.callbacks import PrintCallback, TqdmCallback

    report = await ce.evaluate(dataset, callbacks=[PrintCallback()])
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from chatbot_evals.types import EvalResult, EvalReport

logger = structlog.get_logger(__name__)


class BaseCallback(ABC):
    """Abstract base class for evaluation callbacks.

    Subclass this to create custom progress reporters, loggers, or
    integrations.
    """

    @abstractmethod
    def on_eval_start(self, total_conversations: int, metrics: list[str]) -> None:
        """Called when an evaluation run begins.

        Args:
            total_conversations: Number of conversations to evaluate.
            metrics: List of metric names that will be computed.
        """

    @abstractmethod
    def on_conversation_evaluated(
        self,
        index: int,
        total: int,
        result: EvalResult,
    ) -> None:
        """Called after a single conversation has been evaluated.

        Args:
            index: 1-based index of the conversation just evaluated.
            total: Total number of conversations in the run.
            result: The evaluation result for this conversation.
        """

    @abstractmethod
    def on_metric_computed(
        self,
        metric_name: str,
        score: float,
        conversation_id: str,
    ) -> None:
        """Called after an individual metric is computed.

        Args:
            metric_name: Name of the metric.
            score: The computed score.
            conversation_id: ID of the conversation.
        """

    @abstractmethod
    def on_eval_complete(self, report: EvalReport) -> None:
        """Called when the entire evaluation run is finished.

        Args:
            report: The final evaluation report.
        """

    @abstractmethod
    def on_error(self, error: Exception, context: dict[str, Any] | None = None) -> None:
        """Called when an error occurs during evaluation.

        Args:
            error: The exception that was raised.
            context: Optional context about where the error occurred.
        """


# ---------------------------------------------------------------------------
# Concrete implementations
# ---------------------------------------------------------------------------


class PrintCallback(BaseCallback):
    """Prints evaluation progress to stdout.

    Example::

        report = await ce.evaluate(dataset, callbacks=[PrintCallback()])
    """

    def __init__(self, *, show_scores: bool = True) -> None:
        self._show_scores = show_scores

    def on_eval_start(self, total_conversations: int, metrics: list[str]) -> None:
        print(
            f"[chatbot-evals] Starting evaluation: "
            f"{total_conversations} conversations, "
            f"metrics={metrics}"
        )

    def on_conversation_evaluated(
        self, index: int, total: int, result: EvalResult
    ) -> None:
        score_str = ""
        if self._show_scores:
            score_str = f" | overall={result.overall_score:.3f}"
        print(f"[chatbot-evals] [{index}/{total}] {result.conversation_id}{score_str}")

    def on_metric_computed(
        self, metric_name: str, score: float, conversation_id: str
    ) -> None:
        if self._show_scores:
            print(f"  -> {metric_name}: {score:.3f}")

    def on_eval_complete(self, report: EvalReport) -> None:
        print(f"[chatbot-evals] Evaluation complete: {len(report.results)} conversations")
        if report.metric_averages:
            for metric, avg in report.metric_averages.items():
                print(f"  {metric}: {avg:.3f}")

    def on_error(self, error: Exception, context: dict[str, Any] | None = None) -> None:
        print(f"[chatbot-evals] ERROR: {error}")
        if context:
            print(f"  context: {context}")


class TqdmCallback(BaseCallback):
    """Shows a tqdm progress bar during evaluation.

    Requires tqdm to be installed (``pip install tqdm``).

    Example::

        report = await ce.evaluate(dataset, callbacks=[TqdmCallback()])
    """

    def __init__(self, *, desc: str = "Evaluating") -> None:
        self._desc = desc
        self._pbar: Any = None

    def on_eval_start(self, total_conversations: int, metrics: list[str]) -> None:
        try:
            from tqdm import tqdm
        except ImportError as exc:
            raise ImportError(
                "tqdm is required for TqdmCallback. Install it with: pip install tqdm"
            ) from exc
        self._pbar = tqdm(total=total_conversations, desc=self._desc, unit="conv")

    def on_conversation_evaluated(
        self, index: int, total: int, result: EvalResult
    ) -> None:
        if self._pbar is not None:
            self._pbar.update(1)
            self._pbar.set_postfix(score=f"{result.overall_score:.3f}")

    def on_metric_computed(
        self, metric_name: str, score: float, conversation_id: str
    ) -> None:
        pass  # tqdm bar is enough feedback

    def on_eval_complete(self, report: EvalReport) -> None:
        if self._pbar is not None:
            self._pbar.close()
            self._pbar = None

    def on_error(self, error: Exception, context: dict[str, Any] | None = None) -> None:
        if self._pbar is not None:
            self._pbar.write(f"ERROR: {error}")


class FileCallback(BaseCallback):
    """Writes evaluation results to a JSON Lines file as they complete.

    Each line is a JSON object representing one conversation's result.

    Args:
        path: Destination file path.

    Example::

        report = await ce.evaluate(dataset, callbacks=[FileCallback("results.jsonl")])
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._fh: Any = None

    def on_eval_start(self, total_conversations: int, metrics: list[str]) -> None:
        self._fh = self._path.open("w", encoding="utf-8")
        header = {
            "event": "eval_start",
            "total_conversations": total_conversations,
            "metrics": metrics,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._fh.write(json.dumps(header) + "\n")
        self._fh.flush()

    def on_conversation_evaluated(
        self, index: int, total: int, result: EvalResult
    ) -> None:
        if self._fh is not None:
            row = {
                "event": "conversation_evaluated",
                "index": index,
                "total": total,
                "conversation_id": result.conversation_id,
                "overall_score": result.overall_score,
                "scores": result.scores,
                "flags": result.flags,
                "timestamp": result.timestamp.isoformat(),
            }
            self._fh.write(json.dumps(row) + "\n")
            self._fh.flush()

    def on_metric_computed(
        self, metric_name: str, score: float, conversation_id: str
    ) -> None:
        pass  # individual metric events not written to avoid excessive output

    def on_eval_complete(self, report: EvalReport) -> None:
        if self._fh is not None:
            footer = {
                "event": "eval_complete",
                "total_results": len(report.results),
                "metric_averages": report.metric_averages,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._fh.write(json.dumps(footer) + "\n")
            self._fh.close()
            self._fh = None

    def on_error(self, error: Exception, context: dict[str, Any] | None = None) -> None:
        if self._fh is not None:
            row = {
                "event": "error",
                "error": str(error),
                "context": context,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._fh.write(json.dumps(row) + "\n")
            self._fh.flush()


class WebhookCallback(BaseCallback):
    """POSTs evaluation results to a URL as they complete.

    Uses ``urllib`` from the standard library so no extra dependency is
    required.

    Args:
        url: The webhook endpoint URL.
        headers: Optional extra HTTP headers.

    Example::

        report = await ce.evaluate(
            dataset,
            callbacks=[WebhookCallback("https://example.com/webhook")],
        )
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self._url = url
        self._headers = headers or {}

    def _post(self, payload: dict[str, Any]) -> None:
        """Send a JSON POST request (fire-and-forget, errors are logged)."""
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=data,
            headers={
                "Content-Type": "application/json",
                **self._headers,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                _ = resp.read()
        except Exception as exc:
            logger.warning("webhook_post_failed", url=self._url, error=str(exc))

    def on_eval_start(self, total_conversations: int, metrics: list[str]) -> None:
        self._post({
            "event": "eval_start",
            "total_conversations": total_conversations,
            "metrics": metrics,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def on_conversation_evaluated(
        self, index: int, total: int, result: EvalResult
    ) -> None:
        self._post({
            "event": "conversation_evaluated",
            "index": index,
            "total": total,
            "conversation_id": result.conversation_id,
            "overall_score": result.overall_score,
            "scores": result.scores,
        })

    def on_metric_computed(
        self, metric_name: str, score: float, conversation_id: str
    ) -> None:
        pass  # batched with conversation_evaluated to reduce HTTP noise

    def on_eval_complete(self, report: EvalReport) -> None:
        self._post({
            "event": "eval_complete",
            "total_results": len(report.results),
            "metric_averages": report.metric_averages,
            "summary": report.summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def on_error(self, error: Exception, context: dict[str, Any] | None = None) -> None:
        self._post({
            "event": "error",
            "error": str(error),
            "context": context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
