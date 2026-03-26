"""Slack Bot platform connector.

Fetches conversation data from Slack channels via the Web API.  Each Slack
thread (a parent message plus its replies) is treated as a single conversation.
Bot-authored messages (identified by the ``bot_id`` field) are mapped to the
``"assistant"`` role; all other messages are mapped to ``"user"``.

Reference: https://api.slack.com/methods
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

_BASE_URL = "https://slack.com/api"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class SlackConfig(ConnectorConfig):
    """Configuration specific to the Slack Bot connector."""

    connector_type: str = "slack"
    bot_token: str = Field(
        ..., description="Slack Bot User OAuth Token (xoxb-...)"
    )
    channel_ids: list[str] = Field(
        ..., description="List of Slack channel IDs to monitor"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of messages per page (max 1000)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class SlackConnector(BaseConnector):
    """Connector that pulls threaded conversations from Slack channels."""

    def __init__(self, config: SlackConfig) -> None:
        super().__init__(config)
        self._config: SlackConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify the bot token."""
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
        """Call ``conversations.info`` on the first configured channel to validate the token."""
        client = self._ensure_client()
        if not self._config.channel_ids:
            self.logger.warning("no_channels_configured")
            return False

        try:
            resp = await client.get(
                "/conversations.info",
                params={"channel": self._config.channel_ids[0]},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok", False):
                self.logger.warning(
                    "auth_check_failed", error=data.get("error", "unknown")
                )
                return False
            return True
        except httpx.HTTPError as exc:
            self.logger.warning("auth_check_error", error=str(exc))
            return False

    # -- data fetching -------------------------------------------------------

    async def fetch_conversations(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch threaded conversations from all configured Slack channels.

        Each thread (parent message + replies) is mapped to one
        :class:`ConversationData`.  Only parent messages that have at least one
        reply are included (pure single messages without a thread are skipped).

        Args:
            since: Only return conversations whose parent message was sent
                after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []

        for channel_id in self._config.channel_ids:
            if len(conversations) >= limit:
                break
            channel_convos = await self._fetch_channel_threads(
                client,
                channel_id,
                since=since,
                limit=limit - len(conversations),
            )
            conversations.extend(channel_convos)

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations[:limit]

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single Slack thread by ``channel_id:thread_ts``.

        Args:
            external_id: A string in the form ``"<channel_id>:<thread_ts>"``.

        Raises:
            ValueError: If the format is invalid or the thread is not found.
        """
        self._require_connected()
        client = self._ensure_client()

        parts = external_id.split(":", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid external_id '{external_id}'. "
                "Expected format: '<channel_id>:<thread_ts>'"
            )
        channel_id, thread_ts = parts

        replies = await self._fetch_thread_replies(client, channel_id, thread_ts)
        if not replies:
            raise ValueError(
                f"Thread '{thread_ts}' not found in channel '{channel_id}'"
            )
        return self._map_thread(channel_id, thread_ts, replies)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_channel_threads(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Retrieve parent messages from a channel, then fetch their replies."""
        conversations: list[ConversationData] = []
        cursor: str | None = None

        while len(conversations) < limit:
            params: dict[str, Any] = {
                "channel": channel_id,
                "limit": min(self._config.page_size, 200),
            }
            if since is not None:
                params["oldest"] = str(since.timestamp())
            if cursor:
                params["cursor"] = cursor

            try:
                resp = await client.get("/conversations.history", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_history_error", channel=channel_id, error=str(exc)
                )
                raise

            data = resp.json()
            if not data.get("ok", False):
                self.logger.error(
                    "fetch_history_api_error",
                    channel=channel_id,
                    error=data.get("error", "unknown"),
                )
                break

            messages: list[dict[str, Any]] = data.get("messages", [])

            for msg in messages:
                if len(conversations) >= limit:
                    break
                # Only process threaded messages (those that have replies).
                thread_ts = msg.get("thread_ts")
                reply_count = msg.get("reply_count", 0)
                if thread_ts and reply_count and reply_count > 0:
                    try:
                        replies = await self._fetch_thread_replies(
                            client, channel_id, thread_ts
                        )
                        conversations.append(
                            self._map_thread(channel_id, thread_ts, replies)
                        )
                    except Exception:
                        self.logger.warning(
                            "fetch_thread_failed",
                            channel=channel_id,
                            thread_ts=thread_ts,
                            exc_info=True,
                        )

            # Cursor-based pagination
            response_metadata = data.get("response_metadata", {})
            cursor = response_metadata.get("next_cursor") or None
            if not cursor:
                break

        return conversations

    async def _fetch_thread_replies(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        thread_ts: str,
    ) -> list[dict[str, Any]]:
        """Fetch all replies in a thread, handling cursor pagination."""
        all_messages: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": self._config.page_size,
            }
            if cursor:
                params["cursor"] = cursor

            try:
                resp = await client.get("/conversations.replies", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_replies_error",
                    channel=channel_id,
                    thread_ts=thread_ts,
                    error=str(exc),
                )
                raise

            data = resp.json()
            if not data.get("ok", False):
                self.logger.error(
                    "fetch_replies_api_error",
                    channel=channel_id,
                    thread_ts=thread_ts,
                    error=data.get("error", "unknown"),
                )
                break

            all_messages.extend(data.get("messages", []))

            response_metadata = data.get("response_metadata", {})
            cursor = response_metadata.get("next_cursor") or None
            if not cursor:
                break

        return all_messages

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_thread(
        channel_id: str,
        thread_ts: str,
        raw_messages: list[dict[str, Any]],
    ) -> ConversationData:
        """Map a Slack thread to :class:`ConversationData`."""
        messages: list[MessageData] = []

        for msg in raw_messages:
            text = msg.get("text", "").strip()
            if not text:
                continue
            messages.append(
                MessageData(
                    role=_map_message_role(msg),
                    content=text,
                    timestamp=_ts_to_dt(msg.get("ts")),
                    metadata={
                        "user": msg.get("user", ""),
                        "bot_id": msg.get("bot_id", ""),
                        "subtype": msg.get("subtype", ""),
                    },
                )
            )

        started_at = _ts_to_dt(raw_messages[0].get("ts")) if raw_messages else None
        ended_at = _ts_to_dt(raw_messages[-1].get("ts")) if raw_messages else None

        return ConversationData(
            external_id=f"{channel_id}:{thread_ts}",
            messages=messages,
            metadata={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "reply_count": len(raw_messages) - 1 if raw_messages else 0,
            },
            started_at=started_at,
            ended_at=ended_at,
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_message_role(msg: dict[str, Any]) -> str:
    """Determine the role of a Slack message author.

    Messages with a ``bot_id`` field or ``subtype`` of ``"bot_message"`` are
    mapped to ``"assistant"``; all others to ``"user"``.
    """
    if msg.get("bot_id") or msg.get("subtype") == "bot_message":
        return "assistant"
    return "user"


def _ts_to_dt(ts: str | None) -> datetime | None:
    """Convert a Slack timestamp (e.g. ``'1234567890.123456'``) to a datetime."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
