"""Botpress platform connector.

Fetches conversation data from the Botpress Cloud API.  Conversations are
listed via ``GET /v1/chat/conversations`` and individual message histories
are retrieved via ``GET /v1/chat/conversations/{id}/messages``.

Authentication uses a Personal Access Token (PAT) or a Bot Token in the
``Authorization`` header.

Reference: https://botpress.com/docs/api-documentation/
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

_BASE_URL = "https://api.botpress.cloud"
_CONVERSATIONS_PATH = "/v1/chat/conversations"
_MESSAGES_PATH = "/v1/chat/conversations/{conversation_id}/messages"
_BOT_PATH = "/v1/admin/bots/{bot_id}"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class BotpressConfig(ConnectorConfig):
    """Configuration specific to the Botpress connector."""

    connector_type: str = "botpress"
    token: str = Field(
        ..., description="Botpress Personal Access Token or Bot Token"
    )
    bot_id: str = Field(..., description="Botpress bot identifier")
    workspace_id: str = Field(
        default="", description="Botpress workspace identifier (for scoping)"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Number of conversations per page",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class BotpressConnector(BaseConnector):
    """Connector that pulls conversations from Botpress Cloud API."""

    def __init__(self, config: BotpressConfig) -> None:
        super().__init__(config)
        self._config: BotpressConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify the token."""
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
        """Call ``GET /v1/admin/bots/{bot_id}`` to validate credentials."""
        client = self._ensure_client()
        path = _BOT_PATH.format(bot_id=self._config.bot_id)
        try:
            resp = await client.get(path)
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
        """Fetch conversations from Botpress with cursor-based pagination.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        next_token: str | None = None

        while len(conversations) < limit:
            params: dict[str, Any] = {"limit": min(self._config.page_size, limit)}
            if next_token:
                params["nextToken"] = next_token

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

            body = resp.json()
            items: list[dict[str, Any]] = body.get("conversations", [])

            if not items:
                break

            for item in items:
                if len(conversations) >= limit:
                    break

                updated_at = item.get("updatedAt")
                if since is not None and updated_at:
                    updated_dt = _parse_iso_dt(updated_at)
                    if updated_dt is not None and updated_dt <= since:
                        continue

                conversation_id = str(item.get("id", ""))
                try:
                    conv = await self._fetch_conversation_messages(
                        client, conversation_id, item
                    )
                    conversations.append(conv)
                except Exception:
                    conversations.append(self._map_conversation_summary(item))

            next_token = body.get("meta", {}).get("nextToken") or body.get("nextToken")
            if not next_token:
                break

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its Botpress conversation ID."""
        self._require_connected()
        client = self._ensure_client()
        return await self._fetch_conversation_messages(client, external_id)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_conversation_messages(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
        summary: dict[str, Any] | None = None,
    ) -> ConversationData:
        """GET messages for a conversation and map to :class:`ConversationData`.

        Handles cursor-based pagination to retrieve all messages.
        """
        path = _MESSAGES_PATH.format(conversation_id=conversation_id)

        all_raw_messages: list[dict[str, Any]] = []
        next_token: str | None = None

        while True:
            params: dict[str, Any] = {}
            if next_token:
                params["nextToken"] = next_token

            try:
                resp = await client.get(path, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise ValueError(
                        f"Conversation '{conversation_id}' not found on Botpress"
                    ) from exc
                raise

            body = resp.json()
            items = body.get("messages", [])
            all_raw_messages.extend(items)

            next_token = body.get("meta", {}).get("nextToken") or body.get("nextToken")
            if not next_token or not items:
                break

        messages: list[MessageData] = []
        for msg in all_raw_messages:
            content = _extract_message_text(msg)
            if not content:
                continue
            messages.append(
                MessageData(
                    role=_map_message_role(msg),
                    content=content,
                    timestamp=_parse_iso_dt(msg.get("createdAt")),
                    metadata={
                        "type": msg.get("type", ""),
                        "payload": msg.get("payload", {}),
                    },
                )
            )

        # Ensure messages are ordered chronologically.
        messages.sort(key=lambda m: m.timestamp or datetime.min.replace(tzinfo=timezone.utc))

        meta = summary or {}
        return ConversationData(
            external_id=conversation_id,
            messages=messages,
            metadata={
                "channel": meta.get("channel", ""),
                "integration": meta.get("integration", ""),
                "tags": meta.get("tags", {}),
            },
            started_at=_parse_iso_dt(meta.get("createdAt")),
            ended_at=_parse_iso_dt(meta.get("updatedAt")),
        )

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_conversation_summary(raw: dict[str, Any]) -> ConversationData:
        """Map a list-level Botpress conversation to :class:`ConversationData`."""
        return ConversationData(
            external_id=str(raw.get("id", "")),
            messages=[],
            metadata={
                "channel": raw.get("channel", ""),
                "integration": raw.get("integration", ""),
                "tags": raw.get("tags", {}),
            },
            started_at=_parse_iso_dt(raw.get("createdAt")),
            ended_at=_parse_iso_dt(raw.get("updatedAt")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._config.token}",
            "Accept": "application/json",
        }
        if self._config.bot_id:
            headers["x-bot-id"] = self._config.bot_id
        if self._config.workspace_id:
            headers["x-workspace-id"] = self._config.workspace_id
        return headers

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_message_role(msg: dict[str, Any]) -> str:
    """Normalise a Botpress message to a standard role string.

    Botpress distinguishes messages by ``direction`` (``incoming`` vs
    ``outgoing``) or by ``userId`` / ``authorType``.
    """
    direction = str(msg.get("direction", "")).lower()
    if direction == "outgoing":
        return "assistant"
    if direction == "incoming":
        return "user"

    # Fall back to author type / tags.
    author_type = str(msg.get("authorType", "") or msg.get("type", "")).lower()
    if author_type in ("bot", "system"):
        return "assistant"
    return "user"


def _extract_message_text(msg: dict[str, Any]) -> str:
    """Extract plain-text content from a Botpress message payload."""
    # Direct text field
    text = msg.get("text")
    if text:
        return str(text).strip()

    # Payload-based content
    payload = msg.get("payload", {})
    if isinstance(payload, dict):
        text = payload.get("text") or payload.get("message") or payload.get("body")
        if text:
            return str(text).strip()

    return ""


def _parse_iso_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string to a timezone-aware datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
