"""Module-level convenience functions for chatbot evaluation.

These functions provide the simplest possible API for evaluating chatbot
conversations -- similar to ``mlflow.evaluate()`` or ``deepeval.evaluate()``.

Example::

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
"""

from __future__ import annotations

from typing import Any, Callable

from chatbot_evals.callbacks import BaseCallback
from chatbot_evals.types import Conversation, Dataset, EvalReport


async def evaluate(
    conversations: list[Conversation] | Dataset,
    metrics: list[str] | None = None,
    judge_model: str = "gpt-4o",
    name: str | None = None,
    callbacks: list[BaseCallback] | None = None,
) -> EvalReport:
    """Evaluate conversations with specified metrics.

    This is the primary entry point for the SDK.  Pass a list of
    :class:`~chatbot_evals.types.Conversation` objects (or a
    :class:`~chatbot_evals.types.Dataset`) and get back an
    :class:`~chatbot_evals.types.EvalReport` containing per-conversation
    scores, aggregate averages, and improvement recommendations.

    Args:
        conversations: Conversations to evaluate -- either a list or a
            :class:`Dataset`.
        metrics: Metric names to compute.  If ``None``, all registered
            metrics are used.
        judge_model: LLM model for judge-based metrics (default ``"gpt-4o"``).
        name: Optional human-readable run name.
        callbacks: Progress / reporting callbacks.

    Returns:
        An :class:`~chatbot_evals.types.EvalReport`.

    Example::

        import chatbot_evals as ce

        conversations = [
            ce.Conversation(messages=[
                ce.Message(role="user", content="What is AI?"),
                ce.Message(role="assistant", content="AI is artificial intelligence."),
            ]),
        ]
        report = await ce.evaluate(conversations, metrics=["coherence"])
        print(report.summary)
    """
    from chatbot_evals.client import ChatbotEvals

    client = ChatbotEvals(judge_model=judge_model)

    if isinstance(conversations, Dataset):
        dataset = conversations
    else:
        dataset = Dataset(conversations=conversations)

    return await client.run(
        dataset=dataset,
        metrics=metrics,
        name=name,
        callbacks=callbacks,
    )


async def evaluate_dataset(
    dataset: Dataset,
    metrics: list[str] | None = None,
    judge_model: str = "gpt-4o",
    name: str | None = None,
    callbacks: list[BaseCallback] | None = None,
    **kwargs: Any,
) -> EvalReport:
    """Evaluate a :class:`~chatbot_evals.types.Dataset`.

    Convenience wrapper around :func:`evaluate` that accepts a
    :class:`Dataset` directly.

    Args:
        dataset: The dataset to evaluate.
        metrics: Metric names to compute.
        judge_model: LLM model for judge-based metrics.
        name: Optional run name.
        callbacks: Progress callbacks.
        **kwargs: Additional keyword arguments forwarded to the client.

    Returns:
        An :class:`~chatbot_evals.types.EvalReport`.

    Example::

        ds = ce.Dataset.from_jsonl("conversations.jsonl")
        report = await ce.evaluate_dataset(ds, metrics=["faithfulness"])
    """
    return await evaluate(
        conversations=dataset,
        metrics=metrics,
        judge_model=judge_model,
        name=name,
        callbacks=callbacks,
    )


def evaluate_sync(
    conversations: list[Conversation] | Dataset,
    metrics: list[str] | None = None,
    judge_model: str = "gpt-4o",
    name: str | None = None,
    callbacks: list[BaseCallback] | None = None,
) -> EvalReport:
    """Synchronous version of :func:`evaluate`.

    Useful in scripts, notebooks, and other contexts where ``await`` is
    not available.

    Args:
        conversations: Conversations to evaluate.
        metrics: Metric names to compute.
        judge_model: LLM model for judge-based metrics.
        name: Optional run name.
        callbacks: Progress callbacks.

    Returns:
        An :class:`~chatbot_evals.types.EvalReport`.

    Example::

        report = ce.evaluate_sync(conversations, metrics=["faithfulness"])
        print(report.summary)
    """
    from chatbot_evals.client import _run_sync

    return _run_sync(
        evaluate(
            conversations=conversations,
            metrics=metrics,
            judge_model=judge_model,
            name=name,
            callbacks=callbacks,
        )
    )
