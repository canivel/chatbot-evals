"""OpenTelemetry-inspired tracing for chatbot interactions.

The :class:`Tracer` captures hierarchical spans representing operations
(LLM calls, retrieval steps, tool invocations, etc.) and can convert the
recorded trace into :class:`~chatbot_evals.types.Conversation` objects
suitable for the evaluation engine.

Usage::

    tracer = Tracer(project="my-chatbot")

    with tracer.span("user_request") as root:
        root.set_attribute("user.message", user_msg)

        with tracer.span("retrieval") as retrieval:
            context = retrieve(user_msg)
            retrieval.set_attribute("documents", context)

        with tracer.span("llm_call") as llm:
            response = generate(user_msg, context)
            llm.set_attribute("model", "gpt-4o")
            llm.set_attribute("response", response)

    conversations = tracer.to_conversations()
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

import structlog
from pydantic import BaseModel, Field

from chatbot_evals.types import Conversation, Message

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------


class Span(BaseModel):
    """A single operation span (LLM call, retrieval, tool use, etc.).

    Spans form a tree: each span may have a *parent_id* pointing at its
    enclosing span.  Leaf spans typically represent atomic operations while
    root spans represent full user-request lifecycles.
    """

    span_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this span.",
    )
    parent_id: str | None = Field(
        default=None,
        description="Span ID of the parent span, or None for root spans.",
    )
    name: str = Field(..., description="Human-readable name of the operation.")
    start_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the span started.",
    )
    end_time: datetime | None = Field(
        default=None,
        description="When the span ended (None if still open).",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value attributes recorded on this span.",
    )
    events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Timestamped events recorded during the span.",
    )
    status: str = Field(
        default="ok",
        description="Span status: 'ok' or 'error'.",
    )

    # -- mutators ------------------------------------------------------------

    def set_attribute(self, key: str, value: Any) -> None:
        """Record an arbitrary attribute on this span.

        Args:
            key: Attribute name (use dotted namespaces, e.g. ``"llm.model"``).
            value: Attribute value (should be JSON-serialisable).
        """
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Append a timestamped event to the span.

        Args:
            name: Short event name, e.g. ``"cache_hit"``.
            attributes: Optional event-level attributes.
        """
        self.events.append(
            {
                "name": name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "attributes": attributes or {},
            }
        )

    def end(self) -> None:
        """Mark the span as ended (sets *end_time* to now)."""
        if self.end_time is None:
            self.end_time = datetime.now(timezone.utc)

    @property
    def duration_ms(self) -> float | None:
        """Wall-clock duration in milliseconds, or ``None`` if still open."""
        if self.end_time is None:
            return None
        delta = self.end_time - self.start_time
        return delta.total_seconds() * 1000.0


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class Tracer:
    """Traces chatbot interactions for evaluation.

    The tracer maintains an ordered list of :class:`Span` objects and an
    internal stack so that nested ``with tracer.span(...)`` blocks
    automatically set parent-child relationships.

    Args:
        project: Optional project name for organising traces.
        auto_eval: Reserved for future use -- when ``True`` the tracer will
            automatically trigger evaluation after each root span closes.
        metrics: Optional list of metric names to run during auto-eval.
    """

    def __init__(
        self,
        project: str | None = None,
        auto_eval: bool = False,
        metrics: list[str] | None = None,
    ) -> None:
        self.project = project
        self.auto_eval = auto_eval
        self.metrics = metrics or []
        self._spans: list[Span] = []
        self._span_stack: list[Span] = []

    # -- span context manager ------------------------------------------------

    @contextmanager
    def span(
        self,
        name: str,
        parent: Span | None = None,
    ) -> Generator[Span, None, None]:
        """Create a new span as a context manager.

        Within the ``with`` block the span is the *current* span; any
        nested ``tracer.span(...)`` calls will automatically become
        children of this span.

        Args:
            name: Human-readable name for the operation.
            parent: Explicit parent span.  If ``None``, the current
                top-of-stack span is used (or the span becomes a root).

        Yields:
            The newly created :class:`Span`.
        """
        parent_id: str | None = None
        if parent is not None:
            parent_id = parent.span_id
        elif self._span_stack:
            parent_id = self._span_stack[-1].span_id

        new_span = Span(name=name, parent_id=parent_id)
        self._spans.append(new_span)
        self._span_stack.append(new_span)

        try:
            yield new_span
        except Exception as exc:
            new_span.status = "error"
            new_span.set_attribute("error.type", type(exc).__name__)
            new_span.set_attribute("error.message", str(exc))
            raise
        finally:
            new_span.end()
            self._span_stack.pop()

    # -- conversion to conversations -----------------------------------------

    def to_conversations(self) -> list[Conversation]:
        """Export recorded traces as a list of :class:`Conversation` objects.

        Each *root* span (a span with no parent) becomes a separate
        conversation.  Child spans with ``user.message`` or ``response``
        attributes are mapped to conversation messages.

        Returns:
            List of :class:`Conversation` objects ready for evaluation.
        """
        root_spans = [s for s in self._spans if s.parent_id is None]
        conversations: list[Conversation] = []

        for root in root_spans:
            messages = self._extract_messages(root)
            context = self._extract_context(root)
            system_prompt = self._extract_system_prompt(root)

            conv = Conversation(
                messages=messages,
                context=context or None,
                system_prompt=system_prompt,
                metadata={
                    "trace_project": self.project,
                    "root_span_id": root.span_id,
                    "root_span_name": root.name,
                    "duration_ms": root.duration_ms,
                },
            )
            conversations.append(conv)

        logger.info(
            "tracer.to_conversations",
            project=self.project,
            root_spans=len(root_spans),
            conversations=len(conversations),
        )
        return conversations

    # -- export --------------------------------------------------------------

    def export_json(self, path: str) -> None:
        """Serialise all recorded spans to a JSON file.

        Args:
            path: Filesystem path for the output JSON file.
        """
        data = [span.model_dump(mode="json") for span in self._spans]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        logger.info("tracer.export_json", path=path, spans=len(data))

    def clear(self) -> None:
        """Discard all recorded spans and reset the tracer state."""
        self._spans.clear()
        self._span_stack.clear()
        logger.debug("tracer.cleared", project=self.project)

    # -- introspection -------------------------------------------------------

    @property
    def spans(self) -> list[Span]:
        """Return a copy of all recorded spans."""
        return list(self._spans)

    @property
    def root_spans(self) -> list[Span]:
        """Return only root-level spans (those without a parent)."""
        return [s for s in self._spans if s.parent_id is None]

    # -- internal helpers ----------------------------------------------------

    def _children_of(self, parent: Span) -> list[Span]:
        """Return direct children of *parent*, in recording order."""
        return [s for s in self._spans if s.parent_id == parent.span_id]

    def _descendants_of(self, parent: Span) -> list[Span]:
        """Return all descendants of *parent* (breadth-first)."""
        result: list[Span] = []
        queue = self._children_of(parent)
        while queue:
            current = queue.pop(0)
            result.append(current)
            queue.extend(self._children_of(current))
        return result

    def _extract_messages(self, root: Span) -> list[Message]:
        """Walk the span tree under *root* and build a message list."""
        messages: list[Message] = []
        all_spans = [root, *self._descendants_of(root)]

        for span in all_spans:
            # Check for user message
            user_msg = (
                span.attributes.get("user.message")
                or span.attributes.get("user_message")
                or span.attributes.get("input")
            )
            if user_msg:
                messages.append(
                    Message(
                        role="user",
                        content=str(user_msg),
                        timestamp=span.start_time,
                        metadata={"span_id": span.span_id, "span_name": span.name},
                    )
                )

            # Check for assistant response
            assistant_msg = (
                span.attributes.get("response")
                or span.attributes.get("assistant.message")
                or span.attributes.get("output")
            )
            if assistant_msg:
                messages.append(
                    Message(
                        role="assistant",
                        content=str(assistant_msg),
                        timestamp=span.end_time or span.start_time,
                        metadata={
                            "span_id": span.span_id,
                            "span_name": span.name,
                            "model": span.attributes.get("model"),
                        },
                    )
                )

        # Sort by timestamp for correct ordering
        messages.sort(
            key=lambda m: m.timestamp or datetime.min.replace(tzinfo=timezone.utc)
        )
        return messages

    def _extract_context(self, root: Span) -> list[str]:
        """Collect retrieved-context fragments from the span tree."""
        context: list[str] = []
        all_spans = [root, *self._descendants_of(root)]

        for span in all_spans:
            ctx = (
                span.attributes.get("context")
                or span.attributes.get("retrieved_context")
                or span.attributes.get("documents")
            )
            if ctx is None:
                continue
            if isinstance(ctx, list):
                context.extend(str(item) for item in ctx)
            else:
                context.append(str(ctx))

        return context

    def _extract_system_prompt(self, root: Span) -> str | None:
        """Find the system prompt, if any, in the span tree."""
        all_spans = [root, *self._descendants_of(root)]
        for span in all_spans:
            prompt = (
                span.attributes.get("system_prompt")
                or span.attributes.get("system.prompt")
            )
            if prompt:
                return str(prompt)
        return None


# ---------------------------------------------------------------------------
# Quick context manager
# ---------------------------------------------------------------------------


@contextmanager
def trace_context(
    name: str,
    project: str | None = None,
) -> Generator[Tracer, None, None]:
    """Convenience context manager that creates a :class:`Tracer` and opens
    a root span in one step.

    Usage::

        with trace_context("my-request", project="chatbot") as tracer:
            with tracer.span("retrieval") as ret:
                ret.set_attribute("documents", docs)
            with tracer.span("llm_call") as llm:
                llm.set_attribute("response", answer)

        conversations = tracer.to_conversations()

    Args:
        name: Name for the implicit root span.
        project: Optional project label.

    Yields:
        A :class:`Tracer` instance with an open root span.
    """
    tracer = Tracer(project=project)
    with tracer.span(name):
        yield tracer
