"""Crisp platform connector.

Fetches conversation data from the Crisp REST API v1.  Conversations are
listed via ``GET /website/{website_id}/conversations`` and individual message
histories are retrieved via
``GET /website/{website_id}/conversation/{session_id}/messages``.

Authentication uses HTTP Basic with a plugin *token_id* / *token_key* pair.

Reference: https://docs.crisp.chat/references/rest-api/v1/
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

_BASE_URL = "https://api.crisp.chat/v1"
_CONVERSATIONS_PATH = "/website/{website_id}/conversations/{page_number}"
_MESSAGES_PATH = "/website/{website_id}/conversation/{session_id}/messages"
_WEBSITE_PATH = "/website/{website_id}"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class CrispConfig(ConnectorConfig):
    """Configuration specific to the Crisp connector."""

    connector_type: str = "crisp"
    token_id: str = Field(..., description="Crisp plugin token identifier")
    token_key: str = Field(..., description="Crisp plugin token secret key")
    website_id: str = Field(..., description="Crisp website ID to pull conversations from")
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of conversations per page",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class CrispConnector(BaseConnector):
    """Connector that pulls conversations from Crisp via REST API v1."""

    def __init__(self, config: CrispConfig) -> None:
        super().__init__(config)
        self._config: CrispConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify credentials against the Crisp API."""
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
        """Call ``GET /website/{website_id}`` to validate credentials."""
        client = self._ensure_client()
        path = _WEBSITE_PATH.format(website_id=self._config.website_id)
        try:
            resp = await client.get(path)
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
        """Fetch conversations from Crisp with page-number pagination.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        page_number = 1

        while len(conversations) < limit:
            path = _CONVERSATIONS_PATH.format(
                website_id=self._config.website_id,
                page_number=page_number,
            )
            try:
                resp = await client.get(path)
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

            body = resp.json()
            items: list[dict[str, Any]] = body.get("data", [])

            if not items:
                break

            for item in items:
                if len(conversations) >= limit:
                    break

                updated = item.get("updated_at")
                if since is not None and updated is not None:
                    updated_dt = _millis_to_dt(updated)
                    if updated_dt is not None and updated_dt <= since:
                        continue

                session_id = str(item.get("session_id", ""))
                try:
                    conv = await self._fetch_conversation_messages(
                        client, session_id, item
                    )
                    conversations.append(conv)
                except Exception:
                    conversations.append(self._map_conversation_summary(item))

            page_number += 1

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its Crisp session ID."""
        self._require_connected()
        client = self._ensure_client()
        return await self._fetch_conversation_messages(client, external_id)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_conversation_messages(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        summary: dict[str, Any] | None = None,
    ) -> ConversationData:
        """GET messages for a conversation and map to :class:`ConversationData`."""
        path = _MESSAGES_PATH.format(
            website_id=self._config.website_id,
            session_id=session_id,
        )
        try:
            resp = await client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{session_id}' not found on Crisp"
                ) from exc
            raise

        body = resp.json()
        raw_messages: list[dict[str, Any]] = body.get("data", [])

        messages: list[MessageData] = []
        for msg in raw_messages:
            content = str(msg.get("content", "") or "").strip()
            if not content:
                continue
            messages.append(
                MessageData(
                    role=_map_origin_role(msg.get("from", "")),
                    content=content,
                    timestamp=_millis_to_dt(msg.get("timestamp")),
                    metadata={
                        "fingerprint": msg.get("fingerprint", ""),
                        "type": msg.get("type", ""),
                    },
                )
            )

        meta = summary or {}
        return ConversationData(
            external_id=session_id,
            messages=messages,
            metadata={
                "state": meta.get("state", ""),
                "availability": meta.get("availability", ""),
            },
            started_at=_millis_to_dt(meta.get("created_at")),
            ended_at=_millis_to_dt(meta.get("updated_at")),
        )

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_conversation_summary(raw: dict[str, Any]) -> ConversationData:
        """Map a list-level Crisp conversation (no messages) to :class:`ConversationData`."""
        messages: list[MessageData] = []
        last_message = raw.get("last_message")
        if last_message:
            messages.append(
                MessageData(
                    role=_map_origin_role(raw.get("meta", {}).get("from", "user")),
                    content=str(last_message).strip(),
                    timestamp=_millis_to_dt(raw.get("updated_at")),
                )
            )

        return ConversationData(
            external_id=str(raw.get("session_id", "")),
            messages=messages,
            metadata={"state": raw.get("state", "")},
            started_at=_millis_to_dt(raw.get("created_at")),
            ended_at=_millis_to_dt(raw.get("updated_at")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with Basic authentication."""
        credentials = f"{self._config.token_id}:{self._config.token_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_origin_role(origin: str) -> str:
    """Normalise a Crisp message origin to a standard role string.

    Crisp uses ``"user"`` for visitor messages and ``"operator"`` for agent /
    bot replies.
    """
    origin_lower = str(origin).lower()
    if origin_lower in ("operator", "bot"):
        return "assistant"
    return "user"


def _millis_to_dt(value: int | float | str | None) -> datetime | None:
    """Convert a millisecond epoch timestamp to a timezone-aware datetime.

    Crisp timestamps are typically in milliseconds.
    """
    if value is None:
        return None
    try:
        ts = int(value)
        # Crisp uses millisecond timestamps
        if ts > 1e12:
            ts = ts // 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
