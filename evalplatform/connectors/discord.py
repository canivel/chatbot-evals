"""Discord Bot platform connector.

Fetches conversation data from Discord channels via the REST API.  Messages
are grouped into conversations either by Discord thread or by time-windowed
proximity (messages within a configurable number of minutes of each other).

Bot-authored messages (``author.bot = true``) are mapped to ``"assistant"``;
all other messages are mapped to ``"user"``.

Reference: https://discord.com/developers/docs/resources/channel
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

_BASE_URL = "https://discord.com/api/v10"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class DiscordConfig(ConnectorConfig):
    """Configuration specific to the Discord Bot connector."""

    connector_type: str = "discord"
    bot_token: str = Field(..., description="Discord bot token")
    channel_ids: list[str] = Field(
        ..., description="List of Discord channel IDs to monitor"
    )
    time_window_minutes: int = Field(
        default=30,
        ge=1,
        description=(
            "For non-threaded channels, group messages within this many "
            "minutes of each other into a single conversation"
        ),
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Number of messages per page (max 100)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class DiscordConnector(BaseConnector):
    """Connector that pulls conversations from Discord channels."""

    def __init__(self, config: DiscordConfig) -> None:
        super().__init__(config)
        self._config: DiscordConfig = config
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
        """Call ``GET /channels/{id}`` on the first configured channel to validate the token."""
        client = self._ensure_client()
        if not self._config.channel_ids:
            self.logger.warning("no_channels_configured")
            return False

        try:
            resp = await client.get(f"/channels/{self._config.channel_ids[0]}")
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
        """Fetch conversations from all configured Discord channels.

        Messages are grouped into conversations by thread or time-window
        proximity.

        Args:
            since: Only return messages sent after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []

        for channel_id in self._config.channel_ids:
            if len(conversations) >= limit:
                break

            # Fetch threads in the channel
            thread_convos = await self._fetch_channel_threads(
                client, channel_id, since=since, limit=limit - len(conversations)
            )
            conversations.extend(thread_convos)

            if len(conversations) >= limit:
                break

            # Fetch non-threaded messages and group by time window
            windowed_convos = await self._fetch_channel_time_windowed(
                client, channel_id, since=since, limit=limit - len(conversations)
            )
            conversations.extend(windowed_convos)

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations[:limit]

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its external ID.

        Args:
            external_id: Either a thread channel ID (``"thread:<channel_id>"``)
                or a time-window key (``"window:<channel_id>:<first_msg_id>"``).

        Raises:
            ValueError: If the format is invalid or the conversation is not found.
        """
        self._require_connected()
        client = self._ensure_client()

        if external_id.startswith("thread:"):
            thread_channel_id = external_id[len("thread:"):]
            messages = await self._fetch_all_channel_messages(client, thread_channel_id)
            if not messages:
                raise ValueError(f"Thread '{thread_channel_id}' not found or empty")
            return self._map_messages_to_conversation(
                external_id, thread_channel_id, messages
            )

        if external_id.startswith("window:"):
            parts = external_id.split(":", 2)
            if len(parts) != 3:
                raise ValueError(
                    f"Invalid window external_id '{external_id}'. "
                    "Expected format: 'window:<channel_id>:<first_msg_id>'"
                )
            _, channel_id, first_msg_id = parts
            # Fetch messages around the anchor point
            messages = await self._fetch_messages_around(
                client, channel_id, first_msg_id
            )
            if not messages:
                raise ValueError(
                    f"Window starting at message '{first_msg_id}' not found "
                    f"in channel '{channel_id}'"
                )
            return self._map_messages_to_conversation(
                external_id, channel_id, messages
            )

        raise ValueError(
            f"Invalid external_id '{external_id}'. "
            "Expected prefix 'thread:' or 'window:'."
        )

    # -- thread fetching -----------------------------------------------------

    async def _fetch_channel_threads(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch active threads in a channel and return their messages as conversations."""
        conversations: list[ConversationData] = []

        try:
            resp = await client.get(f"/channels/{channel_id}/threads")
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            # Channel may not support threads or we lack permissions
            return conversations
        except httpx.HTTPError as exc:
            self.logger.warning(
                "fetch_threads_error", channel=channel_id, error=str(exc)
            )
            return conversations

        data = resp.json()
        threads: list[dict[str, Any]] = data.get("threads", [])

        for thread in threads:
            if len(conversations) >= limit:
                break
            thread_id = thread.get("id", "")
            if not thread_id:
                continue

            try:
                messages = await self._fetch_all_channel_messages(client, thread_id)
                if since:
                    messages = [
                        m for m in messages
                        if _parse_discord_timestamp(m.get("timestamp"))
                        and _parse_discord_timestamp(m.get("timestamp")) >= since  # type: ignore[operator]
                    ]
                if messages:
                    conversations.append(
                        self._map_messages_to_conversation(
                            f"thread:{thread_id}", thread_id, messages
                        )
                    )
            except Exception:
                self.logger.warning(
                    "fetch_thread_messages_failed",
                    thread_id=thread_id,
                    exc_info=True,
                )

        return conversations

    # -- time-windowed grouping ----------------------------------------------

    async def _fetch_channel_time_windowed(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch channel messages and group them by time window into conversations."""
        raw_messages = await self._fetch_all_channel_messages(
            client, channel_id, since=since
        )

        if not raw_messages:
            return []

        # Filter out messages that belong to threads (have a message_reference
        # pointing to a thread parent) to avoid double-counting.
        non_threaded = [
            m for m in raw_messages if not m.get("thread", {}).get("id")
        ]

        # Sort by timestamp ascending
        non_threaded.sort(key=lambda m: m.get("timestamp", ""))

        # Group into time windows
        groups: list[list[dict[str, Any]]] = []
        current_group: list[dict[str, Any]] = []

        for msg in non_threaded:
            msg_dt = _parse_discord_timestamp(msg.get("timestamp"))
            if not msg_dt:
                continue

            if current_group:
                last_dt = _parse_discord_timestamp(
                    current_group[-1].get("timestamp")
                )
                if last_dt and (msg_dt - last_dt) > timedelta(
                    minutes=self._config.time_window_minutes
                ):
                    groups.append(current_group)
                    current_group = []

            current_group.append(msg)

        if current_group:
            groups.append(current_group)

        # Convert groups to conversations
        conversations: list[ConversationData] = []
        for group in groups:
            if len(conversations) >= limit:
                break
            first_id = group[0].get("id", "unknown")
            conversations.append(
                self._map_messages_to_conversation(
                    f"window:{channel_id}:{first_id}", channel_id, group
                )
            )

        return conversations

    # -- raw message fetching ------------------------------------------------

    async def _fetch_all_channel_messages(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        *,
        since: datetime | None = None,
        max_messages: int = 1000,
    ) -> list[dict[str, Any]]:
        """Paginate through all messages in a channel using before/after cursors."""
        all_messages: list[dict[str, Any]] = []
        params: dict[str, Any] = {"limit": self._config.page_size}

        if since is not None:
            # Discord uses snowflake IDs; convert datetime to approximate snowflake
            params["after"] = _datetime_to_snowflake(since)

        while len(all_messages) < max_messages:
            try:
                resp = await client.get(
                    f"/channels/{channel_id}/messages", params=params
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_messages_error", channel=channel_id, error=str(exc)
                )
                raise

            batch: list[dict[str, Any]] = resp.json()
            if not batch:
                break

            all_messages.extend(batch)

            if len(batch) < self._config.page_size:
                break

            # Use the last message ID as the pagination cursor.
            # Discord returns messages newest-first by default, so the last
            # element in the response has the oldest ID.
            oldest_id = batch[-1].get("id")
            if not oldest_id:
                break
            params["before"] = oldest_id

        return all_messages

    async def _fetch_messages_around(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        message_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch messages around a specific message for context reconstruction."""
        try:
            resp = await client.get(
                f"/channels/{channel_id}/messages",
                params={"around": message_id, "limit": self._config.page_size},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            self.logger.error(
                "fetch_messages_around_error",
                channel=channel_id,
                message_id=message_id,
                error=str(exc),
            )
            raise

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_messages_to_conversation(
        external_id: str,
        channel_id: str,
        raw_messages: list[dict[str, Any]],
    ) -> ConversationData:
        """Map a list of Discord messages to :class:`ConversationData`."""
        # Sort ascending by timestamp for natural reading order
        sorted_msgs = sorted(raw_messages, key=lambda m: m.get("timestamp", ""))

        messages: list[MessageData] = []
        for msg in sorted_msgs:
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            author = msg.get("author", {})
            messages.append(
                MessageData(
                    role="assistant" if author.get("bot", False) else "user",
                    content=content,
                    timestamp=_parse_discord_timestamp(msg.get("timestamp")),
                    metadata={
                        "author_id": author.get("id", ""),
                        "author_username": author.get("username", ""),
                        "message_id": msg.get("id", ""),
                    },
                )
            )

        started_at = _parse_discord_timestamp(
            sorted_msgs[0].get("timestamp")
        ) if sorted_msgs else None
        ended_at = _parse_discord_timestamp(
            sorted_msgs[-1].get("timestamp")
        ) if sorted_msgs else None

        return ConversationData(
            external_id=external_id,
            messages=messages,
            metadata={"channel_id": channel_id},
            started_at=started_at,
            ended_at=ended_at,
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self._config.bot_token}",
            "Content-Type": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _parse_discord_timestamp(ts: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp as returned by the Discord API."""
    if ts is None:
        return None
    try:
        # Discord timestamps may include +00:00 or be naive
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _datetime_to_snowflake(dt: datetime) -> str:
    """Convert a datetime to an approximate Discord snowflake ID.

    Discord snowflakes encode a timestamp as
    ``(unix_ms - DISCORD_EPOCH) << 22``.
    """
    discord_epoch_ms = 1420070400000  # 2015-01-01T00:00:00Z in ms
    unix_ms = int(dt.timestamp() * 1000)
    snowflake = (unix_ms - discord_epoch_ms) << 22
    return str(max(snowflake, 0))
