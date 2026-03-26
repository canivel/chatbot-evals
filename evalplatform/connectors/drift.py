"""Drift platform connector.

Fetches conversation data from the Drift REST API.  Conversations are
retrieved via ``GET /conversations`` and individual conversation messages via
``GET /conversations/{id}/messages``.

Reference: https://devdocs.drift.com/docs/
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import Field

import structlog

from evalplatform.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    ConversationData,
    MessageData,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://driftapi.com"
_CONVERSATIONS_PATH = "/conversations"
_CONVERSATION_MESSAGES_PATH = "/conversations/{conversation_id}/messages"
_TOKEN_CHECK_PATH = "/contacts"  # lightweight endpoint for auth verification


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class DriftConfig(ConnectorConfig):
    """Configuration specific to the Drift connector."""

    connector_type: str = "drift"
    access_token: str = Field(
        ..., description="Drift OAuth Bearer access token"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Number of conversations per page (max 50)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class DriftConnector(BaseConnector):
    """Connector that pulls conversations from Drift via the REST API.

    Drift conversations are listed via the conversations endpoint and
    individual messages are fetched per conversation.  Message author types
    (``end_user``, ``bot``, ``agent``) are normalised to the canonical
    ``"user"`` / ``"assistant"`` roles.

    Reference: https://devdocs.drift.com/docs/
    """

    def __init__(self, config: DriftConfig) -> None:
        super().__init__(config)
        self._config: DriftConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify the access token."""
        self.logger.info("connecting")
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
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
        """Call ``GET /contacts`` with a minimal query to validate the token."""
        client = self._ensure_client()
        try:
            resp = await client.get(_TOKEN_CHECK_PATH, params={"limit": 1})
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as exc:
            self.logger.warning(
                "auth_check_failed", status_code=exc.response.status_code
            )
            return False
        except httpx.HTTPError as exc:
            self.logger.warning("auth_check_error", error=str(exc))
            return False

    # -- data fetching -------------------------------------------------------

    async def fetch_conversations(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch conversations from Drift with offset-based pagination.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        offset = 0

        while len(conversations) < limit:
            params: dict[str, Any] = {
                "limit": min(self._config.page_size, limit - len(conversations)),
                "offset": offset,
            }

            try:
                resp = await client.get(_CONVERSATIONS_PATH, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_conversations_http_error",
                    status_code=exc.response.status_code,
                    detail=exc.response.text[:500],
                )
                raise
            except httpx.HTTPError as exc:
                self.logger.error("fetch_conversations_error", error=str(exc))
                raise

            data = resp.json()
            items: list[dict[str, Any]] = data.get("data", [])
            if not items:
                break

            for item in items:
                if len(conversations) >= limit:
                    break

                conv_id = str(item.get("id", ""))
                updated_at = item.get("updatedAt")

                # Filter by 'since' if provided (Drift uses millisecond timestamps).
                if since is not None and updated_at is not None:
                    conv_updated = _epoch_ms_to_dt(updated_at)
                    if conv_updated is not None and conv_updated <= since:
                        continue

                try:
                    conv = await self._fetch_conversation_with_messages(
                        client, conv_id, item
                    )
                    conversations.append(conv)
                except Exception:
                    # Fall back to summary without messages.
                    conversations.append(self._map_conversation_summary(item))

            # If fewer items than requested, no more pages.
            if len(items) < self._config.page_size:
                break

            offset += len(items)

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its Drift conversation ID."""
        self._require_connected()
        client = self._ensure_client()

        # Fetch conversation metadata.
        try:
            resp = await client.get(f"{_CONVERSATIONS_PATH}/{external_id}")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{external_id}' not found on Drift"
                ) from exc
            raise

        data = resp.json()
        item: dict[str, Any] = data.get("data", {})

        return await self._fetch_conversation_with_messages(
            client, external_id, item
        )

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_conversation_with_messages(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
        summary: dict[str, Any],
    ) -> ConversationData:
        """Fetch messages for a conversation and build :class:`ConversationData`."""
        path = _CONVERSATION_MESSAGES_PATH.format(conversation_id=conversation_id)
        all_messages_raw: list[dict[str, Any]] = []
        next_offset: int | None = 0

        while next_offset is not None:
            params: dict[str, Any] = {"limit": 50}
            if next_offset > 0:
                params["offset"] = next_offset

            try:
                resp = await client.get(path, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_messages_http_error",
                    conversation_id=conversation_id,
                    status_code=exc.response.status_code,
                )
                break
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_messages_transport_error",
                    conversation_id=conversation_id,
                    error=str(exc),
                )
                break

            data = resp.json()
            msgs: list[dict[str, Any]] = data.get("data", [])
            if not msgs:
                break

            all_messages_raw.extend(msgs)

            # Drift uses pagination metadata or returns fewer items.
            pagination = data.get("pagination", {})
            if pagination.get("more", False):
                next_offset = (next_offset or 0) + len(msgs)
            else:
                next_offset = None

        return self._map_conversation(summary, all_messages_raw)

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_conversation(
        summary: dict[str, Any], messages_raw: list[dict[str, Any]]
    ) -> ConversationData:
        """Map a Drift conversation and its messages to :class:`ConversationData`."""
        messages: list[MessageData] = []

        # Sort messages by creation time.
        sorted_msgs = sorted(
            messages_raw, key=lambda m: m.get("createdAt", 0)
        )

        for msg in sorted_msgs:
            body = str(msg.get("body", "") or "").strip()
            if not body:
                continue

            msg_type = str(msg.get("type", "")).lower()
            # Only include chat messages (skip system events like "routing").
            if msg_type not in ("chat", "private_prompt", ""):
                continue

            author = msg.get("author", {})
            messages.append(
                MessageData(
                    role=_map_author_role(author),
                    content=body,
                    timestamp=_epoch_ms_to_dt(msg.get("createdAt")),
                    metadata={
                        "message_id": msg.get("id", ""),
                        "message_type": msg_type,
                        "author_type": author.get("type", ""),
                        "author_id": str(author.get("id", "")),
                    },
                )
            )

        return ConversationData(
            external_id=str(summary.get("id", "")),
            messages=messages,
            metadata={
                "status": summary.get("status", ""),
                "contact_id": summary.get("contactId", ""),
                "inbox_id": summary.get("inboxId", ""),
                "tags": summary.get("tags", []),
            },
            started_at=_epoch_ms_to_dt(summary.get("createdAt")),
            ended_at=_epoch_ms_to_dt(summary.get("updatedAt")),
        )

    @staticmethod
    def _map_conversation_summary(item: dict[str, Any]) -> ConversationData:
        """Map a Drift conversation listing (no messages) to a minimal :class:`ConversationData`."""
        return ConversationData(
            external_id=str(item.get("id", "")),
            messages=[],
            metadata={
                "status": item.get("status", ""),
                "contact_id": item.get("contactId", ""),
            },
            started_at=_epoch_ms_to_dt(item.get("createdAt")),
            ended_at=_epoch_ms_to_dt(item.get("updatedAt")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_author_role(author: dict[str, Any]) -> str:
    """Normalise a Drift author type to a standard role string.

    Drift author types include ``end_user``, ``bot``, ``agent``, ``team``.
    """
    author_type = str(author.get("type", "")).lower()
    mapping: dict[str, str] = {
        "end_user": "user",
        "contact": "user",
        "visitor": "user",
        "bot": "assistant",
        "agent": "assistant",
        "team": "assistant",
    }
    return mapping.get(author_type, "user")


def _epoch_ms_to_dt(value: int | str | None) -> datetime | None:
    """Convert a millisecond epoch timestamp to a timezone-aware datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
