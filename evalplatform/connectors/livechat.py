"""LiveChat platform connector.

Fetches chat archive data from the LiveChat Agent Chat API v3.5.  Chat
archives are retrieved via ``GET /v3.5/agent/action/list_archives`` which
returns chats with their full message history.

Reference: https://developers.livechat.com/docs/messaging/agent-chat-api
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

_BASE_URL = "https://api.livechatinc.com"
_LIST_ARCHIVES_PATH = "/v3.5/agent/action/list_archives"
_LIST_CHATS_PATH = "/v3.5/agent/action/list_chats"
_GET_CHAT_PATH = "/v3.5/agent/action/get_chat"
_ME_PATH = "/v3.5/agent/action/get_customer"  # lightweight auth check


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class LiveChatConfig(ConnectorConfig):
    """Configuration specific to the LiveChat connector."""

    connector_type: str = "livechat"
    access_token: str = Field(
        ...,
        description="LiveChat Personal Access Token or OAuth access token",
    )
    organization_id: str = Field(
        ..., description="LiveChat organization ID"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Number of chats per page (max 100)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class LiveChatConnector(BaseConnector):
    """Connector that pulls chat archives from LiveChat via the Agent Chat API v3.5.

    LiveChat chat archives include the full message thread.  Each message's
    ``author_id`` is resolved via the ``user_type`` field on thread users to
    determine whether the author is a customer (``"user"``) or an agent/bot
    (``"assistant"``).

    Pagination is cursor-based using ``page_id`` returned by the API.

    Reference: https://developers.livechat.com/docs/messaging/agent-chat-api
    """

    def __init__(self, config: LiveChatConfig) -> None:
        super().__init__(config)
        self._config: LiveChatConfig = config
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
        """Make a minimal ``list_archives`` request to validate the access token."""
        client = self._ensure_client()
        try:
            # Use a minimal request to verify credentials.
            payload: dict[str, Any] = {"limit": 1}
            resp = await client.post(_LIST_ARCHIVES_PATH, json=payload)
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
        """Fetch chat archives from LiveChat with cursor-based pagination.

        Args:
            since: Only return chats created after this timestamp.
            limit: Maximum number of chats to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        page_id: str | None = None

        while len(conversations) < limit:
            payload: dict[str, Any] = {
                "limit": min(self._config.page_size, limit - len(conversations)),
            }
            if page_id is not None:
                payload["page_id"] = page_id
            if since is not None:
                payload["filters"] = {
                    "from": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }

            try:
                resp = await client.post(_LIST_ARCHIVES_PATH, json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_archives_http_error",
                    status_code=exc.response.status_code,
                    detail=exc.response.text[:500],
                )
                raise
            except httpx.HTTPError as exc:
                self.logger.error("fetch_archives_error", error=str(exc))
                raise

            data = resp.json()
            chats: list[dict[str, Any]] = data.get("chats", [])
            if not chats:
                break

            for chat in chats:
                if len(conversations) >= limit:
                    break
                conversations.append(self._map_chat(chat))

            # Cursor-based pagination: next_page_id
            page_id = data.get("next_page_id")
            if not page_id:
                break

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single chat by its LiveChat chat ID."""
        self._require_connected()
        client = self._ensure_client()

        try:
            payload: dict[str, Any] = {"chat_id": external_id}
            resp = await client.post(_GET_CHAT_PATH, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Chat '{external_id}' not found on LiveChat"
                ) from exc
            raise

        data = resp.json()
        return self._map_chat(data)

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_chat(chat: dict[str, Any]) -> ConversationData:
        """Map a LiveChat chat archive to :class:`ConversationData`.

        A chat contains ``thread`` objects, each with a list of ``events``
        (messages).  The ``users`` array provides ``user_type`` for each
        participant, which is used to determine roles.
        """
        # Build a lookup from user IDs to their type.
        users: list[dict[str, Any]] = chat.get("users", [])
        user_type_map: dict[str, str] = {}
        for user in users:
            uid = str(user.get("id", ""))
            utype = str(user.get("type", "") or user.get("user_type", "")).lower()
            user_type_map[uid] = utype

        messages: list[MessageData] = []

        # LiveChat may return a single thread or multiple threads.
        threads: list[dict[str, Any]] = chat.get("threads", []) or chat.get("thread", [])
        if isinstance(threads, dict):
            threads = [threads]

        for thread in threads:
            events: list[dict[str, Any]] = thread.get("events", [])
            for event in events:
                event_type = str(event.get("type", "")).lower()
                # Only process message events (skip system, file, rich_message, etc. without text).
                if event_type not in ("message", "filled_form", ""):
                    # For non-message events, check if there is text content.
                    text = str(event.get("text", "") or "").strip()
                    if not text:
                        continue
                else:
                    text = str(event.get("text", "") or "").strip()
                    if not text:
                        continue

                author_id = str(event.get("author_id", ""))
                role = _map_user_type_to_role(
                    user_type_map.get(author_id, "")
                )

                messages.append(
                    MessageData(
                        role=role,
                        content=text,
                        timestamp=_parse_livechat_dt(event.get("created_at")),
                        metadata={
                            "event_id": event.get("id", ""),
                            "event_type": event_type,
                            "author_id": author_id,
                            "thread_id": thread.get("id", ""),
                        },
                    )
                )

        # Determine conversation timestamps.
        chat_id = str(chat.get("id", ""))
        created_at: datetime | None = None
        ended_at: datetime | None = None

        if threads:
            first_thread = threads[0]
            created_at = _parse_livechat_dt(first_thread.get("created_at"))
            last_thread = threads[-1]
            ended_at = _parse_livechat_dt(last_thread.get("closed_at"))

        # Fall back to chat-level properties.
        if created_at is None:
            created_at = _parse_livechat_dt(chat.get("created_at"))

        properties = chat.get("properties", {})
        routing = properties.get("routing", {})
        source = properties.get("source", {})

        return ConversationData(
            external_id=chat_id,
            messages=messages,
            metadata={
                "tags": [
                    t.get("name", "") for t in chat.get("tags", [])
                    if isinstance(t, dict)
                ] if isinstance(chat.get("tags"), list) else [],
                "agents": [
                    str(u.get("id", ""))
                    for u in users
                    if str(u.get("type", "")).lower() == "agent"
                ],
                "rating": chat.get("rating"),
                "routing": routing,
                "source": source,
            },
            started_at=created_at,
            ended_at=ended_at,
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Organization-Id": self._config.organization_id,
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_user_type_to_role(user_type: str) -> str:
    """Normalise a LiveChat user type to a standard role string.

    LiveChat user types include ``customer``, ``agent``, and ``supervisor``.
    """
    mapping: dict[str, str] = {
        "customer": "user",
        "visitor": "user",
        "agent": "assistant",
        "supervisor": "assistant",
        "bot": "assistant",
    }
    return mapping.get(user_type.lower(), "user")


def _parse_livechat_dt(value: str | None) -> datetime | None:
    """Parse a LiveChat ISO-8601 datetime string into a timezone-aware datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
