"""Chatbot Evals SDK -- evaluate chatbot conversations with a few lines of code.

Install with ``pip install chatbot-evals`` and start evaluating::

    import chatbot_evals as ce

    conversations = [
        ce.Conversation(
            messages=[
                ce.Message(role="user", content="What is your return policy?"),
                ce.Message(role="assistant", content="We accept returns within 30 days."),
            ],
            context="Return policy: 30 day returns with receipt.",
        )
    ]

    report = await ce.evaluate(conversations, metrics=["faithfulness", "relevance"])
    print(report.summary)
    print(report.metric_averages)

Key APIs
--------
- :func:`evaluate` / :func:`evaluate_sync` -- Evaluate conversations (module-level).
- :func:`evaluate_dataset` -- Evaluate a :class:`Dataset`.
- :class:`ChatbotEvals` -- Object-oriented client with full control.
- :func:`@trace <trace>` / :func:`@monitor <monitor>` / :func:`@log_conversation <log_conversation>` -- Decorators for production monitoring.
- :func:`configure` -- Set global SDK configuration.
"""

from __future__ import annotations

# Types
from chatbot_evals.types import (
    Conversation,
    Dataset,
    EvalReport,
    EvalResult,
    Message,
    MetricDetail,
)

# Client
from chatbot_evals.client import ChatbotEvals

# Module-level evaluate functions
from chatbot_evals.evaluate import evaluate, evaluate_dataset, evaluate_sync

# Decorators
from chatbot_evals.decorators import (
    TraceContext,
    clear_traces,
    get_traces,
    log_conversation,
    monitor,
    trace,
)

# Config
from chatbot_evals.config import Config, configure, get_config

__all__ = [
    # Types
    "Conversation",
    "Dataset",
    "EvalReport",
    "EvalResult",
    "Message",
    "MetricDetail",
    # Client
    "ChatbotEvals",
    # Evaluate
    "evaluate",
    "evaluate_dataset",
    "evaluate_sync",
    # Decorators
    "trace",
    "monitor",
    "log_conversation",
    "TraceContext",
    "get_traces",
    "clear_traces",
    # Config
    "Config",
    "configure",
    "get_config",
]

__version__ = "0.1.0"
