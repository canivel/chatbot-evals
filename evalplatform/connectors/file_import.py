"""File import connector.

Imports conversation data from local files in CSV, JSON, or JSONL format.
Column / field mapping is configurable so that arbitrary file schemas can be
normalised to :class:`ConversationData`.

Supports batch import with progress reporting via a callback.
"""

from __future__ import annotations

import csv
import io
import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import aiofiles
from pydantic import BaseModel, Field

import structlog

from evalplatform.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    ConversationData,
    MessageData,
    SyncResult,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FileFormat(str, Enum):
    """Supported file formats for import."""

    CSV = "csv"
    JSON = "json"
    JSONL = "jsonl"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ColumnMapping(BaseModel):
    """Mapping from file columns / fields to ConversationData fields.

    For CSV files, values are column names.  For JSON/JSONL, values are
    dot-separated paths into each record object.
    """

    conversation_id: str = Field(
        default="conversation_id",
        description="Column/path for the conversation external ID",
    )
    message_role: str = Field(
        default="role",
        description="Column/path for the message role",
    )
    message_content: str = Field(
        default="content",
        description="Column/path for the message text",
    )
    message_timestamp: str = Field(
        default="timestamp",
        description="Column/path for the message timestamp",
    )
    started_at: str = Field(
        default="started_at",
        description="Column/path for the conversation start time",
    )
    ended_at: str = Field(
        default="ended_at",
        description="Column/path for the conversation end time",
    )
    messages_path: str = Field(
        default="messages",
        description="Dot-path to the messages array (JSON/JSONL only)",
    )


class FileImportConfig(ConnectorConfig):
    """Configuration for the file import connector."""

    connector_type: str = "file_import"
    file_format: FileFormat = Field(
        default=FileFormat.JSON, description="Format of the file to import"
    )
    column_mapping: ColumnMapping = Field(
        default_factory=ColumnMapping,
        description="Mapping from file columns/fields to ConversationData fields",
    )
    batch_size: int = Field(
        default=500, ge=1, le=10_000, description="Number of records per batch"
    )
    encoding: str = Field(
        default="utf-8", description="File encoding"
    )
    csv_delimiter: str = Field(
        default=",", description="Delimiter for CSV files"
    )


# ---------------------------------------------------------------------------
# Progress callback protocol
# ---------------------------------------------------------------------------


