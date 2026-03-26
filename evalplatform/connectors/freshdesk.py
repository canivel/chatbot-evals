"""Freshdesk platform connector.

Fetches ticket conversation data from the Freshdesk REST API v2.  Tickets are
retrieved via ``GET /api/v2/tickets`` and individual conversation threads via
``GET /api/v2/tickets/{id}/conversations``.

Reference: https://developers.freshdesk.com/api/
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

_TICKETS_PATH = "/api/v2/tickets"
_TICKET_CONVERSATIONS_PATH = "/api/v2/tickets/{ticket_id}/conversations"
_SETTINGS_PATH = "/api/v2/settings/helpdesk"
_PER_PAGE = 100


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class FreshdeskConfig(ConnectorConfig):
    """Configuration specific to the Freshdesk connector."""

    connector_type: str = "freshdesk"
    api_key: str = Field(..., description="Freshdesk API key")
    domain: str = Field(
        ...,
        description="Freshdesk domain (e.g. yourcompany.freshdesk.com)",
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Number of tickets per page (max 100)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class FreshdeskConnector(BaseConnector):
    """Connector that pulls ticket conversations from Freshdesk via REST API v2.

    Freshdesk uses Basic authentication where the username is the API key and
    the password is ``X``.  Ticket conversations are mapped so that requester
    messages become ``"user"`` and agent/bot replies become ``"assistant"``.

    Reference: https://developers.freshdesk.com/api/
    """

    def __init__(self, config: FreshdeskConfig) -> None:
        super().__init__(config)
        self._config: FreshdeskConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify the API key."""
        self.logger.info("connecting")
        self._client = httpx.AsyncClient(
            base_url=f"https://{self._config.domain}",
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
        """Call ``GET /api/v2/settings/helpdesk`` to validate the API key."""
        client = self._ensure_client()
        try:
            resp = await client.get(_SETTINGS_PATH)
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
        """Fetch ticket conversations from Freshdesk with pagination.

        Args:
            since: Only return tickets updated after this timestamp.
            limit: Maximum number of ticket conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        page = 1

        while len(conversations) < limit:
            params: dict[str, Any] = {
                "per_page": min(self._config.page_size, _PER_PAGE),
                "page": page,
                "order_by": "updated_at",
                "order_type": "desc",
            }
            if since is not None:
                params["updated_since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

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

            tickets: list[dict[str, Any]] = resp.json()
            if not tickets:
                break

            for ticket in tickets:
                if len(conversations) >= limit:
                    break
                try:
                    conv = await self._fetch_ticket_conversation(
                        client, ticket
                    )
                    conversations.append(conv)
                except Exception:
                    # Fall back to a summary representation from the ticket.
                    conversations.append(self._map_ticket_summary(ticket))

            # If we received fewer than a full page, we've exhausted results.
            if len(tickets) < self._config.page_size:
                break

            page += 1

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single ticket conversation by its Freshdesk ticket ID."""
        self._require_connected()
        client = self._ensure_client()

        # Fetch the ticket itself.
        try:
            resp = await client.get(f"{_TICKETS_PATH}/{external_id}")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Ticket '{external_id}' not found on Freshdesk"
                ) from exc
            raise

        ticket: dict[str, Any] = resp.json()
        return await self._fetch_ticket_conversation(client, ticket)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_ticket_conversation(
        self, client: httpx.AsyncClient, ticket: dict[str, Any]
    ) -> ConversationData:
        """Fetch conversation entries for a ticket and map to :class:`ConversationData`."""
        ticket_id = str(ticket.get("id", ""))
        path = _TICKET_CONVERSATIONS_PATH.format(ticket_id=ticket_id)

        all_entries: list[dict[str, Any]] = []
        page = 1

        while True:
            try:
                resp = await client.get(
                    path, params={"per_page": _PER_PAGE, "page": page}
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_ticket_conversations_error",
                    ticket_id=ticket_id,
                    status_code=exc.response.status_code,
                )
                break
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_ticket_conversations_transport_error",
                    ticket_id=ticket_id,
                    error=str(exc),
                )
                break

            entries: list[dict[str, Any]] = resp.json()
            if not entries:
                break

            all_entries.extend(entries)

            if len(entries) < _PER_PAGE:
                break
            page += 1

        return self._map_ticket_to_conversation(ticket, all_entries)

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_ticket_to_conversation(
        ticket: dict[str, Any], entries: list[dict[str, Any]]
    ) -> ConversationData:
        """Map a Freshdesk ticket and its conversation entries to :class:`ConversationData`."""
        messages: list[MessageData] = []

        # The initial ticket description is treated as the first user message.
        description = str(ticket.get("description_text", "") or ticket.get("description", "") or "").strip()
        if description:
            messages.append(
                MessageData(
                    role="user",
                    content=description,
                    timestamp=_parse_dt(ticket.get("created_at")),
                    metadata={"entry_type": "ticket_description"},
                )
            )

        for entry in entries:
            body = str(entry.get("body_text", "") or entry.get("body", "") or "").strip()
            if not body:
                continue

            messages.append(
                MessageData(
                    role=_map_source_role(entry.get("source", 0), entry.get("incoming", True)),
                    content=body,
                    timestamp=_parse_dt(entry.get("created_at")),
                    metadata={
                        "entry_id": entry.get("id", ""),
                        "source": entry.get("source", 0),
                        "incoming": entry.get("incoming", True),
                    },
                )
            )

        return ConversationData(
            external_id=str(ticket.get("id", "")),
            messages=messages,
            metadata={
                "subject": ticket.get("subject", ""),
                "status": ticket.get("status"),
                "priority": ticket.get("priority"),
                "type": ticket.get("type", ""),
                "tags": ticket.get("tags", []),
                "requester_id": ticket.get("requester_id"),
                "responder_id": ticket.get("responder_id"),
            },
            started_at=_parse_dt(ticket.get("created_at")),
            ended_at=_parse_dt(ticket.get("updated_at")),
        )

    @staticmethod
    def _map_ticket_summary(ticket: dict[str, Any]) -> ConversationData:
        """Map a ticket without conversation entries to a minimal :class:`ConversationData`."""
        messages: list[MessageData] = []
        description = str(ticket.get("description_text", "") or ticket.get("description", "") or "").strip()
        if description:
            messages.append(
                MessageData(
                    role="user",
                    content=description,
                    timestamp=_parse_dt(ticket.get("created_at")),
                    metadata={"entry_type": "ticket_description"},
                )
            )

        return ConversationData(
            external_id=str(ticket.get("id", "")),
            messages=messages,
            metadata={
                "subject": ticket.get("subject", ""),
                "status": ticket.get("status"),
            },
            started_at=_parse_dt(ticket.get("created_at")),
            ended_at=_parse_dt(ticket.get("updated_at")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        # Freshdesk uses Basic auth: api_key:X
        credentials = base64.b64encode(
            f"{self._config.api_key}:X".encode()
        ).decode()
        return {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_source_role(source: int, incoming: bool) -> str:
    """Normalise a Freshdesk conversation entry to a standard role string.

    Freshdesk marks entries as *incoming* (from the customer) or outgoing
    (from an agent/bot).  The ``source`` field indicates the channel but the
    ``incoming`` boolean is the most reliable role indicator.
    """
    if incoming:
        return "user"
    return "assistant"


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp returned by Freshdesk into a timezone-aware datetime."""
    if not value:
        return None
    try:
        # Freshdesk returns ISO-8601 strings like "2024-01-15T10:30:00Z"
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
