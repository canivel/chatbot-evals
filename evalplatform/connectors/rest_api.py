"""Generic REST API poller connector.

Polls a configurable REST endpoint on a schedule (or on demand) and maps the
JSON response to :class:`ConversationData`.  Supports multiple authentication
methods and pagination patterns (offset, cursor, next-URL).
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx
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
# Config models
# ---------------------------------------------------------------------------


class AuthType(str, Enum):
    """Supported authentication schemes."""

    BEARER = "bearer"
    BASIC = "basic"
    API_KEY = "api_key"
    NONE = "none"


class PaginationType(str, Enum):
    """Supported pagination strategies."""

    OFFSET = "offset"
    CURSOR = "cursor"
    NEXT_URL = "next_url"
    NONE = "none"


class PaginationConfig(BaseModel):
    """Configuration for response pagination."""

    type: PaginationType = Field(
        default=PaginationType.NONE, description="Pagination strategy"
    )
    page_size: int = Field(
        default=100, ge=1, le=1000, description="Items per page"
    )
    offset_param: str = Field(
        default="offset", description="Query parameter name for offset pagination"
    )
    limit_param: str = Field(
        default="limit", description="Query parameter name for page size"
    )
    cursor_param: str = Field(
        default="cursor", description="Query parameter name for cursor pagination"
    )
    cursor_response_path: str = Field(
        default="next_cursor",
        description="Dot-separated path to the cursor value in the response",
    )
    next_url_response_path: str = Field(
        default="next",
        description="Dot-separated path to the next-page URL in the response",
    )
    total_path: str = Field(
        default="total",
        description="Dot-separated path to total item count (for offset pagination)",
    )
    max_pages: int = Field(
        default=100, ge=1, description="Safety limit on number of pages to fetch"
    )


class ResponseMapping(BaseModel):
    """JSONPath-like mapping from API response to ConversationData fields.

    Each value is a dot-separated path into the response JSON.
    """

    conversations_path: str = Field(
        default="data",
        description="Path to the array of conversations in the response",
    )
    conversation_id: str = Field(
        default="id", description="Path (relative to conversation) to its ID"
    )
    messages_path: str = Field(
        default="messages",
        description="Path (relative to conversation) to its messages array",
    )
    message_role: str = Field(
        default="role",
        description="Path (relative to message) to the role",
    )
    message_content: str = Field(
        default="content",
        description="Path (relative to message) to the text content",
    )
    message_timestamp: str = Field(
        default="timestamp",
        description="Path (relative to message) to the timestamp",
    )
    started_at: str = Field(
        default="started_at",
        description="Path (relative to conversation) to the start timestamp",
    )
    ended_at: str = Field(
        default="ended_at",
        description="Path (relative to conversation) to the end timestamp",
    )


class RestAPIConfig(ConnectorConfig):
    """Configuration for the generic REST API poller connector."""

    connector_type: str = "rest_api"
    url: str = Field(..., description="Base URL of the conversations endpoint")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Extra HTTP headers"
    )
    auth_type: AuthType = Field(
        default=AuthType.BEARER, description="Authentication method"
    )
    auth_token: str = Field(
        default="", description="Bearer token or API key value"
    )
    auth_username: str = Field(
        default="", description="Username for Basic auth"
    )
    auth_password: str = Field(
        default="", description="Password for Basic auth"
    )
    api_key_header: str = Field(
        default="X-API-Key",
        description="Header name for API-key auth",
    )
    polling_interval_seconds: int = Field(
        default=300, ge=10, description="Polling interval in seconds"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout"
    )
    pagination: PaginationConfig = Field(
        default_factory=PaginationConfig,
        description="Pagination configuration",
    )
    response_mapping: ResponseMapping = Field(
        default_factory=ResponseMapping,
        description="Mapping from response JSON to ConversationData",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class RestAPIConnector(BaseConnector):
    """Generic REST API poller that fetches conversations from any endpoint."""

    def __init__(self, config: RestAPIConfig) -> None:
        super().__init__(config)
        self._config: RestAPIConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client with the configured authentication."""
        self.logger.info("connecting", url=self._config.url)
        self._client = httpx.AsyncClient(
            headers=self._build_headers(),
            timeout=httpx.Timeout(self._config.timeout_seconds),
        )

        if await self.test_connection():
            self.status = ConnectorStatus.CONNECTED
            self.logger.info("connected")
            return True

        self.status = ConnectorStatus.ERROR
        self.logger.error("connection_failed")
        return False

    async def disconnect(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self.status = ConnectorStatus.DISCONNECTED
        self.logger.info("disconnected")

    async def test_connection(self) -> bool:
        """Make a lightweight GET to the configured URL to verify connectivity."""
        client = self._ensure_client()
        try:
            resp = await client.get(self._config.url, params={"limit": "1"})
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as exc:
            self.logger.warning(
                "connection_test_failed", status_code=exc.response.status_code
            )
            return False
        except httpx.HTTPError as exc:
            self.logger.warning("connection_test_error", error=str(exc))
            return False

    # -- data fetching -------------------------------------------------------

    async def fetch_conversations(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Poll the configured REST endpoint and return mapped conversations.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()
        mapping = self._config.response_mapping
        pagination = self._config.pagination

        conversations: list[ConversationData] = []
        page = 0
        offset = 0
        cursor: str | None = None
        url: str | None = self._config.url

        while url and len(conversations) < limit and page < pagination.max_pages:
            params = self._build_query_params(
                since=since,
                limit=min(pagination.page_size, limit - len(conversations)),
                offset=offset,
                cursor=cursor,
            )

            try:
                if url.startswith("http") and url != self._config.url:
                    # Absolute URL from next_url pagination
                    resp = await client.get(url)
                else:
                    resp = await client.get(url, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_http_error",
                    status_code=exc.response.status_code,
                    detail=exc.response.text[:500],
                )
                raise
            except httpx.HTTPError as exc:
                self.logger.error("fetch_error", error=str(exc))
                raise

            data = resp.json()
            raw_items = _resolve_path(data, mapping.conversations_path)

            if not isinstance(raw_items, list) or not raw_items:
                break

            for item in raw_items:
                if len(conversations) >= limit:
                    break
                conversations.append(self._map_conversation(item))

            # Advance pagination
            url, offset, cursor = self._advance_pagination(data, offset, len(raw_items))
            page += 1

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by appending the ID to the base URL."""
        self._require_connected()
        client = self._ensure_client()

        detail_url = f"{self._config.url.rstrip('/')}/{external_id}"

        try:
            resp = await client.get(detail_url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{external_id}' not found at {detail_url}"
                ) from exc
            raise

        raw = resp.json()
        return self._map_conversation(raw)

    # -- sync override -------------------------------------------------------

    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Run a poll-based sync cycle."""
        self.status = ConnectorStatus.SYNCING
        self.logger.info("sync_started", since=since)

        start = time.monotonic()
        errors: list[str] = []
        count = 0

        try:
            conversations = await self.fetch_conversations(since=since, limit=10_000)
            count = len(conversations)
        except Exception as exc:
            msg = f"Sync failed: {exc}"
            errors.append(msg)
            self.logger.error("sync_error", error=msg, exc_info=True)
            self.status = ConnectorStatus.ERROR
        else:
            self.status = ConnectorStatus.CONNECTED
            self.logger.info("sync_completed", conversations_synced=count)

        return SyncResult(
            conversations_synced=count,
            errors=errors,
            duration_seconds=round(time.monotonic() - start, 3),
        )

    # -- mapping helpers -----------------------------------------------------

    def _map_conversation(self, raw: dict[str, Any]) -> ConversationData:
        """Map a raw API response object to :class:`ConversationData`."""
        mapping = self._config.response_mapping

        external_id = str(_resolve_path(raw, mapping.conversation_id) or "")
        raw_messages = _resolve_path(raw, mapping.messages_path)
        messages: list[MessageData] = []

        if isinstance(raw_messages, list):
            for raw_msg in raw_messages:
                if not isinstance(raw_msg, dict):
                    continue
                messages.append(
                    MessageData(
                        role=str(_resolve_path(raw_msg, mapping.message_role) or "user"),
                        content=str(
                            _resolve_path(raw_msg, mapping.message_content) or ""
                        ),
                        timestamp=_parse_timestamp(
                            _resolve_path(raw_msg, mapping.message_timestamp)
                        ),
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

        return ConversationData(
            external_id=external_id,
            messages=messages,
            metadata={
                k: v
                for k, v in raw.items()
                if k
                not in (
                    mapping.conversation_id,
                    mapping.messages_path,
                    mapping.started_at,
                    mapping.ended_at,
                )
            },
            started_at=_parse_timestamp(_resolve_path(raw, mapping.started_at)),
            ended_at=_parse_timestamp(_resolve_path(raw, mapping.ended_at)),
        )

    # -- pagination helpers --------------------------------------------------

    def _build_query_params(
        self,
        *,
        since: datetime | None,
        limit: int,
        offset: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        """Build query parameters for a single page request."""
        pagination = self._config.pagination
        params: dict[str, Any] = {pagination.limit_param: limit}

        if since is not None:
            params["since"] = since.isoformat()

        if pagination.type == PaginationType.OFFSET:
            params[pagination.offset_param] = offset
        elif pagination.type == PaginationType.CURSOR and cursor:
            params[pagination.cursor_param] = cursor

        return params

    def _advance_pagination(
        self,
        data: dict[str, Any],
        current_offset: int,
        items_returned: int,
    ) -> tuple[str | None, int, str | None]:
        """Determine the next URL / offset / cursor based on the response.

        Returns:
            ``(next_url, new_offset, new_cursor)`` tuple.  ``next_url`` is
            ``None`` when pagination is exhausted.
        """
        pagination = self._config.pagination

        if pagination.type == PaginationType.OFFSET:
            new_offset = current_offset + items_returned
            total = _resolve_path(data, pagination.total_path)
            if isinstance(total, int) and new_offset >= total:
                return None, new_offset, None
            if items_returned < pagination.page_size:
                return None, new_offset, None
            return self._config.url, new_offset, None

        if pagination.type == PaginationType.CURSOR:
            next_cursor = _resolve_path(data, pagination.cursor_response_path)
            if not next_cursor:
                return None, 0, None
            return self._config.url, 0, str(next_cursor)

        if pagination.type == PaginationType.NEXT_URL:
            next_url = _resolve_path(data, pagination.next_url_response_path)
            if not next_url or not isinstance(next_url, str):
                return None, 0, None
            return next_url, 0, None

        # No pagination
        return None, 0, None

    # -- auth / header helpers -----------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers including authentication."""
        headers: dict[str, str] = {
            "Accept": "application/json",
            **self._config.headers,
        }

        match self._config.auth_type:
            case AuthType.BEARER:
                if self._config.auth_token:
                    headers["Authorization"] = f"Bearer {self._config.auth_token}"
            case AuthType.BASIC:
                creds = f"{self._config.auth_username}:{self._config.auth_password}"
                b64 = base64.b64encode(creds.encode()).decode()
                headers["Authorization"] = f"Basic {b64}"
            case AuthType.API_KEY:
                if self._config.auth_token:
                    headers[self._config.api_key_header] = self._config.auth_token
            case AuthType.NONE:
                pass

        return headers

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


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
    if value is None:
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