class ImportProgressCallback(Protocol):
    """Protocol for progress reporting during import."""

    async def __call__(
        self,
        *,
        processed: int,
        total: int | None,
        errors: int,
    ) -> None:
        """Called periodically during import.

        Args:
            processed: Number of records processed so far.
            total: Total number of records, if known in advance.
            errors: Number of records that failed to parse.
        """
        ...


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class FileImportConnector(BaseConnector):
    """Connector that imports conversations from CSV, JSON, or JSONL files."""

    def __init__(self, config: FileImportConfig) -> None:
        super().__init__(config)
        self._config: FileImportConfig = config
        self._conversations: dict[str, ConversationData] = {}
        self._import_errors: list[str] = []

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Mark the connector as ready for import."""
        self.status = ConnectorStatus.CONNECTED
        self.logger.info("file_import_connector_ready")
        return True

    async def disconnect(self) -> None:
        """Clear stored conversations."""
        self.status = ConnectorStatus.DISCONNECTED
        self._conversations.clear()
        self._import_errors.clear()
        self.logger.info("file_import_connector_disconnected")

    async def test_connection(self) -> bool:
        """Always returns True; file imports don't require a live connection."""
        return True

    # -- data fetching -------------------------------------------------------

    async def fetch_conversations(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Return stored (imported) conversations.

        Args:
            since: Only return conversations with ``started_at`` after this time.
            limit: Maximum number to return.
        """
        conversations = list(self._conversations.values())

        if since is not None:
            conversations = [
                c
                for c in conversations
                if c.started_at is not None and c.started_at >= since
            ]

        conversations.sort(
            key=lambda c: c.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return conversations[:limit]

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Return a single imported conversation by external ID."""
        conv = self._conversations.get(external_id)
        if conv is None:
            raise ValueError(
                f"Conversation '{external_id}' not found in imported data"
            )
        return conv

    # -- sync override -------------------------------------------------------

    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Return a summary of the imported conversations."""
        start = time.monotonic()
        conversations = await self.fetch_conversations(since=since, limit=len(self._conversations))
        return SyncResult(
            conversations_synced=len(conversations),
            errors=list(self._import_errors),
            duration_seconds=round(time.monotonic() - start, 3),
        )

    # -- file import ---------------------------------------------------------

    async def import_file(
        self,
        file_path: str | Path,
        *,
        progress_callback: ImportProgressCallback | None = None,
    ) -> ImportResult:
        """Import conversations from a file.

        Args:
            file_path: Path to the file to import.
            progress_callback: Optional async callback invoked after each batch.

        Returns:
            An :class:`ImportResult` summarising the import.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Import file not found: {path}")

        self.logger.info(
            "import_started",
            file=str(path),
            format=self._config.file_format.value,
        )
        self._import_errors.clear()
        start = time.monotonic()

        match self._config.file_format:
            case FileFormat.CSV:
                result = await self._import_csv(path, progress_callback)
            case FileFormat.JSON:
                result = await self._import_json(path, progress_callback)
            case FileFormat.JSONL:
                result = await self._import_jsonl(path, progress_callback)

        result.duration_seconds = round(time.monotonic() - start, 3)

        self.logger.info(
            "import_completed",
            total_records=result.total_records,
            conversations_imported=result.conversations_imported,
            errors=result.error_count,
            duration=result.duration_seconds,
        )
        return result

    async def import_data(
        self,
        data: str | bytes,
        *,
        progress_callback: ImportProgressCallback | None = None,
    ) -> ImportResult:
        """Import conversations from an in-memory string or bytes.

        This is useful when receiving file uploads via an API endpoint.

        Args:
            data: Raw file content (string or bytes).
            progress_callback: Optional async callback.
        """
        if isinstance(data, bytes):
            data = data.decode(self._config.encoding)

        self.logger.info("import_from_data_started", format=self._config.file_format.value)
        self._import_errors.clear()
        start = time.monotonic()

        match self._config.file_format:
            case FileFormat.CSV:
                result = await self._parse_csv(data, progress_callback)
            case FileFormat.JSON:
                result = await self._parse_json(data, progress_callback)
            case FileFormat.JSONL:
                result = await self._parse_jsonl(data, progress_callback)

        result.duration_seconds = round(time.monotonic() - start, 3)

        self.logger.info(
            "import_from_data_completed",
            total_records=result.total_records,
            conversations_imported=result.conversations_imported,
            errors=result.error_count,
        )
        return result

    # -- CSV import ----------------------------------------------------------

    async def _import_csv(
        self,
        path: Path,
        progress_callback: ImportProgressCallback | None,
    ) -> ImportResult:
        """Read a CSV file and delegate to the parser."""
        async with aiofiles.open(
            path, mode="r", encoding=self._config.encoding
        ) as f:
            content = await f.read()
        return await self._parse_csv(content, progress_callback)

    async def _parse_csv(
        self,
        content: str,
        progress_callback: ImportProgressCallback | None,
    ) -> ImportResult:
        """Parse CSV content into conversations.

        CSV files are expected to have one row per message.  Rows with the same
        ``conversation_id`` value are grouped into a single conversation.
        """
        mapping = self._config.column_mapping
        reader = csv.DictReader(
            io.StringIO(content), delimiter=self._config.csv_delimiter
        )

        # Validate required columns
        fieldnames = reader.fieldnames or []
        required = {mapping.conversation_id, mapping.message_role, mapping.message_content}
        missing = required - set(fieldnames)
        if missing:
            raise ValueError(
                f"CSV is missing required columns: {', '.join(sorted(missing))}. "
                f"Available columns: {', '.join(fieldnames)}"
            )

        # Group rows by conversation ID
        groups: dict[str, list[dict[str, str]]] = {}
        total_rows = 0
        error_count = 0

        for row in reader:
            total_rows += 1
            conv_id = row.get(mapping.conversation_id, "")
            if not conv_id:
                error_msg = f"Row {total_rows}: missing conversation_id"
                self._import_errors.append(error_msg)
                error_count += 1
                continue
            groups.setdefault(conv_id, []).append(row)

        # Convert groups to conversations
        conversations_imported = 0
        processed = 0

        for conv_id, rows in groups.items():
            try:
                conv = self._csv_rows_to_conversation(conv_id, rows)
                self._conversations[conv.external_id] = conv
                conversations_imported += 1
            except Exception as exc:
                error_msg = f"Conversation '{conv_id}': {exc}"
                self._import_errors.append(error_msg)
                error_count += 1

            processed += len(rows)
            if progress_callback and processed % self._config.batch_size == 0:
                await progress_callback(
                    processed=processed, total=total_rows, errors=error_count
                )

        if progress_callback:
            await progress_callback(
                processed=total_rows, total=total_rows, errors=error_count
            )

        return ImportResult(
            total_records=total_rows,
            conversations_imported=conversations_imported,
            error_count=error_count,
            errors=list(self._import_errors),
        )

    def _csv_rows_to_conversation(
        self, conv_id: str, rows: list[dict[str, str]]
    ) -> ConversationData:
        """Convert grouped CSV rows into a single :class:`ConversationData`."""
        mapping = self._config.column_mapping
        messages: list[MessageData] = []

        for row in rows:
            role = row.get(mapping.message_role, "user")
            content = row.get(mapping.message_content, "")
            ts_raw = row.get(mapping.message_timestamp, "")
            timestamp = _parse_timestamp(ts_raw) if ts_raw else None

            messages.append(
                MessageData(
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    metadata={
                        k: v
                        for k, v in row.items()
                        if k
                        not in (
                            mapping.conversation_id,
                            mapping.message_role,
                            mapping.message_content,
                            mapping.message_timestamp,
                            mapping.started_at,
                            mapping.ended_at,
                        )
                    },
                )
            )

        # Use first row for conversation-level timestamps
        first_row = rows[0]
        started_at = _parse_timestamp(first_row.get(mapping.started_at, "")) or (
            messages[0].timestamp if messages else None
        )
        ended_at = _parse_timestamp(first_row.get(mapping.ended_at, "")) or (
            messages[-1].timestamp if messages else None
        )

        return ConversationData(
            external_id=conv_id,
            messages=messages,
            metadata={"source": "csv_import"},
            started_at=started_at,
            ended_at=ended_at,
        )

    # -- JSON import ---------------------------------------------------------

    async def _import_json(
        self,
        path: Path,
        progress_callback: ImportProgressCallback | None,
    ) -> ImportResult:
        """Read a JSON file and delegate to the parser."""
        async with aiofiles.open(
            path, mode="r", encoding=self._config.encoding
        ) as f:
            content = await f.read()
        return await self._parse_json(content, progress_callback)

    async def _parse_json(
        self,
        content: str,
        progress_callback: ImportProgressCallback | None,
    ) -> ImportResult:
        """Parse JSON content (expected to be an array of conversation objects)."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        # Accept both a top-level list and a dict with a key holding the list
        if isinstance(data, dict):
            # Try to find an array in the data
            for key in ("conversations", "data", "results", "items"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                raise ValueError(
                    "JSON must be an array or contain a recognised array key "
                    "(conversations, data, results, items)"
                )

        if not isinstance(data, list):
            raise ValueError("JSON root must be an array of conversation objects")

        return await self._process_json_records(data, progress_callback)

    # -- JSONL import --------------------------------------------------------

    async def _import_jsonl(
        self,
        path: Path,
        progress_callback: ImportProgressCallback | None,
    ) -> ImportResult:
        """Read a JSONL file and delegate to the parser."""
        async with aiofiles.open(
            path, mode="r", encoding=self._config.encoding
        ) as f:
            content = await f.read()
        return await self._parse_jsonl(content, progress_callback)

    async def _parse_jsonl(
        self,
        content: str,
        progress_callback: ImportProgressCallback | None,
    ) -> ImportResult:
        """Parse JSONL content (one JSON object per line)."""
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
                else:
                    error_msg = f"Line {line_no}: expected a JSON object, got {type(obj).__name__}"
                    self._import_errors.append(error_msg)
            except json.JSONDecodeError as exc:
                error_msg = f"Line {line_no}: invalid JSON: {exc}"
                self._import_errors.append(error_msg)

        return await self._process_json_records(records, progress_callback)

    # -- shared JSON record processing ---------------------------------------

    async def _process_json_records(
        self,
        records: list[dict[str, Any]],
        progress_callback: ImportProgressCallback | None,
    ) -> ImportResult:
        """Process a list of JSON conversation records."""
        mapping = self._config.column_mapping
        total = len(records)
        conversations_imported = 0
        error_count = len(self._import_errors)  # carry forward any JSONL parse errors

        for idx, record in enumerate(records):
            try:
                conv = self._json_record_to_conversation(record, mapping)
                self._conversations[conv.external_id] = conv
                conversations_imported += 1
            except Exception as exc:
                error_msg = f"Record {idx}: {exc}"
                self._import_errors.append(error_msg)
                error_count += 1

            if progress_callback and (idx + 1) % self._config.batch_size == 0:
                await progress_callback(
                    processed=idx + 1, total=total, errors=error_count
                )

        if progress_callback:
            await progress_callback(
                processed=total, total=total, errors=error_count
            )

        return ImportResult(
            total_records=total,
            conversations_imported=conversations_imported,
            error_count=error_count,
            errors=list(self._import_errors),
        )

    def _json_record_to_conversation(
        self,
        record: dict[str, Any],
        mapping: ColumnMapping,
    ) -> ConversationData:
        """Convert a JSON record into a :class:`ConversationData`."""
        external_id = str(
            _resolve_path(record, mapping.conversation_id) or uuid.uuid4().hex
        )

        raw_messages = _resolve_path(record, mapping.messages_path)
        messages: list[MessageData] = []

        if isinstance(raw_messages, list):
            for raw_msg in raw_messages:
                if not isinstance(raw_msg, dict):
                    continue
                role = str(_resolve_path(raw_msg, mapping.message_role) or "user")
                content = str(_resolve_path(raw_msg, mapping.message_content) or "")
                ts_raw = _resolve_path(raw_msg, mapping.message_timestamp)
                timestamp = _parse_timestamp(ts_raw)

                messages.append(
                    MessageData(
                        role=role,
                        content=content,
                        timestamp=timestamp,
                        metadata={
                            k: v
                            for k, v in raw_msg.items()
                            if k
                            not in (
                                mapping.message_role,
                                mapping.message_content,
                                mapping.message_timestamp,
                            )
                        },
                    )
                )

        started_at = _parse_timestamp(_resolve_path(record, mapping.started_at))
        ended_at = _parse_timestamp(_resolve_path(record, mapping.ended_at))

        return ConversationData(
            external_id=external_id,
            messages=messages,
            metadata={
                k: v
                for k, v in record.items()
                if k
                not in (
                    mapping.conversation_id,
                    mapping.messages_path,
                    mapping.started_at,
                    mapping.ended_at,
                )
            },
            started_at=started_at,
            ended_at=ended_at,
        )

    # -- data validation -----------------------------------------------------

    def validate_file(self, file_path: str | Path) -> list[str]:
        """Synchronously validate that a file can be parsed.

        Returns a list of validation error messages (empty if valid).
        """
        path = Path(file_path)
        errors: list[str] = []

        if not path.exists():
            errors.append(f"File not found: {path}")
            return errors

        if not path.is_file():
            errors.append(f"Path is not a file: {path}")
            return errors

        suffix = path.suffix.lower().lstrip(".")
        expected = self._config.file_format.value
        if suffix not in (expected, "txt"):
            errors.append(
                f"File extension '.{suffix}' does not match expected format '{expected}'"
            )

        try:
            content = path.read_text(encoding=self._config.encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"Cannot decode file with {self._config.encoding}: {exc}")
            return errors

        if not content.strip():
            errors.append("File is empty")
            return errors

        # Format-specific checks
        match self._config.file_format:
            case FileFormat.CSV:
                errors.extend(self._validate_csv_content(content))
            case FileFormat.JSON:
                errors.extend(self._validate_json_content(content))
            case FileFormat.JSONL:
                errors.extend(self._validate_jsonl_content(content))

        return errors

    def _validate_csv_content(self, content: str) -> list[str]:
        """Validate CSV content structure."""
        errors: list[str] = []
        mapping = self._config.column_mapping

        try:
            reader = csv.DictReader(
                io.StringIO(content), delimiter=self._config.csv_delimiter
            )
            fieldnames = reader.fieldnames or []
        except csv.Error as exc:
            errors.append(f"Invalid CSV: {exc}")
            return errors

        required = {mapping.conversation_id, mapping.message_role, mapping.message_content}
        missing = required - set(fieldnames)
        if missing:
            errors.append(f"Missing required columns: {', '.join(sorted(missing))}")

        return errors

    @staticmethod
    def _validate_json_content(content: str) -> list[str]:
        """Validate JSON content structure."""
        errors: list[str] = []
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            errors.append(f"Invalid JSON: {exc}")
            return errors

        if isinstance(data, dict):
            has_array = any(
                isinstance(data.get(k), list)
                for k in ("conversations", "data", "results", "items")
            )
            if not has_array:
                errors.append(
                    "JSON object must contain a recognised array key "
                    "(conversations, data, results, items)"
                )
        elif not isinstance(data, list):
            errors.append("JSON root must be an array or object")

        return errors

    @staticmethod
    def _validate_jsonl_content(content: str) -> list[str]:
        """Validate JSONL content structure."""
        errors: list[str] = []
        for line_no, line in enumerate(content.splitlines()[:10], start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    errors.append(f"Line {line_no}: expected JSON object")
            except json.JSONDecodeError:
                errors.append(f"Line {line_no}: invalid JSON")

        return errors


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ImportResult(BaseModel):
    """Summary of a file import operation."""

    total_records: int = Field(0, description="Total records found in the file")
    conversations_imported: int = Field(
        0, description="Number of conversations successfully imported"
    )
    error_count: int = Field(0, description="Number of records that failed")
    errors: list[str] = Field(
        default_factory=list, description="Individual error messages"
    )
    duration_seconds: float = Field(
        0.0, description="Wall-clock duration of the import"
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _resolve_path(data: Any, path: str) -> Any:
    """Resolve a dot-separated path against a nested dict."""
    current: Any = data
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            return None
    return current


def _parse_timestamp(value: Any) -> datetime | None:
    """Best-effort timestamp parse from various formats."""
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError):
            return None

    value_str = str(value)
    try:
        dt = datetime.fromisoformat(value_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        pass

    try:
        return datetime.fromtimestamp(float(value_str), tz=timezone.utc)
    except (ValueError, OSError):
        return None
