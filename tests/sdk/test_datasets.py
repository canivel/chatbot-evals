"""Tests for SDK dataset loaders."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


def test_load_from_json():
    from chatbot_evals.datasets.loaders import DatasetLoader

    data = [
        {
            "messages": [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
            ],
            "context": "Some context",
        },
        {
            "messages": [
                {"role": "user", "content": "Q2"},
                {"role": "assistant", "content": "A2"},
            ],
        },
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name

    conversations = DatasetLoader.from_json(path)
    assert len(conversations) == 2
    assert conversations[0].messages[0].content == "Q1"
    assert conversations[0].context == "Some context"

    Path(path).unlink()


def test_load_from_jsonl():
    from chatbot_evals.datasets.loaders import DatasetLoader

    lines = [
        json.dumps({"messages": [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"}]}),
        json.dumps({"messages": [{"role": "user", "content": "Q2"}, {"role": "assistant", "content": "A2"}]}),
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(lines))
        path = f.name

    conversations = DatasetLoader.from_jsonl(path)
    assert len(conversations) == 2

    Path(path).unlink()


def test_load_from_csv():
    from chatbot_evals.datasets.loaders import DatasetLoader

    csv_content = "question,answer,context\nWhat is X?,X is Y,Docs say X is Y\nWhat is A?,A is B,Docs say A is B"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        path = f.name

    mapping = {"user_col": "question", "assistant_col": "answer", "context_col": "context"}
    conversations = DatasetLoader.from_csv(path, mapping=mapping)
    assert len(conversations) == 2
    assert conversations[0].messages[0].content == "What is X?"
    assert conversations[0].messages[1].content == "X is Y"
    assert conversations[0].context == "Docs say X is Y"

    Path(path).unlink()


def test_load_from_dict_list():
    from chatbot_evals.datasets.loaders import DatasetLoader

    records = [
        {"messages": [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"}]},
        {"messages": [{"role": "user", "content": "Q2"}, {"role": "assistant", "content": "A2"}]},
    ]

    conversations = DatasetLoader.from_dict_list(records)
    assert len(conversations) == 2
