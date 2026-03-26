"""Transparent wrapper around the OpenAI client that auto-traces conversations.

Usage::

    from openai import AsyncOpenAI
    from chatbot_evals.integrations import OpenAIWrapper

    client = AsyncOpenAI()
    traced = OpenAIWrapper(client, metrics=["faithfulness", "toxicity"])

    # Use exactly like the normal client -- tracing happens automatically.
    response = await traced.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hello"}],
    )

    # Retrieve traced conversations and eval results.
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


class _CompletionsProxy:
    """Proxy for ``client.chat.completions`` that intercepts ``create``."""

    def __init__(self, wrapper: OpenAIWrapper) -> None:
        self._wrapper = wrapper

    async def create(self, **kwargs: Any) -> Any:
        """Intercept a chat completion call, trace it, then return the
        original response object unmodified.
        """
        # Respect sample rate
        if random.random() > self._wrapper.sample_rate:
            return await self._wrapper._client.chat.completions.create(**kwargs)

        messages_raw: list[dict[str, str]] = kwargs.get("messages", [])
        model: str = kwargs.get("model", "unknown")

        with self._wrapper._tracer.span("openai_chat_completion") as span:
            span.set_attribute("model", model)
            span.set_attribute("provider", "openai")

            # Record the user message(s)
            for msg in messages_raw:
                if msg.get("role") == "user":
                    span.set_attribute("user.message", msg["content"])
                    break

            # Record system prompt if present
            for msg in messages_raw:
                if msg.get("role") == "system":
                    span.set_attribute("system_prompt", msg["content"])
                    break

            response = await self._wrapper._client.chat.completions.create(**kwargs)

            # Extract response content
            content = ""
            if response.choices:
                content = response.choices[0].message.content or ""
            span.set_attribute("response", content)

            # Record usage if available
            if response.usage:
                span.set_attribute(
                    "usage.prompt_tokens", response.usage.prompt_tokens
                )
                span.set_attribute(
                    "usage.completion_tokens", response.usage.completion_tokens
                )
                span.set_attribute(
                    "usage.total_tokens", response.usage.total_tokens
                )

        # Store the full conversation
        now = datetime.now(timezone.utc)
        sdk_messages = [
            Message(
                role=m["role"],
                content=m["content"],
                timestamp=now,
            )
            for m in messages_raw
            if m.get("content")
        ]
        sdk_messages.append(
            Message(role="assistant", content=content, timestamp=now)
        )

        # Extract system prompt and context for the Conversation
        system_prompt: str | None = None
        for m in messages_raw:
            if m.get("role") == "system":
                system_prompt = m["content"]
                break

        conv = Conversation(
            id=str(uuid.uuid4()),
            messages=sdk_messages,
            system_prompt=system_prompt,
            metadata={"model": model, "provider": "openai"},
        )
        self._wrapper._conversations.append(conv)

        return response


class _ChatProxy:
    """Proxy for ``client.chat`` exposing ``completions``."""

    def __init__(self, wrapper: OpenAIWrapper) -> None:
        self.completions = _CompletionsProxy(wrapper)


# ---------------------------------------------------------------------------
# OpenAIWrapper
# ---------------------------------------------------------------------------


class OpenAIWrapper:
    """Wraps an OpenAI client to auto-trace and optionally evaluate calls.

    The wrapper is a transparent proxy: it forwards all ``chat.completions``
    calls to the underlying client while recording traces and conversations.

    Args:
        client: An ``openai.AsyncOpenAI`` instance (or compatible).
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
        self._tracer = Tracer(project="openai-wrapper", metrics=self.metrics)
        self._conversations: list[Conversation] = []

        # Expose the proxy
        self.chat = _ChatProxy(self)

        logger.info(
            "openai_wrapper.init",
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

        This is a convenience method that imports the evaluation engine
        at call-time to avoid circular imports and to keep the wrapper
        lightweight when auto-eval is not used.

        Returns:
            A report dictionary with per-conversation and aggregate scores.
        """
        conversations = self.get_conversations()
        if not conversations:
            logger.warning("openai_wrapper.get_eval_report.no_conversations")
            return {"conversations_evaluated": 0, "results": []}

        logger.info(
            "openai_wrapper.get_eval_report",
            conversations=len(conversations),
            metrics=self.metrics,
        )

        # Defer to the evaluation engine (if installed in the same environment)
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
                "openai_wrapper.get_eval_report.engine_not_available",
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

    # -- pass-through for non-chat attributes --------------------------------

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the underlying client for any
        attribute not explicitly handled by the wrapper.
        """
        return getattr(self._client, name)
