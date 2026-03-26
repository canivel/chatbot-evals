"""Yellow.ai Enterprise AI Chatbot platform connector.

Fetches conversation data from the Yellow.ai Data Explorer / Insights API.
Yellow.ai is an enterprise conversational AI platform.  Conversations are
listed via ``GET /data/conversations`` and individual message histories via
``GET /data/conversations/{id}/messages`` with offset-based pagination.

Reference: https://docs.yellow.ai/docs/platform_concepts/Getting%20Started/api-keys
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

_CONVERSATIONS_PATH = "/api/data/conversations"
_MESSAGES_PATH = "/api/data/conversations/{conversation_id}/messages"
_BOT_PATH = "/api/bot/{bot_id}"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class YellowAIConfig(ConnectorConfig):
    """Configuration specific to the Yellow.ai connector."""

    connector_type: str = "yellow_ai"
    api_key: str = Field(..., description="Yellow.ai API key")
    bot_id: str = Field(..., description="Yellow.ai bot ID")
    base_url: str = Field(
        default="https://cloud.yellow.ai",
        description="Base URL of the Yellow.ai API (e.g. https://cloud.yellow.ai)",
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Number of items per page",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class YellowAIConnector(BaseConnector):
    """Connector that pulls conversations from Yellow.ai via the Data Explorer API."""

    def __init__(self, config: YellowAIConfig) -> None:
        super().__init__(config)
        self._config: YellowAIConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify the API key."""
        self.logger.info("connecting")
        self._client = httpx.AsyncClient(
            base_url=self._config.base_url.rstrip("/"),
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
        """Attempt a lightweight API call to validate the API key and bot ID."""
        client = self._ensure_client()
        try:
            # Try fetching conversations with limit=1 as a health check
            resp = await client.get(
                _CONVERSATIONS_PATH,
                params={
                    "bot": self._config.bot_id,
                    "limit": 1,
                },
            )
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
        """Fetch conversations from Yellow.ai with offset-based pagination.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        offset = 0
        page_size = min(self._config.page_size, limit)

        while len(conversations) < limit:
            params: dict[str, Any] = {
                "bot": self._config.bot_id,
                "limit": page_size,
                "offset": offset,
            }

            if since is not None:
                params["start_date"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

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
            items: list[dict[str, Any]] = data.get("data", data.get("conversations", []))

            if not items:
                break

            for item in items:
                if len(conversations) >= limit:
                    break
                conversation_id = str(
                    item.get("id", "") or item.get("conversation_id", "")
                )
                try:
                    messages = await self._fetch_messages(client, conversation_id)
                    conversations.append(
                        self._map_conversation(conversation_id, item, messages)
                    )
                except Exception:
                    # Fall back to summary without messages
                    conversations.append(
                        self._map_conversation(conversation_id, item, [])
                    )

            # If we got fewer items than page_size, no more pages
            if len(items) < page_size:
                break

            offset += page_size

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its Yellow.ai conversation ID.

        Args:
            external_id: The conversation ID on Yellow.ai.

        Raises:
            ValueError: If the conversation cannot be found.
        """
        self._require_connected()
        client = self._ensure_client()

        # Fetch the conversation metadata
        try:
            resp = await client.get(
                _CONVERSATIONS_PATH,
                params={
                    "bot": self._config.bot_id,
                    "conversation_id": external_id,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{external_id}' not found on Yellow.ai"
                ) from exc
            raise

        data = resp.json()
        items: list[dict[str, Any]] = data.get("data", data.get("conversations", []))

        if not items:
            raise ValueError(f"Conversation '{external_id}' not found on Yellow.ai")

        item = items[0]
        messages = await self._fetch_messages(client, external_id)
        return self._map_conversation(external_id, item, messages)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_messages(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch all messages for a conversation with offset-based pagination."""
        all_messages: list[dict[str, Any]] = []
        offset = 0
        page_size = self._config.page_size

        while True:
            path = _MESSAGES_PATH.format(conversation_id=conversation_id)
            params: dict[str, Any] = {
                "bot": self._config.bot_id,
                "limit": page_size,
                "offset": offset,
            }

            try:
                resp = await client.get(path, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                break
            except httpx.HTTPError:
                break

            data = resp.json()
            messages: list[dict[str, Any]] = data.get(
                "data", data.get("messages", [])
            )

            if not messages:
                break

            all_messages.extend(messages)

            if len(messages) < page_size:
                break

            offset += page_size

        return all_messages

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_conversation(
        conversation_id: str,
        item: dict[str, Any],
        raw_messages: list[dict[str, Any]],
    ) -> ConversationData:
        """Map a Yellow.ai conversation and its messages to :class:`ConversationData`."""
        messages: list[MessageData] = []

        for msg in raw_messages:
            content = str(msg.get("text", "") or msg.get("message", "") or "").strip()
            if not content:
                continue

            sender = str(msg.get("sender", "") or msg.get("sender_type", "")).upper()

            messages.append(
                MessageData(
                    role=_map_sender_role(sender),
                    content=content,
                    timestamp=_parse_timestamp(
                        msg.get("timestamp") or msg.get("created_at")
                    ),
                    metadata={
                        "sender_type": sender,
                        "message_id": msg.get("id", msg.get("message_id", "")),
                        "intent": msg.get("intent", ""),
                        "confidence": msg.get("confidence"),
                    },
                )
            )

        return ConversationData(
            external_id=conversation_id,
            messages=messages,
            metadata={
                "intent": item.get("intent", ""),
                "confidence": item.get("confidence"),
                "ticket_id": item.get("ticket_id", ""),
                "tags": item.get("tags", []),
                "channel": item.get("channel", ""),
                "status": item.get("status", ""),
                "bot_id": item.get("bot", item.get("bot_id", "")),
            },
            started_at=_parse_timestamp(
                item.get("created_at") or item.get("start_time")
            ),
            ended_at=_parse_timestamp(
                item.get("updated_at") or item.get("end_time")
            ),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._config.api_key,
            "Accept": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_sender_role(sender: str) -> str:
    """Normalise a Yellow.ai sender type to a standard role string.

    Yellow.ai messages have a sender type:
    - ``"USER"`` -> ``"user"``
    - ``"BOT"`` -> ``"assistant"``
    - ``"AGENT"`` (human handoff) -> ``"assistant"``
    """
    mapping: dict[str, str] = {
        "USER": "user",
        "BOT": "assistant",
        "AGENT": "assistant",
    }
    return mapping.get(sender.upper(), "user")


def _parse_timestamp(value: str | int | float | None) -> datetime | None:
    """Parse a timestamp to a timezone-aware datetime.

    Handles ISO-8601 strings and epoch timestamps (seconds or milliseconds).
    """
    if value is None:
        return None

    # Try ISO-8601 string first
    if isinstance(value, str):
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass
        # Try parsing as numeric string
        try:
            value = float(value)
        except (ValueError, TypeError):
            return None

    # Numeric timestamp (epoch)
    try:
        ts = float(value)
        # If timestamp looks like milliseconds, convert to seconds
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
