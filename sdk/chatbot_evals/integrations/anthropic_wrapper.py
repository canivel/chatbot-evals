"""Transparent wrapper around the Anthropic client that auto-traces conversations.

Usage::

    from anthropic import AsyncAnthropic
    from chatbot_evals.integrations import AnthropicWrapper

    client = AsyncAnthropic()
    traced = AnthropicWrapper(client, metrics=["faithfulness"])

    response = await traced.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello"}],
    )

    conversations = traced.get_conversations()
    report = await traced.get_eval_report()
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from chatbot_evals.tracing.tracer import Tracer
from chatbot_evals.types import Conversation, Message

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal proxy objects
# ---------------------------------------------------------------------------


class _MessagesProxy:
    """Proxy for ``client.messages`` that intercepts ``create``."""

    def __init__(self, wrapper: AnthropicWrapper) -> None:
        self._wrapper = wrapper

    async def create(self, **kwargs: Any) -> Any:
        """Intercept a messages.create call, trace it, then return the
        original response unmodified.
        """
        if random.random() > self._wrapper.sample_rate:
            return await self._wrapper._client.messages.create(**kwargs)

        messages_raw: list[dict[str, Any]] = kwargs.get("messages", [])
        model: str = kwargs.get("model", "unknown")
        system_prompt: str | None = kwargs.get("system")

        with self._wrapper._tracer.span("anthropic_messages_create") as span:
            span.set_attribute("model", model)
            span.set_attribute("provider", "anthropic")

            if system_prompt:
                span.set_attribute("system_prompt", system_prompt)

            # Record the last user message
            for msg in reversed(messages_raw):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    # Anthropic content can be a list of blocks
                    if isinstance(content, list):
                        text_parts = [
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict)
                            and block.get("type") == "text"
                        ]
                        content = " ".join(text_parts)
                    span.set_attribute("user.message", content)
                    break

            response = await self._wrapper._client.messages.create(**kwargs)

            # Extract response content
            response_text = ""
            if response.content:
                text_blocks = [
                    block.text
                    for block in response.content
                    if hasattr(block, "text")
                ]
                response_text = " ".join(text_blocks)
            span.set_attribute("response", response_text)

            # Record usage
            if hasattr(response, "usage") and response.usage:
                span.set_attribute(
                    "usage.input_tokens", response.usage.input_tokens
                )
                span.set_attribute(
                    "usage.output_tokens", response.usage.output_tokens
                )

        # Build the SDK conversation
        now = datetime.now(timezone.utc)
        sdk_messages: list[Message] = []

        if system_prompt:
            sdk_messages.append(
                Message(role="system", content=system_prompt, timestamp=now)
            )

        for msg in messages_raw:
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                content = " ".join(text_parts)
            sdk_messages.append(
                Message(role=msg["role"], content=str(content), timestamp=now)
            )

        sdk_messages.append(
            Message(role="assistant", content=response_text, timestamp=now)
        )

        conv = Conversation(
            id=str(uuid.uuid4()),
            messages=sdk_messages,
            system_prompt=system_prompt,
            metadata={"model": model, "provider": "anthropic"},
        )
        self._wrapper._conversations.append(conv)

        return response


# ---------------------------------------------------------------------------
# AnthropicWrapper
# ---------------------------------------------------------------------------


class AnthropicWrapper:
    """Wraps an Anthropic client to auto-trace and optionally evaluate calls.

    The wrapper is a transparent proxy: it forwards all ``messages.create``
    calls to the underlying client while recording traces and conversations.

    Args:
        client: An ``anthropic.AsyncAnthropic`` instance (or compatible).
        metrics: List of metric names to run during auto-evaluation.
        auto_eval: If ``True``, automatically evaluate after each call
            (reserved for future implementation).
        sample_rate: Fraction of calls to trace (``1.0`` = all, ``0.1`` = 10%).
    """

    def __init__(
        self,
        client: Any,
        metrics: list[str] | None = None,
        auto_eval: bool = True,
        sample_rate: float = 1.0,
    ) -> None:
        self._client = client
        self.metrics = metrics or []
        self.auto_eval = auto_eval
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self._tracer = Tracer(project="anthropic-wrapper", metrics=self.metrics)
        self._conversations: list[Conversation] = []

        # Expose the proxy
        self.messages = _MessagesProxy(self)

        logger.info(
            "anthropic_wrapper.init",
            metrics=self.metrics,
            auto_eval=self.auto_eval,
            sample_rate=self.sample_rate,
        )

    # -- public API ----------------------------------------------------------

    def get_conversations(self) -> list[Conversation]:
        """Return all conversations recorded so far.

        Returns:
            List of :class:`Conversation` objects.
        """
        return list(self._conversations)

    async def get_eval_report(self) -> dict[str, Any]:
        """Evaluate all recorded conversations and return a report dict.

        Returns:
            A report dictionary with per-conversation and aggregate scores.
        """
        conversations = self.get_conversations()
        if not conversations:
            logger.warning("anthropic_wrapper.get_eval_report.no_conversations")
            return {"conversations_evaluated": 0, "results": []}

        logger.info(
            "anthropic_wrapper.get_eval_report",
            conversations=len(conversations),
            metrics=self.metrics,
        )

        try:
            from evalplatform.eval_engine.engine import EvalConfig, EvalEngine
            from evalplatform.eval_engine.metrics.base import (
                ConversationTurn,
                EvalContext,
            )

            engine = EvalEngine()
            eval_contexts = [
                EvalContext(
                    conversation=[
                        ConversationTurn(
                            role=m.role,
                            content=m.content,
                            timestamp=m.timestamp,
                            metadata=m.metadata,
                        )
                        for m in conv.messages
                    ],
                    ground_truth=conv.ground_truth,
                    retrieved_context=(
                        [conv.context]
                        if isinstance(conv.context, str)
                        else (conv.context or [])
                    ),
                    system_prompt=conv.system_prompt,
                    metadata=conv.metadata,
                )
                for conv in conversations
            ]
            config = (
                EvalConfig(metric_names=self.metrics)
                if self.metrics
                else EvalConfig()
            )
            run = await engine.run_eval(eval_contexts, config)
            return run.model_dump(mode="json")
        except ImportError:
            logger.warning(
                "anthropic_wrapper.get_eval_report.engine_not_available",
                hint="Install the full evalplatform package for auto-evaluation.",
            )
            return {
                "conversations_evaluated": len(conversations),
                "results": [],
                "error": "Evaluation engine not available. Install evalplatform.",
            }

    def clear(self) -> None:
        """Reset all recorded conversations and tracer state."""
        self._conversations.clear()
        self._tracer.clear()

    # -- pass-through for non-messages attributes ----------------------------

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the underlying client for any
        attribute not explicitly handled by the wrapper.
        """
        return getattr(self._client, name)
