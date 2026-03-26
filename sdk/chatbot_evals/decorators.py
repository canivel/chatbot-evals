"""Decorators for monitoring and tracing chatbot functions.

Provides decorators that wrap chatbot handler functions to automatically
capture input/output and optionally run evaluations.

Example::

    import chatbot_evals as ce

    @ce.trace(metrics=["faithfulness", "toxicity"])
    async def my_chatbot(user_message: str) -> str:
        response = await call_llm(user_message)
        return response

    # Each call to my_chatbot will now be traced and evaluated.
    answer = await my_chatbot("What is your return policy?")
"""

from __future__ import annotations

import asyncio
import functools
import random
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Generator, AsyncGenerator

import structlog

from chatbot_evals.types import Conversation, EvalResult, Message

logger = structlog.get_logger(__name__)

# Module-level storage for traced conversations
_trace_log: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# @trace
# ---------------------------------------------------------------------------


def trace(
    metrics: list[str] | None = None,
    judge_model: str | None = None,
    project: str | None = None,
) -> Callable:
    """Decorator that captures input/output and runs evaluation.

    Wraps an async or sync chatbot function so that every invocation is
    automatically evaluated against the specified metrics.

    The decorated function's first positional argument is treated as the
    user message and the return value as the assistant response.

    Args:
        metrics: Metric names to evaluate on each call.
        judge_model: LLM judge model override.
        project: Project name for grouping traces.

    Returns:
        A decorator.

    Example::

        @trace(metrics=["faithfulness", "toxicity"])
        async def my_chatbot(user_message: str) -> str:
            return await call_llm(user_message)

        # Traced automatically:
        answer = await my_chatbot("Hello!")
    """

    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                user_message = args[0] if args else kwargs.get("user_message", "")
                start = datetime.now(timezone.utc)

                response = await fn(*args, **kwargs)

                end = datetime.now(timezone.utc)
                latency = (end - start).total_seconds()

                # Run evaluation in the background
                eval_result = await _evaluate_trace(
                    user_message=str(user_message),
                    assistant_response=str(response),
                    metrics=metrics,
                    judge_model=judge_model,
                    latency=latency,
                    project=project,
                )

                # Store trace
                _trace_log.append({
                    "id": str(uuid.uuid4()),
                    "function": fn.__qualname__,
                    "user_message": str(user_message),
                    "assistant_response": str(response),
                    "eval_result": eval_result,
                    "latency": latency,
                    "timestamp": start.isoformat(),
                    "project": project,
                })

                logger.debug(
                    "trace_complete",
                    function=fn.__qualname__,
                    overall_score=eval_result.overall_score if eval_result else None,
                    latency=latency,
                )

                return response

            async_wrapper._traces = _trace_log  # type: ignore[attr-defined]
            return async_wrapper

        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                user_message = args[0] if args else kwargs.get("user_message", "")
                start = datetime.now(timezone.utc)

                response = fn(*args, **kwargs)

                end = datetime.now(timezone.utc)
                latency = (end - start).total_seconds()

                # Run evaluation synchronously
                from chatbot_evals.client import _run_sync

                eval_result = _run_sync(
                    _evaluate_trace(
                        user_message=str(user_message),
                        assistant_response=str(response),
                        metrics=metrics,
                        judge_model=judge_model,
                        latency=latency,
                        project=project,
                    )
                )

                _trace_log.append({
                    "id": str(uuid.uuid4()),
                    "function": fn.__qualname__,
                    "user_message": str(user_message),
                    "assistant_response": str(response),
                    "eval_result": eval_result,
                    "latency": latency,
                    "timestamp": start.isoformat(),
                    "project": project,
                })

                return response

            sync_wrapper._traces = _trace_log  # type: ignore[attr-defined]
            return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# @monitor
# ---------------------------------------------------------------------------


