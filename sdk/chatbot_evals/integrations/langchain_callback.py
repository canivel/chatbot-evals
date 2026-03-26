"""LangChain callback handler that traces LLM calls for evaluation.

Usage::

    from chatbot_evals.integrations import ChatbotEvalsCallbackHandler

    handler = ChatbotEvalsCallbackHandler(metrics=["faithfulness"])
    chain = LLMChain(..., callbacks=[handler])
    chain.run("Hello")

    conversations = handler.get_conversations()
    report = await handler.get_eval_report()

The handler captures LLM inputs/outputs, retriever results, and chain
metadata, converting them into :class:`~chatbot_evals.types.Conversation`
objects.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from chatbot_evals.tracing.tracer import Tracer
from chatbot_evals.types import Conversation, Message

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# LangChain base class import (deferred to avoid hard dependency)
# ---------------------------------------------------------------------------


def _get_base_callback_handler() -> type:
    """Import and return ``langchain_core.callbacks.BaseCallbackHandler``.

    Returns a no-op stub if langchain-core is not installed so the module
    can still be *imported* (but not *used*) without the dependency.
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler  # type: ignore[import-untyped]

        return BaseCallbackHandler
    except ImportError:

        class _StubBaseCallbackHandler:
            """Placeholder when langchain-core is not installed."""

            pass

        return _StubBaseCallbackHandler


_BaseCallbackHandler = _get_base_callback_handler()


# ---------------------------------------------------------------------------
# Callback Handler
# ---------------------------------------------------------------------------


