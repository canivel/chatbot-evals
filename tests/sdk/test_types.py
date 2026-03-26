"""Tests for SDK types."""

from __future__ import annotations

import pytest


def test_message_creation():
    from chatbot_evals.types import Message

    msg = Message(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert msg.metadata == {}


def test_conversation_creation():
    from chatbot_evals.types import Conversation, Message

    conv = Conversation(
        messages=[
            Message(role="user", content="What is X?"),
            Message(role="assistant", content="X is Y."),
        ],
        context="X is Y according to docs.",
        ground_truth="X is Y.",
    )
    assert len(conv.messages) == 2
    assert conv.context == "X is Y according to docs."
    assert conv.id is not None


def test_conversation_from_messages():
    from chatbot_evals.types import Conversation

    conv = Conversation.from_messages([
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
    ])
    assert len(conv.messages) == 2
    assert conv.messages[0].role == "user"


def test_dataset_creation():
    from chatbot_evals.types import Dataset, Conversation, Message

    conversations = [
        Conversation(messages=[Message(role="user", content=f"Q{i}"), Message(role="assistant", content=f"A{i}")])
        for i in range(5)
    ]
    ds = Dataset(conversations=conversations, name="test-set")
    assert len(ds) == 5
    assert ds.name == "test-set"


def test_dataset_from_list():
    from chatbot_evals.types import Dataset

    records = [
        {"messages": [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"}]},
        {"messages": [{"role": "user", "content": "Q2"}, {"role": "assistant", "content": "A2"}]},
    ]
    ds = Dataset.from_list(records)
    assert len(ds) == 2


def test_eval_result():
    from chatbot_evals.types import EvalResult, MetricDetail

    result = EvalResult(
        conversation_id="conv-001",
        scores={"faithfulness": 0.85, "relevance": 0.90},
        details={
            "faithfulness": MetricDetail(score=0.85, explanation="Good grounding"),
            "relevance": MetricDetail(score=0.90, explanation="Very relevant"),
        },
        overall_score=0.875,
    )
    assert result.overall_score == 0.875
    assert result.scores["faithfulness"] == 0.85
    assert len(result.flags) == 0


def test_eval_result_flags():
    from chatbot_evals.types import EvalResult, MetricDetail

    result = EvalResult(
        conversation_id="conv-002",
        scores={"faithfulness": 0.3, "toxicity": 0.4},
        details={
            "faithfulness": MetricDetail(score=0.3, explanation="Low"),
            "toxicity": MetricDetail(score=0.4, explanation="Issues"),
        },
        overall_score=0.35,
        flags=["low_faithfulness", "toxicity_warning"],
    )
    assert len(result.flags) == 2


def test_eval_report():
    from chatbot_evals.types import EvalReport, EvalResult, MetricDetail

    results = [
        EvalResult(
            conversation_id=f"conv-{i}",
            scores={"faithfulness": 0.8 + i * 0.05},
            details={"faithfulness": MetricDetail(score=0.8 + i * 0.05, explanation="OK")},
            overall_score=0.8 + i * 0.05,
        )
        for i in range(3)
    ]
    report = EvalReport(
        results=results,
        summary="Good overall",
        metric_averages={"faithfulness": 0.85},
    )
    assert len(report.results) == 3
    assert report.metric_averages["faithfulness"] == 0.85
