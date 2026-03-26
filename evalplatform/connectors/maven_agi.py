"""MavenAGI platform connector.

Fetches conversation data from the MavenAGI conversational AI platform via its
REST API.  Because the MavenAGI API surface is not fully public, endpoint paths
are defined as configurable placeholders that can be overridden per deployment.
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
# Default (placeholder) endpoint paths
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://api.mavenagi.com/v1"
_CONVERSATIONS_PATH = "/conversations"
_CONVERSATION_DETAIL_PATH = "/conversations/{conversation_id}"
_HEALTH_PATH = "/health"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class MavenAGIConfig(ConnectorConfig):
    """Configuration specific to the MavenAGI connector."""

    connector_type: str = "maven_agi"
    api_key: str = Field(..., description="MavenAGI API key")
    base_url: str = Field(
        default=_DEFAULT_BASE_URL, description="MavenAGI API base URL"
    )
    organization_id: str = Field(
        ..., description="MavenAGI organization identifier"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class MavenAGIConnector(BaseConnector):
    """Connector that pulls conversations from the MavenAGI platform."""

    def __init__(self, config: MavenAGIConfig) -> None:
        super().__init__(config)
        self._config: MavenAGIConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an ``httpx.AsyncClient`` and verify credentials."""
        self.logger.info("connecting", base_url=self._config.base_url)
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
        """Hit the health endpoint to validate credentials."""
        client = self._ensure_client()
        try:
            resp = await client.get(_HEALTH_PATH)
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as exc:
            self.logger.warning(
                "health_check_failed",
                status_code=exc.response.status_code,
            )
            return False
        except httpx.HTTPError as exc:
            self.logger.warning("health_check_error", error=str(exc))
            return False

    # -- data fetching -------------------------------------------------------

    async def fetch_conversations(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch conversations from the MavenAGI conversations endpoint.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        params: dict[str, Any] = {
            "organization_id": self._config.organization_id,
            "limit": min(limit, 100),
        }
        if since is not None:
            params["updated_after"] = since.isoformat()

        conversations: list[ConversationData] = []
        fetched = 0

        while fetched < limit:
            params["limit"] = min(limit - fetched, 100)

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
                conversations.append(self._map_conversation(item))

            fetched += len(items)

            # Cursor-based pagination
            next_cursor: str | None = data.get("next_cursor")
            if not next_cursor:
                break
            params["cursor"] = next_cursor

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its MavenAGI conversation ID."""
        self._require_connected()
        client = self._ensure_client()

        path = _CONVERSATION_DETAIL_PATH.format(conversation_id=external_id)
        params = {"organization_id": self._config.organization_id}

        try:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{external_id}' not found on MavenAGI"
                ) from exc
            raise

        return self._map_conversation(resp.json())

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_conversation(raw: dict[str, Any]) -> ConversationData:
        """Map a MavenAGI API conversation object to :class:`ConversationData`."""
        messages: list[MessageData] = []
        for msg in raw.get("messages", []):
            role = _map_role(msg.get("author", {}).get("type", "unknown"))
            timestamp = _parse_timestamp(msg.get("created_at"))
            messages.append(
                MessageData(
                    role=role,
                    content=msg.get("text", ""),
                    timestamp=timestamp,
                    metadata={
                        k: v
                        for k, v in msg.items()
                        if k not in ("text", "author", "created_at")
                    },
                )
            )

        started_at = _parse_timestamp(raw.get("created_at"))
        ended_at = _parse_timestamp(raw.get("ended_at"))

        return ConversationData(
            external_id=str(raw.get("id", "")),
            messages=messages,
            metadata={
                k: v
                for k, v in raw.items()
                if k not in ("id", "messages", "created_at", "ended_at")
            },
            started_at=started_at,
            ended_at=ended_at,
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Accept": "application/json",
            "X-Organization-Id": self._config.organization_id,
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        """Return the active HTTP client or raise."""
        if self._client is None:
            raise RuntimeError(
                "HTTP client not initialised. Call connect() first."
            )
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_role(author_type: str) -> str:
    """Normalise a MavenAGI author type to a standard role string."""
    mapping: dict[str, str] = {
        "user": "user",
        "human": "user",
        "end_user": "user",
        "bot": "assistant",
        "agent": "assistant",
        "assistant": "assistant",
        "system": "system",
    }
    return mapping.get(author_type.lower(), "user")


def _parse_timestamp(value: str | None) -> datetime | None:
    """Best-effort ISO-8601 timestamp parse."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