class ChatbotEvalsCallbackHandler(_BaseCallbackHandler):  # type: ignore[misc]
    """LangChain callback handler that traces LLM calls and chain runs
    for chatbot evaluation.

    The handler records every LLM start/end and retriever result, then
    provides :meth:`get_conversations` and :meth:`get_eval_report` for
    downstream evaluation.

    Args:
        metrics: List of metric names to run during evaluation.
        project: Project name for trace organisation.
        sample_rate: Fraction of calls to trace.
    """

    def __init__(
        self,
        metrics: list[str] | None = None,
        project: str | None = None,
        sample_rate: float = 1.0,
    ) -> None:
        super().__init__()
        self.metrics = metrics or []
        self.project = project
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self._tracer = Tracer(project=project or "langchain", metrics=self.metrics)
        self._conversations: list[Conversation] = []

        # Internal state for building conversations from callback events
        self._pending_messages: dict[str, list[Message]] = {}
        self._pending_context: dict[str, list[str]] = {}
        self._pending_metadata: dict[str, dict[str, Any]] = {}

        logger.info(
            "langchain_callback.init",
            metrics=self.metrics,
            project=self.project,
        )

    # -- LangChain callback interface ----------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM call begins."""
        rid = str(run_id or uuid.uuid4())
        self._pending_messages.setdefault(rid, [])
        self._pending_context.setdefault(rid, [])
        self._pending_metadata.setdefault(rid, {})

        model_name = serialized.get("name") or serialized.get("id", ["unknown"])[-1]
        self._pending_metadata[rid]["model"] = model_name
        self._pending_metadata[rid]["provider"] = "langchain"

        # Treat prompts as user messages
        now = datetime.now(timezone.utc)
        for prompt in prompts:
            self._pending_messages[rid].append(
                Message(role="user", content=prompt, timestamp=now)
            )

        logger.debug(
            "langchain_callback.on_llm_start", run_id=rid, model=model_name
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chat model call begins."""
        rid = str(run_id or uuid.uuid4())
        self._pending_messages.setdefault(rid, [])
        self._pending_context.setdefault(rid, [])
        self._pending_metadata.setdefault(rid, {})

        model_name = serialized.get("name") or serialized.get("id", ["unknown"])[-1]
        self._pending_metadata[rid]["model"] = model_name
        self._pending_metadata[rid]["provider"] = "langchain"

        now = datetime.now(timezone.utc)
        # Convert LangChain message objects to our Message format
        for message_group in messages:
            for lc_msg in message_group:
                role = "user"
                content = ""
                if hasattr(lc_msg, "type"):
                    role_map = {
                        "human": "user",
                        "ai": "assistant",
                        "system": "system",
                        "HumanMessage": "user",
                        "AIMessage": "assistant",
                        "SystemMessage": "system",
                    }
                    role = role_map.get(lc_msg.type, "user")
                if hasattr(lc_msg, "content"):
                    content = str(lc_msg.content)

                self._pending_messages[rid].append(
                    Message(role=role, content=content, timestamp=now)
                )

        logger.debug(
            "langchain_callback.on_chat_model_start",
            run_id=rid,
            model=model_name,
        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM call completes."""
        rid = str(run_id or "")
        if rid not in self._pending_messages:
            return

        # Extract text from the LangChain LLMResult
        content = ""
        if hasattr(response, "generations") and response.generations:
            first_gen = response.generations[0]
            if first_gen:
                gen = first_gen[0]
                if hasattr(gen, "text"):
                    content = gen.text
                elif hasattr(gen, "message") and hasattr(gen.message, "content"):
                    content = str(gen.message.content)

        self._pending_messages[rid].append(
            Message(
                role="assistant",
                content=content,
                timestamp=datetime.now(timezone.utc),
            )
        )

        # Record token usage if available
        if hasattr(response, "llm_output") and response.llm_output:
            usage = response.llm_output.get("token_usage", {})
            if usage:
                self._pending_metadata[rid]["usage"] = usage

        # Finalize the conversation
        self._finalize_conversation(rid)
        logger.debug("langchain_callback.on_llm_end", run_id=rid)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM call errors."""
        rid = str(run_id or "")
        logger.warning(
            "langchain_callback.on_llm_error",
            run_id=rid,
            error=str(error),
        )
        # Clean up pending state
        self._pending_messages.pop(rid, None)
        self._pending_context.pop(rid, None)
        self._pending_metadata.pop(rid, None)

    def on_retriever_end(
        self,
        documents: Any,
        *,
        run_id: Any | None = None,
        parent_run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a retriever returns documents."""
        # Associate context with the parent LLM run if possible
        rid = str(parent_run_id or run_id or "")
        self._pending_context.setdefault(rid, [])

        if isinstance(documents, list):
            for doc in documents:
                if hasattr(doc, "page_content"):
                    self._pending_context[rid].append(doc.page_content)
                elif isinstance(doc, str):
                    self._pending_context[rid].append(doc)

        logger.debug(
            "langchain_callback.on_retriever_end",
            run_id=rid,
            documents=len(self._pending_context.get(rid, [])),
        )

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain begins (informational)."""
        logger.debug(
            "langchain_callback.on_chain_start",
            run_id=str(run_id or ""),
            chain=serialized.get("name", "unknown"),
        )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain completes (informational)."""
        logger.debug(
            "langchain_callback.on_chain_end",
            run_id=str(run_id or ""),
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain errors (informational)."""
        logger.warning(
            "langchain_callback.on_chain_error",
            run_id=str(run_id or ""),
            error=str(error),
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
            logger.warning("langchain_callback.get_eval_report.no_conversations")
            return {"conversations_evaluated": 0, "results": []}

        logger.info(
            "langchain_callback.get_eval_report",
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
                "langchain_callback.get_eval_report.engine_not_available",
                hint="Install the full evalplatform package for auto-evaluation.",
            )
            return {
                "conversations_evaluated": len(conversations),
                "results": [],
                "error": "Evaluation engine not available. Install evalplatform.",
            }

    def clear(self) -> None:
        """Reset all recorded conversations and internal state."""
        self._conversations.clear()
        self._pending_messages.clear()
        self._pending_context.clear()
        self._pending_metadata.clear()
        self._tracer.clear()

    # -- internal helpers ----------------------------------------------------

    def _finalize_conversation(self, run_id: str) -> None:
        """Convert pending state for *run_id* into a :class:`Conversation`
        and append it to the recorded list.
        """
        messages = self._pending_messages.pop(run_id, [])
        context = self._pending_context.pop(run_id, [])
        metadata = self._pending_metadata.pop(run_id, {})

        if not messages:
            return

        # Extract system prompt from messages if present
        system_prompt: str | None = None
        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
                break

        conv = Conversation(
            id=str(uuid.uuid4()),
            messages=messages,
            context=context or None,
            system_prompt=system_prompt,
            metadata=metadata,
        )
        self._conversations.append(conv)
