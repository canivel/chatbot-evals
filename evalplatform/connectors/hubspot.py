"""HubSpot Conversations connector.

Fetches conversation thread data from the HubSpot Conversations API v3.
Threads are retrieved via ``GET /conversations/v3/conversations/threads`` and
individual thread messages via
``GET /conversations/v3/conversations/threads/{id}/messages``.

Reference: https://developers.hubspot.com/docs/api/conversations/conversations
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

_BASE_URL = "https://api.hubapi.com"
_THREADS_PATH = "/conversations/v3/conversations/threads"
_THREAD_MESSAGES_PATH = "/conversations/v3/conversations/threads/{thread_id}/messages"
_ACCOUNT_INFO_PATH = "/integrations/v1/me"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class HubSpotConfig(ConnectorConfig):
    """Configuration specific to the HubSpot Conversations connector."""

    connector_type: str = "hubspot"
    access_token: str = Field(
        ...,
        description="HubSpot private app token or OAuth access token",
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Number of threads per page (max 100)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class HubSpotConnector(BaseConnector):
    """Connector that pulls conversation threads from HubSpot via the Conversations API v3.

    HubSpot conversation threads are paginated using a cursor-based ``after``
    parameter.  Individual messages within a thread are fetched separately.
    Sender types (``VISITOR``, ``CONTACT``, ``BOT``, ``AGENT``) are normalised
    to the canonical ``"user"`` / ``"assistant"`` roles.

    Reference: https://developers.hubspot.com/docs/api/conversations/conversations
    """

    def __init__(self, config: HubSpotConfig) -> None:
        super().__init__(config)
        self._config: HubSpotConfig = config
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
        """Call ``GET /integrations/v1/me`` to validate the access token."""
        client = self._ensure_client()
        try:
            resp = await client.get(_ACCOUNT_INFO_PATH)
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
        """Fetch conversation threads from HubSpot with cursor-based pagination.

        Args:
            since: Only return threads updated after this timestamp.
            limit: Maximum number of threads to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        after: str | None = None

        while len(conversations) < limit:
            params: dict[str, Any] = {
                "limit": min(self._config.page_size, limit - len(conversations)),
            }
            if after is not None:
                params["after"] = after
            if since is not None:
                # HubSpot filters by latestMessageTimestamp
                params["latestMessageTimestampAfter"] = since.strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"
                )

            try:
                resp = await client.get(_THREADS_PATH, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_threads_http_error",
                    status_code=exc.response.status_code,
                    detail=exc.response.text[:500],
                )
                raise
            except httpx.HTTPError as exc:
                self.logger.error("fetch_threads_error", error=str(exc))
                raise

            data = resp.json()
            results: list[dict[str, Any]] = data.get("results", [])
            if not results:
                break

            for thread in results:
                if len(conversations) >= limit:
                    break
                thread_id = str(thread.get("id", ""))
                try:
                    conv = await self._fetch_thread_with_messages(
                        client, thread_id, thread
                    )
                    conversations.append(conv)
                except Exception:
                    conversations.append(self._map_thread_summary(thread))

            # Cursor-based pagination via paging.next.after
            paging = data.get("paging", {})
            next_page = paging.get("next", {})
            after = next_page.get("after") if next_page else None
            if after is None:
                break

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation thread by its HubSpot thread ID."""
        self._require_connected()
        client = self._ensure_client()

        # Fetch thread metadata.
        try:
            resp = await client.get(f"{_THREADS_PATH}/{external_id}")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Thread '{external_id}' not found on HubSpot"
                ) from exc
            raise

        thread: dict[str, Any] = resp.json()
        return await self._fetch_thread_with_messages(client, external_id, thread)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_thread_with_messages(
        self,
        client: httpx.AsyncClient,
        thread_id: str,
        thread_summary: dict[str, Any],
    ) -> ConversationData:
        """Fetch messages for a thread and build :class:`ConversationData`."""
        path = _THREAD_MESSAGES_PATH.format(thread_id=thread_id)
        all_messages_raw: list[dict[str, Any]] = []
        after: str | None = None

        while True:
            params: dict[str, Any] = {"limit": 100}
            if after is not None:
                params["after"] = after

            try:
                resp = await client.get(path, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_messages_http_error",
                    thread_id=thread_id,
                    status_code=exc.response.status_code,
                )
                break
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_messages_transport_error",
                    thread_id=thread_id,
                    error=str(exc),
                )
                break

            data = resp.json()
            results: list[dict[str, Any]] = data.get("results", [])
            if not results:
                break

            all_messages_raw.extend(results)

            # Cursor-based pagination
            paging = data.get("paging", {})
            next_page = paging.get("next", {})
            after = next_page.get("after") if next_page else None
            if after is None:
                break

        return self._map_thread(thread_summary, all_messages_raw)

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_thread(
        thread: dict[str, Any], messages_raw: list[dict[str, Any]]
    ) -> ConversationData:
        """Map a HubSpot thread and its messages to :class:`ConversationData`."""
        messages: list[MessageData] = []

        # Sort messages by creation time.
        sorted_msgs = sorted(
            messages_raw,
            key=lambda m: m.get("createdAt", ""),
        )

        for msg in sorted_msgs:
            text = _extract_message_text(msg)
            if not text:
                continue

            senders = msg.get("senders", [])
            sender_type = ""
            sender_name = ""
            if senders:
                first_sender = senders[0]
                sender_type = str(
                    first_sender.get("senderField", "") or first_sender.get("actorId", "")
                )
                sender_name = str(first_sender.get("name", ""))

            role = _map_sender_role(
                msg.get("type", ""),
                msg.get("direction", ""),
                senders,
            )

            messages.append(
                MessageData(
                    role=role,
                    content=text,
                    timestamp=_parse_hubspot_dt(msg.get("createdAt")),
                    metadata={
                        "message_id": msg.get("id", ""),
                        "sender_type": sender_type,
                        "sender_name": sender_name,
                        "direction": msg.get("direction", ""),
                        "channel_type": msg.get("channelId", ""),
                    },
                )
            )

        return ConversationData(
            external_id=str(thread.get("id", "")),
            messages=messages,
            metadata={
                "status": thread.get("status", ""),
                "channel": thread.get("originalChannelId", ""),
                "inbox_id": thread.get("inboxId", ""),
                "assigned_agent": thread.get("assignedTo", ""),
                "latest_message_timestamp": thread.get(
                    "latestMessageTimestamp", ""
                ),
            },
            started_at=_parse_hubspot_dt(thread.get("createdAt")),
            ended_at=_parse_hubspot_dt(thread.get("closedAt")),
        )

    @staticmethod
    def _map_thread_summary(thread: dict[str, Any]) -> ConversationData:
        """Map a thread listing (no messages) to a minimal :class:`ConversationData`."""
        return ConversationData(
            external_id=str(thread.get("id", "")),
            messages=[],
            metadata={
                "status": thread.get("status", ""),
                "channel": thread.get("originalChannelId", ""),
            },
            started_at=_parse_hubspot_dt(thread.get("createdAt")),
            ended_at=_parse_hubspot_dt(thread.get("closedAt")),
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


def _map_sender_role(
    msg_type: str, direction: str, senders: list[dict[str, Any]]
) -> str:
    """Normalise a HubSpot message sender to a standard role string.

    HubSpot sender types include ``VISITOR``, ``CONTACT`` (user-side) and
    ``BOT``, ``AGENT`` (assistant-side).  The message ``direction`` field
    (``INCOMING`` / ``OUTGOING``) is also considered.
    """
    # Check senders for explicit type information.
    for sender in senders:
        actor_id = str(sender.get("actorId", "") or "").upper()
        sender_field = str(sender.get("senderField", "") or "").upper()

        for val in (actor_id, sender_field):
            if any(t in val for t in ("VISITOR", "CONTACT")):
                return "user"
            if any(t in val for t in ("BOT", "AGENT", "SYSTEM")):
                return "assistant"

    # Fall back to direction: INCOMING = from user, OUTGOING = from assistant.
    direction_upper = direction.upper()
    if direction_upper == "INCOMING":
        return "user"
    if direction_upper == "OUTGOING":
        return "assistant"

    return "user"


def _extract_message_text(msg: dict[str, Any]) -> str:
    """Extract plain-text content from a HubSpot message object."""
    # HubSpot messages carry text in various fields.
    text = str(msg.get("text", "") or "").strip()
    if text:
        return text

    # Rich text / HTML may be in richText or body.
    rich_text = str(msg.get("richText", "") or "").strip()
    if rich_text:
        # Simple HTML tag stripping for a best-effort plain text.
        import re

        return re.sub(r"<[^>]+>", "", rich_text).strip()

    return ""


def _parse_hubspot_dt(value: str | int | None) -> datetime | None:
    """Parse a HubSpot timestamp into a timezone-aware datetime.

    HubSpot returns timestamps as either ISO-8601 strings or millisecond
    epoch integers.
    """
    if value is None:
        return None

    # Millisecond epoch.
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None

    # ISO-8601 string.
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

        # Millisecond epoch as string.
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

    return None