def monitor(
    metrics: list[str] | None = None,
    sample_rate: float = 1.0,
    judge_model: str | None = None,
    project: str | None = None,
) -> Callable:
    """Decorator that samples and evaluates chatbot calls asynchronously.

    Unlike :func:`trace`, ``monitor`` does not block the response.
    Evaluation is scheduled as a background task, and only a fraction of
    calls (controlled by *sample_rate*) are evaluated.

    Args:
        metrics: Metric names to evaluate.
        sample_rate: Fraction of calls to evaluate (0.0 - 1.0).
        judge_model: LLM judge model override.
        project: Project name for grouping.

    Returns:
        A decorator.

    Example::

        @monitor(metrics=["toxicity"], sample_rate=0.1)
        async def chatbot(user_message: str) -> str:
            return await call_llm(user_message)
    """

    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                user_message = args[0] if args else kwargs.get("user_message", "")
                start = datetime.now(timezone.utc)

                response = await fn(*args, **kwargs)

                end = datetime.now(timezone.utc)
                latency = (end - start).total_seconds()

                # Sample
                if random.random() <= sample_rate:
                    # Schedule evaluation as a background task (fire-and-forget)
                    asyncio.ensure_future(
                        _evaluate_and_log_trace(
                            fn_name=fn.__qualname__,
                            user_message=str(user_message),
                            assistant_response=str(response),
                            metrics=metrics,
                            judge_model=judge_model,
                            latency=latency,
                            project=project,
                        )
                    )

                return response

            return async_wrapper

        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                user_message = args[0] if args else kwargs.get("user_message", "")
                start = datetime.now(timezone.utc)

                response = fn(*args, **kwargs)

                end = datetime.now(timezone.utc)
                latency = (end - start).total_seconds()

                if random.random() <= sample_rate:
                    _trace_log.append({
                        "id": str(uuid.uuid4()),
                        "function": fn.__qualname__,
                        "user_message": str(user_message),
                        "assistant_response": str(response),
                        "eval_result": None,  # async eval not possible in sync context
                        "latency": latency,
                        "timestamp": start.isoformat(),
                        "project": project,
                        "pending_eval": True,
                    })

                return response

            return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# @log_conversation
# ---------------------------------------------------------------------------


def log_conversation(
    project: str | None = None,
) -> Callable:
    """Decorator that logs chatbot input/output without evaluating.

    Captures the user message and assistant response for later analysis
    without incurring any evaluation overhead.

    Args:
        project: Project name for grouping.

    Returns:
        A decorator.

    Example::

        @log_conversation(project="support-bot")
        async def chatbot(user_message: str) -> str:
            return await call_llm(user_message)
    """

    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                user_message = args[0] if args else kwargs.get("user_message", "")
                start = datetime.now(timezone.utc)

                response = await fn(*args, **kwargs)

                end = datetime.now(timezone.utc)
                latency = (end - start).total_seconds()

                _trace_log.append({
                    "id": str(uuid.uuid4()),
                    "function": fn.__qualname__,
                    "user_message": str(user_message),
                    "assistant_response": str(response),
                    "eval_result": None,
                    "latency": latency,
                    "timestamp": start.isoformat(),
                    "project": project,
                })

                logger.debug(
                    "conversation_logged",
                    function=fn.__qualname__,
                    latency=latency,
                )

                return response

            return async_wrapper

        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                user_message = args[0] if args else kwargs.get("user_message", "")
                start = datetime.now(timezone.utc)

                response = fn(*args, **kwargs)

                end = datetime.now(timezone.utc)
                latency = (end - start).total_seconds()

                _trace_log.append({
                    "id": str(uuid.uuid4()),
                    "function": fn.__qualname__,
                    "user_message": str(user_message),
                    "assistant_response": str(response),
                    "eval_result": None,
                    "latency": latency,
                    "timestamp": start.isoformat(),
                    "project": project,
                })

                return response

            return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# TraceContext
# ---------------------------------------------------------------------------


