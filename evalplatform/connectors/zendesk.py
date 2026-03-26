"""Zendesk Chat / Messaging connector.

Fetches chat transcripts from the Zendesk Chat API and maps them to the
canonical :class:`ConversationData` model.

Reference:
- Chat API: https://developer.zendesk.com/api-reference/live-chat/chat-api/chats/
- Sunshine Conversations: https://developer.zendesk.com/api-reference/agent-workspace/
"""

from __future__ import annotations

import base64
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

_CHATS_PATH = "/api/v2/chats"
_CHAT_DETAIL_PATH = "/api/v2/chats/{chat_id}"
_ACCOUNT_PATH = "/api/v2/account"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ZendeskConfig(ConnectorConfig):
    """Configuration specific to the Zendesk connector."""

    connector_type: str = "zendesk"
    subdomain: str = Field(
        ..., description="Zendesk subdomain (e.g. 'acme' for acme.zendesk.com)"
    )
    api_token: str = Field(..., description="Zendesk API token")
    email: str = Field(
        ..., description="Email address associated with the API token"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=200,
        description="Number of chats per page",
    )

    @property
    def base_url(self) -> str:
        """Construct the base URL from the subdomain."""
        return f"https://{self.subdomain}.zendesk.com"


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class ZendeskConnector(BaseConnector):
    """Connector that pulls chat transcripts from Zendesk Chat / Messaging."""

    def __init__(self, config: ZendeskConfig) -> None:
        super().__init__(config)
        self._config: ZendeskConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify credentials."""
        self.logger.info("connecting", subdomain=self._config.subdomain)
        self._client = httpx.AsyncClient(
            base_url=self._config.base_url,
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
        """Hit the account endpoint to validate credentials."""
        client = self._ensure_client()
        try:
            resp = await client.get(_ACCOUNT_PATH)
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
        """Fetch chat transcripts from Zendesk with pagination.

        Args:
            since: Only return chats updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        params: dict[str, Any] = {"limit": min(self._config.page_size, limit)}

        if since is not None:
            params["start_time"] = int(since.timestamp())

        next_url: str | None = _CHATS_PATH

        while next_url and len(conversations) < limit:
            try:
                if next_url.startswith("http"):
                    resp = await client.get(next_url)
                else:
                    resp = await client.get(next_url, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_chats_http_error",
                    status_code=exc.response.status_code,
                    detail=exc.response.text[:500],
                )
                raise
            except httpx.HTTPError as exc:
                self.logger.error("fetch_chats_error", error=str(exc))
                raise

            data = resp.json()
            items: list[dict[str, Any]] = data.get("chats", data.get("results", []))

            for item in items:
                if len(conversations) >= limit:
                    break
                conversations.append(self._map_chat(item))

            # Zendesk uses next_page URL for pagination
            next_url = data.get("next_page") or data.get("next_url")
            params = {}  # absolute URL carries its own params

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single chat by its Zendesk chat ID."""
        self._require_connected()
        client = self._ensure_client()

        path = _CHAT_DETAIL_PATH.format(chat_id=external_id)
        try:
            resp = await client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Chat '{external_id}' not found on Zendesk"
                ) from exc
            raise

        return self._map_chat(resp.json())

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_chat(raw: dict[str, Any]) -> ConversationData:
        """Map a Zendesk chat object to :class:`ConversationData`."""
        messages: list[MessageData] = []

        # The ``history`` field contains the ordered chat events.
        history: list[dict[str, Any]] = raw.get("history", [])
        for event in history:
            event_type = event.get("type", "")
            if event_type not in ("chat.msg", "chat.message", "msg"):
                # Skip non-message events (join, leave, system, etc.)
                continue

            messages.append(
                MessageData(
                    role=_map_sender_role(event.get("sender_type", "")),
                    content=event.get("msg", event.get("message", "")),
                    timestamp=_parse_timestamp(event.get("timestamp")),
                    metadata={
                        "display_name": event.get("display_name", ""),
                        "event_type": event_type,
                    },
                )
            )

        # Some Zendesk endpoints return messages at top level instead of history
        if not messages:
            for msg in raw.get("messages", []):
                messages.append(
                    MessageData(
                        role=_map_sender_role(msg.get("role", msg.get("type", ""))),
                        content=msg.get("content", msg.get("message", msg.get("body", ""))),
                        timestamp=_parse_timestamp(
                            msg.get("timestamp", msg.get("created_at"))
                        ),
                        metadata={
                            "display_name": msg.get("display_name", ""),
                        },
                    )
                )

        started_at = _parse_timestamp(
            raw.get("started_at", raw.get("start_timestamp", raw.get("created_at")))
        )
        ended_at = _parse_timestamp(
            raw.get("ended_at", raw.get("end_timestamp"))
        )

        return ConversationData(
            external_id=str(raw.get("id", "")),
            messages=messages,
            metadata={
                "department": raw.get("department_name", ""),
                "tags": raw.get("tags", []),
                "rating": raw.get("rating"),
                "visitor": raw.get("visitor", {}),
                "agent_names": raw.get("agent_names", []),
            },
            started_at=started_at,
            ended_at=ended_at,
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with Basic authentication (email/token)."""
        credentials = f"{self._config.email}/token:{self._config.api_token}"
        b64 = base64.b64encode(credentials.encode()).decode()
        return {
            "Authorization": f"Basic {b64}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_sender_role(sender_type: str) -> str:
    """Normalise a Zendesk sender type to a standard role string."""
    mapping: dict[str, str] = {
        "visitor": "user",
        "customer": "user",
        "end_user": "user",
        "user": "user",
        "agent": "assistant",
        "admin": "assistant",
        "trigger": "system",
        "system": "system",
    }
    return mapping.get(sender_type.lower(), "user")


def _parse_timestamp(value: str | int | float | None) -> datetime | None:
    """Best-effort timestamp parse.  Accepts epoch seconds or ISO-8601 strings."""
    if value is None:
        return None

    # Epoch (int or float or numeric string)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError):
            return None

    # String
    value_str = str(value)
    if value_str.replace(".", "").replace("-", "").isdigit():
        try:
            return datetime.fromtimestamp(float(value_str), tz=timezone.utc)
        except (ValueError, OSError):
            pass

    try:
        dt = datetime.fromisoformat(value_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
