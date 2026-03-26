"""Dataset loading utilities for CSV, JSON, JSONL, DataFrames, and HuggingFace.

Every public loader returns ``list[Conversation]`` so results can be fed
directly into the evaluation engine or wrapped in a :class:`Dataset`.
"""

from __future__ import annotations

import csv
import json
import pathlib
from typing import Any

import structlog

from chatbot_evals.types import Conversation, Message

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Column-mapping type
# ---------------------------------------------------------------------------

# A mapping tells loaders which source columns map to Conversation fields.
# Recognised keys:
#   user_col        -> user message text
#   assistant_col   -> assistant response text
#   context_col     -> retrieved context (single string or JSON list)
#   ground_truth_col -> expected answer
#   system_prompt_col -> system prompt
#   id_col          -> conversation id
ColumnMapping = dict[str, str]

_DEFAULT_MAPPING: ColumnMapping = {
    "user_col": "question",
    "assistant_col": "answer",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_to_conversation(
    record: dict[str, Any],
    mapping: ColumnMapping | None = None,
) -> Conversation:
    """Convert a flat dict/record into a :class:`Conversation`.

    If the record already contains a ``messages`` key with the expected
    list-of-dicts shape it is treated as a pre-structured conversation.
    Otherwise the *mapping* is used to extract user/assistant columns.
    """
    mapping = mapping or _DEFAULT_MAPPING

    # Pre-structured record -- passthrough via Conversation.from_dict
    if "messages" in record and isinstance(record["messages"], list):
        return Conversation.from_dict(record)

    # Flat record -- use mapping to build messages
    messages: list[Message] = []

    system_prompt: str | None = None
    system_col = mapping.get("system_prompt_col")
    if system_col and record.get(system_col):
        system_prompt = str(record[system_col])
        messages.append(Message(role="system", content=system_prompt))

    user_col = mapping.get("user_col", "question")
    if record.get(user_col):
        messages.append(Message(role="user", content=str(record[user_col])))

    assistant_col = mapping.get("assistant_col", "answer")
    if record.get(assistant_col):
        messages.append(Message(role="assistant", content=str(record[assistant_col])))

    context_col = mapping.get("context_col")
    context: str | list[str] | None = _parse_context(
        record.get(context_col) if context_col else None
    )

    ground_truth_col = mapping.get("ground_truth_col")
    ground_truth = (
        str(record[ground_truth_col])
        if ground_truth_col and record.get(ground_truth_col)
        else None
    )

    id_col = mapping.get("id_col")
    conv_id = str(record[id_col]) if id_col and record.get(id_col) else None

    # Remaining fields go into metadata (excluding mapped columns)
    mapped_cols = {
        user_col,
        assistant_col,
        context_col,
        ground_truth_col,
        system_col,
        id_col,
    }
    extra_metadata = {
        k: v for k, v in record.items() if k not in mapped_cols and v is not None
    }

    kwargs: dict[str, Any] = {
        "messages": messages,
        "context": context,
        "ground_truth": ground_truth,
        "system_prompt": system_prompt,
        "metadata": extra_metadata,
    }
    if conv_id:
        kwargs["id"] = conv_id

    return Conversation(**kwargs)


def _parse_context(raw: Any) -> str | list[str] | None:
    """Normalise a context value into a form accepted by :class:`Conversation`.

    Returns a single string, a list of strings, or ``None``.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        # Attempt JSON parse for stringified lists
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return raw if raw.strip() else None
    return str(raw)


# ---------------------------------------------------------------------------
# DatasetLoader
# ---------------------------------------------------------------------------


class DatasetLoader:
    """Versatile loader that converts common data formats into conversations.

    All methods are static and return ``list[Conversation]``.
    """

    @staticmethod
    def from_csv(
        path: str | pathlib.Path,
        mapping: ColumnMapping | None = None,
    ) -> list[Conversation]:
        """Load conversations from a CSV file.

        Args:
            path: Filesystem path to the CSV file.
            mapping: Column mapping, e.g.
                ``{"user_col": "question", "assistant_col": "answer"}``.

        Returns:
            List of parsed :class:`Conversation` objects.
        """
        path = pathlib.Path(path)
        logger.info("dataset_loader.from_csv", path=str(path))

        conversations: list[Conversation] = []
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                conversations.append(_record_to_conversation(row, mapping))

        logger.info("dataset_loader.from_csv.done", count=len(conversations))
        return conversations

    @staticmethod
    def from_json(path: str | pathlib.Path) -> list[Conversation]:
        """Load conversations from a JSON file containing an array of objects.

        Each object may be a pre-structured conversation (with ``messages``)
        or a flat record that will be converted using the default mapping.

        Args:
            path: Filesystem path to the JSON file.

        Returns:
            List of parsed :class:`Conversation` objects.
        """
        path = pathlib.Path(path)
        logger.info("dataset_loader.from_json", path=str(path))

        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        if not isinstance(data, list):
            raise ValueError(
                f"Expected a JSON array at the top level, got {type(data).__name__}"
            )

        conversations = [_record_to_conversation(record) for record in data]
        logger.info("dataset_loader.from_json.done", count=len(conversations))
        return conversations

    @staticmethod
    def from_jsonl(path: str | pathlib.Path) -> list[Conversation]:
        """Load conversations from a JSONL file (one JSON object per line).

        Args:
            path: Filesystem path to the JSONL file.

        Returns:
            List of parsed :class:`Conversation` objects.
        """
        path = pathlib.Path(path)
        logger.info("dataset_loader.from_jsonl", path=str(path))

        conversations: list[Conversation] = []
        with path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "dataset_loader.from_jsonl.parse_error",
                        line=line_no,
                        error=str(exc),
                    )
                    continue
                conversations.append(_record_to_conversation(record))

        logger.info("dataset_loader.from_jsonl.done", count=len(conversations))
        return conversations

    @staticmethod
    def from_pandas(
        df: Any,  # pandas.DataFrame -- kept as Any to avoid hard dependency
        mapping: ColumnMapping | None = None,
    ) -> list[Conversation]:
        """Load conversations from a :mod:`pandas` DataFrame.

        Args:
            df: A ``pandas.DataFrame`` with one conversation per row.
            mapping: Column mapping.

        Returns:
            List of parsed :class:`Conversation` objects.

        Raises:
            ImportError: If pandas is not installed.
        """
        try:
            import pandas as pd  # noqa: F401 -- validate import
        except ImportError as exc:
            raise ImportError(
                "pandas is required for from_pandas(). "
                "Install it with: pip install chatbot-evals[pandas]"
            ) from exc

        logger.info("dataset_loader.from_pandas", rows=len(df))
        records: list[dict[str, Any]] = df.to_dict(orient="records")
        return DatasetLoader.from_dict_list(records, mapping)

    @staticmethod
    def from_dict_list(
        records: list[dict[str, Any]],
        mapping: ColumnMapping | None = None,
    ) -> list[Conversation]:
        """Load conversations from a list of plain dicts.

        Args:
            records: List of dictionaries, one per conversation.
            mapping: Column mapping.

        Returns:
            List of parsed :class:`Conversation` objects.
        """
        logger.info("dataset_loader.from_dict_list", count=len(records))
        return [_record_to_conversation(record, mapping) for record in records]


# ---------------------------------------------------------------------------
# FileLoader -- convenience alias that auto-detects format from extension
# ---------------------------------------------------------------------------


class FileLoader:
    """Auto-detect file format and delegate to :class:`DatasetLoader`.

    Supports ``.csv``, ``.json``, and ``.jsonl`` / ``.ndjson`` extensions.
    """

    @staticmethod
    def load(
        path: str | pathlib.Path,
        mapping: ColumnMapping | None = None,
    ) -> list[Conversation]:
        """Load conversations from a file, auto-detecting the format.

        Args:
            path: Filesystem path.
            mapping: Optional column mapping (used for CSV and flat-record JSON).

        Returns:
            List of :class:`Conversation` objects.

        Raises:
            ValueError: If the file extension is not recognised.
        """
        path = pathlib.Path(path)
        suffix = path.suffix.lower()

        if suffix == ".csv":
            return DatasetLoader.from_csv(path, mapping)
        if suffix == ".json":
            return DatasetLoader.from_json(path)
        if suffix in {".jsonl", ".ndjson"}:
            return DatasetLoader.from_jsonl(path)

        raise ValueError(
            f"Unsupported file extension {suffix!r}. "
            "Use .csv, .json, or .jsonl."
        )


# ---------------------------------------------------------------------------
# HuggingFaceLoader
# ---------------------------------------------------------------------------


class HuggingFaceLoader:
    """Load evaluation datasets from the HuggingFace Hub.

    Requires the ``datasets`` package::

        pip install chatbot-evals[huggingface]
    """

    @staticmethod
    def from_hub(
        dataset_name: str,
        split: str = "test",
        mapping: ColumnMapping | None = None,
        *,
        max_samples: int | None = None,
        trust_remote_code: bool = False,
    ) -> list[Conversation]:
        """Download a dataset from HuggingFace and convert to conversations.

        Args:
            dataset_name: HuggingFace dataset identifier, e.g. ``"squad"``.
            split: Dataset split to load (default ``"test"``).
            mapping: Column mapping from HF columns to conversation fields.
            max_samples: If set, only load up to this many samples.
            trust_remote_code: Whether to trust remote code in the dataset
                script (forwarded to ``datasets.load_dataset``).

        Returns:
            List of :class:`Conversation` objects.

        Raises:
            ImportError: If the ``datasets`` library is not installed.

        Example::

            convs = HuggingFaceLoader.from_hub(
                "squad",
                split="validation",
                mapping={
                    "user_col": "question",
                    "context_col": "context",
                    "ground_truth_col": "answers",
                },
            )
        """
        try:
            from datasets import load_dataset  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "The 'datasets' library is required for HuggingFaceLoader. "
                "Install it with: pip install chatbot-evals[huggingface]"
            ) from exc

        logger.info(
            "huggingface_loader.from_hub",
            dataset=dataset_name,
            split=split,
        )

        ds = load_dataset(
            dataset_name,
            split=split,
            trust_remote_code=trust_remote_code,
        )

        records: list[dict[str, Any]] = []
        for idx, row in enumerate(ds):
            if max_samples is not None and idx >= max_samples:
                break
            records.append(dict(row))

        conversations = DatasetLoader.from_dict_list(records, mapping)
        logger.info(
            "huggingface_loader.from_hub.done",
            dataset=dataset_name,
            count=len(conversations),
        )
        return conversations
