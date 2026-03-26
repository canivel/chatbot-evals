"""Ada AI Customer Support platform connector.

Fetches conversation data from the Ada Conversations API (REST).  Ada is an
AI-first customer support platform that uses LLMs to auto-resolve customer
inquiries.  Conversations are retrieved via ``GET /conversations`` with
cursor-based pagination and individual details (including messages) via
``GET /conversations/{id}``.

Reference: https://developers.ada.cx/reference
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

_CONVERSATIONS_PATH = "/api/conversations"
_CONVERSATION_DETAIL_PATH = "/api/conversations/{conversation_id}"
_HEALTH_PATH = "/api/health"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class AdaConfig(ConnectorConfig):
    """Configuration specific to the Ada connector."""

    connector_type: str = "ada"
    api_key: str = Field(..., description="Ada API key (Bearer token)")
    base_url: str = Field(
        ...,
        description="Base URL of the Ada instance (e.g. https://yourcompany.ada.cx)",
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


class AdaConnector(BaseConnector):
    """Connector that pulls conversations from Ada via the Conversations API."""

    def __init__(self, config: AdaConfig) -> None:
        super().__init__(config)
        self._config: AdaConfig = config
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
        """Call the health endpoint to validate credentials."""
        client = self._ensure_client()
        try:
            resp = await client.get(_HEALTH_PATH)
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
        """Fetch conversations from Ada with cursor-based pagination.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        params: dict[str, Any] = {"limit": min(self._config.page_size, limit)}

        if since is not None:
            params["updated_after"] = since.isoformat()

        cursor: str | None = None

        while len(conversations) < limit:
            if cursor:
                params["cursor"] = cursor

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
            items: list[dict[str, Any]] = data.get("conversations", [])

            if not items:
                break

            for item in items:
                if len(conversations) >= limit:
                    break
                try:
                    full = await self._fetch_conversation_detail(
                        client, str(item.get("id", ""))
                    )
                    conversations.append(full)
                except Exception:
                    conversations.append(self._map_conversation_summary(item))

            # Advance cursor
            cursor = data.get("next_cursor")
            if not cursor:
                break

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its Ada conversation ID."""
        self._require_connected()
        client = self._ensure_client()
        return await self._fetch_conversation_detail(client, external_id)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_conversation_detail(
        self, client: httpx.AsyncClient, conversation_id: str
    ) -> ConversationData:
        """GET /api/conversations/{id} and map to :class:`ConversationData`."""
        path = _CONVERSATION_DETAIL_PATH.format(conversation_id=conversation_id)
        try:
            resp = await client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{conversation_id}' not found on Ada"
                ) from exc
            raise

        return self._map_conversation_detail(resp.json())

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_conversation_detail(raw: dict[str, Any]) -> ConversationData:
        """Map a full Ada conversation (with messages) to :class:`ConversationData`."""
        messages: list[MessageData] = []

        for msg in raw.get("messages", []):
            content = str(msg.get("content", "") or "").strip()
            if not content:
                continue
            messages.append(
                MessageData(
                    role=_map_source_role(msg.get("source", "")),
                    content=content,
                    timestamp=_parse_iso_dt(msg.get("created_at")),
                    metadata={
                        "source": msg.get("source", ""),
                        "message_id": msg.get("id", ""),
                    },
                )
            )

        return ConversationData(
            external_id=str(raw.get("id", "")),
            messages=messages,
            metadata={
                "resolution_status": raw.get("resolution_status", ""),
                "confidence_score": raw.get("confidence_score"),
                "intent": raw.get("intent", ""),
                "channel": raw.get("channel", ""),
                "tags": raw.get("tags", []),
            },
            started_at=_parse_iso_dt(raw.get("created_at")),
            ended_at=_parse_iso_dt(raw.get("ended_at")),
        )

    @staticmethod
    def _map_conversation_summary(raw: dict[str, Any]) -> ConversationData:
        """Map a list-level Ada conversation to :class:`ConversationData`."""
        return ConversationData(
            external_id=str(raw.get("id", "")),
            messages=[],
            metadata={
                "resolution_status": raw.get("resolution_status", ""),
                "confidence_score": raw.get("confidence_score"),
                "intent": raw.get("intent", ""),
            },
            started_at=_parse_iso_dt(raw.get("created_at")),
            ended_at=_parse_iso_dt(raw.get("ended_at")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Accept": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_source_role(source: str) -> str:
    """Normalise an Ada message source to a standard role string.

    Ada messages carry a ``source`` field:
    - ``"customer"`` -> ``"user"``
    - ``"bot"`` / ``"ada"`` -> ``"assistant"``
    - ``"agent"`` (human handoff) -> ``"assistant"``
    """
    source_lower = str(source).lower()
    mapping: dict[str, str] = {
        "customer": "user",
        "bot": "assistant",
        "ada": "assistant",
        "agent": "assistant",
    }
    return mapping.get(source_lower, "user")


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