class TraceContext:
    """Context manager for manual tracing spans.

    Use this when you need fine-grained control over what is captured,
    such as multi-step pipelines or RAG flows.

    Example::

        async with TraceContext(project="my-bot") as ctx:
            ctx.log_user_message("What is AI?")
            response = await call_llm("What is AI?")
            ctx.log_assistant_response(response)
            ctx.set_context("AI is artificial intelligence.")

        # ctx.result contains the evaluation result (if metrics were specified)
    """

    def __init__(
        self,
        metrics: list[str] | None = None,
        judge_model: str | None = None,
        project: str | None = None,
    ) -> None:
        self._metrics = metrics
        self._judge_model = judge_model
        self._project = project
        self._messages: list[Message] = []
        self._context: str | None = None
        self._ground_truth: str | None = None
        self._system_prompt: str | None = None
        self._metadata: dict[str, Any] = {}
        self._start: datetime | None = None
        self.result: EvalResult | None = None

    def log_user_message(self, content: str) -> None:
        """Record a user message."""
        self._messages.append(Message(role="user", content=content))

    def log_assistant_response(self, content: str) -> None:
        """Record an assistant response."""
        self._messages.append(Message(role="assistant", content=content))

    def log_system_message(self, content: str) -> None:
        """Record a system message."""
        self._messages.append(Message(role="system", content=content))

    def set_context(self, context: str) -> None:
        """Set the retrieved context for evaluation."""
        self._context = context

    def set_ground_truth(self, ground_truth: str) -> None:
        """Set the expected correct answer."""
        self._ground_truth = ground_truth

    def set_system_prompt(self, system_prompt: str) -> None:
        """Set the system prompt."""
        self._system_prompt = system_prompt

    def set_metadata(self, **kwargs: Any) -> None:
        """Set arbitrary metadata."""
        self._metadata.update(kwargs)

    async def __aenter__(self) -> TraceContext:
        self._start = datetime.now(timezone.utc)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            logger.warning("trace_context_error", error=str(exc_val))
            return

        end = datetime.now(timezone.utc)
        latency = (end - self._start).total_seconds() if self._start else 0

        if self._messages and self._metrics:
            conversation = Conversation(
                messages=self._messages,
                context=self._context,
                ground_truth=self._ground_truth,
                system_prompt=self._system_prompt,
                metadata={**self._metadata, "latency": latency},
            )

            from chatbot_evals.client import ChatbotEvals

            client = ChatbotEvals(judge_model=self._judge_model or "gpt-4o")
            self.result = await client.evaluate(conversation, metrics=self._metrics)

        # Log the span
        _trace_log.append({
            "id": str(uuid.uuid4()),
            "type": "trace_context",
            "messages": [m.model_dump() for m in self._messages],
            "eval_result": self.result,
            "latency": latency,
            "timestamp": (self._start or datetime.now(timezone.utc)).isoformat(),
            "project": self._project,
        })

    def __enter__(self) -> TraceContext:
        self._start = datetime.now(timezone.utc)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            return

        end = datetime.now(timezone.utc)
        latency = (end - self._start).total_seconds() if self._start else 0

        _trace_log.append({
            "id": str(uuid.uuid4()),
            "type": "trace_context",
            "messages": [m.model_dump() for m in self._messages],
            "eval_result": None,
            "latency": latency,
            "timestamp": (self._start or datetime.now(timezone.utc)).isoformat(),
            "project": self._project,
        })


def get_traces() -> list[dict[str, Any]]:
    """Return all captured traces.

    Returns:
        A list of trace dicts recorded by ``@trace``, ``@monitor``,
        ``@log_conversation``, or :class:`TraceContext`.
    """
    return list(_trace_log)


def clear_traces() -> None:
    """Clear all captured traces."""
    _trace_log.clear()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _evaluate_trace(
    user_message: str,
    assistant_response: str,
    metrics: list[str] | None,
    judge_model: str | None,
    latency: float,
    project: str | None,
) -> EvalResult | None:
    """Build a Conversation from trace data and evaluate it."""
    if not metrics:
        return None

    from chatbot_evals.client import ChatbotEvals

    conversation = Conversation(
        messages=[
            Message(role="user", content=user_message),
            Message(role="assistant", content=assistant_response),
        ],
        metadata={"latency": latency, "project": project},
    )

    client = ChatbotEvals(judge_model=judge_model or "gpt-4o")
    try:
        return await client.evaluate(conversation, metrics=metrics)
    except Exception as exc:
        logger.error("trace_eval_failed", error=str(exc))
        return None


async def _evaluate_and_log_trace(
    fn_name: str,
    user_message: str,
    assistant_response: str,
    metrics: list[str] | None,
    judge_model: str | None,
    latency: float,
    project: str | None,
) -> None:
    """Evaluate and log a trace (used by @monitor for fire-and-forget)."""
    eval_result = await _evaluate_trace(
        user_message=user_message,
        assistant_response=assistant_response,
        metrics=metrics,
        judge_model=judge_model,
        latency=latency,
        project=project,
    )

    _trace_log.append({
        "id": str(uuid.uuid4()),
        "function": fn_name,
        "user_message": user_message,
        "assistant_response": assistant_response,
        "eval_result": eval_result,
        "latency": latency,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": project,
    })
