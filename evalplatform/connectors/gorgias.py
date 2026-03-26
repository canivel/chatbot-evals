"""Gorgias platform connector.

Fetches conversation data from the Gorgias REST API.  Tickets are listed via
``GET /api/tickets`` and individual ticket messages are retrieved via
``GET /api/tickets/{id}/messages``.

Authentication uses HTTP Basic with ``email:api_key`` or a Bearer token.

Reference: https://developers.gorgias.com/reference
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

_TICKETS_PATH = "/api/tickets"
_TICKET_MESSAGES_PATH = "/api/tickets/{ticket_id}/messages"
_ACCOUNT_PATH = "/api/account"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class GorgiasConfig(ConnectorConfig):
    """Configuration specific to the Gorgias connector."""

    connector_type: str = "gorgias"
    domain: str = Field(
        ...,
        description="Gorgias domain (e.g. yourstore.gorgias.com)",
    )
    email: str = Field(
        default="",
        description="Gorgias account email for Basic auth",
    )
    api_key: str = Field(
        default="",
        description="Gorgias API key for Basic auth or Bearer token",
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=30,
        ge=1,
        le=100,
        description="Number of tickets per page",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class GorgiasConnector(BaseConnector):
    """Connector that pulls ticket conversations from the Gorgias API."""

    def __init__(self, config: GorgiasConfig) -> None:
        super().__init__(config)
        self._config: GorgiasConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify credentials."""
        self.logger.info("connecting")
        base_url = self._build_base_url()
        self._client = httpx.AsyncClient(
            base_url=base_url,
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
        """Call ``GET /api/account`` to validate credentials."""
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
        """Fetch tickets from Gorgias with cursor-based pagination.

        Args:
            since: Only return tickets updated after this timestamp.
            limit: Maximum number of tickets to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        cursor: str | None = None

        while len(conversations) < limit:
            params: dict[str, Any] = {
                "limit": min(self._config.page_size, limit - len(conversations)),
                "order_by": "updated_datetime:desc",
            }
            if cursor:
                params["cursor"] = cursor
            if since is not None:
                params["updated_datetime[gte]"] = since.isoformat()

            try:
                resp = await client.get(_TICKETS_PATH, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_tickets_http_error",
                    status_code=exc.response.status_code,
                    detail=exc.response.text[:500],
                )
                raise
            except httpx.HTTPError as exc:
                self.logger.error("fetch_tickets_error", error=str(exc))
                raise

            body = resp.json()
            items: list[dict[str, Any]] = body.get("data", [])

            if not items:
                break

            for item in items:
                if len(conversations) >= limit:
                    break
                ticket_id = str(item.get("id", ""))
                try:
                    conv = await self._fetch_ticket_messages(
                        client, ticket_id, item
                    )
                    conversations.append(conv)
                except Exception:
                    conversations.append(self._map_ticket_summary(item))

            # Cursor pagination -- Gorgias returns a ``meta.next_cursor``.
            meta = body.get("meta", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                break

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single ticket by its Gorgias ticket ID."""
        self._require_connected()
        client = self._ensure_client()
        return await self._fetch_ticket_messages(client, external_id)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_ticket_messages(
        self,
        client: httpx.AsyncClient,
        ticket_id: str,
        summary: dict[str, Any] | None = None,
    ) -> ConversationData:
        """GET messages for a ticket and map to :class:`ConversationData`.

        Handles cursor-based pagination to retrieve all messages.
        """
        path = _TICKET_MESSAGES_PATH.format(ticket_id=ticket_id)

        all_raw_messages: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"limit": 50, "order_by": "created_datetime:asc"}
            if cursor:
                params["cursor"] = cursor

            try:
                resp = await client.get(path, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise ValueError(
                        f"Ticket '{ticket_id}' not found on Gorgias"
                    ) from exc
                raise

            body = resp.json()
            items: list[dict[str, Any]] = body.get("data", [])
            all_raw_messages.extend(items)

            cursor = body.get("meta", {}).get("next_cursor")
            if not cursor or not items:
                break

        messages: list[MessageData] = []
        for msg in all_raw_messages:
            content = _extract_message_text(msg)
            if not content:
                continue
            messages.append(
                MessageData(
                    role=_map_sender_role(msg),
                    content=content,
                    timestamp=_parse_iso_dt(msg.get("created_datetime")),
                    metadata={
                        "channel": msg.get("channel", ""),
                        "via": msg.get("via", ""),
                        "message_id": msg.get("id", ""),
                        "from_agent": msg.get("from_agent", False),
                    },
                )
            )

        meta = summary or {}
        tags = meta.get("tags", [])
        tag_names: list[str] = []
        if isinstance(tags, list):
            tag_names = [
                str(t.get("name", "") if isinstance(t, dict) else t)
                for t in tags
            ]

        return ConversationData(
            external_id=ticket_id,
            messages=messages,
            metadata={
                "subject": meta.get("subject", ""),
                "status": meta.get("status", ""),
                "channel": meta.get("channel", ""),
                "tags": tag_names,
                "priority": meta.get("priority", ""),
                "assignee_user": meta.get("assignee_user", {}),
            },
            started_at=_parse_iso_dt(meta.get("created_datetime")),
            ended_at=_parse_iso_dt(meta.get("updated_datetime")),
        )

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_ticket_summary(raw: dict[str, Any]) -> ConversationData:
        """Map a list-level Gorgias ticket (no messages) to :class:`ConversationData`."""
        tags = raw.get("tags", [])
        tag_names: list[str] = []
        if isinstance(tags, list):
            tag_names = [
                str(t.get("name", "") if isinstance(t, dict) else t)
                for t in tags
            ]

        return ConversationData(
            external_id=str(raw.get("id", "")),
            messages=[],
            metadata={
                "subject": raw.get("subject", ""),
                "status": raw.get("status", ""),
                "channel": raw.get("channel", ""),
                "tags": tag_names,
                "priority": raw.get("priority", ""),
            },
            started_at=_parse_iso_dt(raw.get("created_datetime")),
            ended_at=_parse_iso_dt(raw.get("updated_datetime")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_base_url(self) -> str:
        """Build the base URL from the configured domain."""
        domain = self._config.domain.rstrip("/")
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        return domain

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with authentication."""
        headers: dict[str, str] = {"Accept": "application/json"}

        if self._config.email and self._config.api_key:
            # Basic auth with email:api_key
            credentials = f"{self._config.email}:{self._config.api_key}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        elif self._config.api_key:
            # Bearer token
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        return headers

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_sender_role(msg: dict[str, Any]) -> str:
    """Normalise a Gorgias message sender to a standard role string.

    Gorgias messages include a ``source`` dict with a ``type`` field
    (e.g. ``"customer"``, ``"agent"``, ``"rule"``).  The ``from_agent``
    boolean is a convenient fallback.
    """
    source = msg.get("source", {})
    if isinstance(source, dict):
        source_type = str(source.get("type", "")).lower()
        if source_type == "customer":
            return "user"
        if source_type in ("agent", "rule", "bot", "automation"):
            return "assistant"

    sender_type = str(msg.get("sender", {}).get("type", "")).lower() if isinstance(msg.get("sender"), dict) else ""
    if sender_type == "customer":
        return "user"
    if sender_type in ("agent", "bot"):
        return "assistant"

    if msg.get("from_agent"):
        return "assistant"

    return "user"


def _extract_message_text(msg: dict[str, Any]) -> str:
    """Extract plain-text content from a Gorgias message.

    Gorgias may store HTML in ``body_html`` and plain text in ``body_text``.
    """
    text = msg.get("body_text")
    if text:
        return str(text).strip()
    html = msg.get("body_html")
    if html:
        # Very simple HTML stripping -- just return the raw value.
        return str(html).strip()
    return str(msg.get("body", "") or "").strip()


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
