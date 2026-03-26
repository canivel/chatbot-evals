"""Intercom platform connector.

Fetches conversation data from the Intercom REST API v2.  Conversations are
retrieved via ``GET /conversations`` and individual conversation details
(including *conversation parts* that become messages) via
``GET /conversations/{id}``.

Reference: https://developers.intercom.com/docs/references/rest-api/api.intercom.io/conversations/
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

_BASE_URL = "https://api.intercom.io"
_API_VERSION = "2.10"
_CONVERSATIONS_PATH = "/conversations"
_CONVERSATION_DETAIL_PATH = "/conversations/{conversation_id}"
_ME_PATH = "/me"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class IntercomConfig(ConnectorConfig):
    """Configuration specific to the Intercom connector."""

    connector_type: str = "intercom"
    access_token: str = Field(..., description="Intercom access token")
    workspace_id: str = Field(
        default="", description="Intercom workspace ID (for logging / filtering)"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=150,
        description="Number of conversations per page (max 150)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class IntercomConnector(BaseConnector):
    """Connector that pulls conversations from Intercom via REST API v2."""

    def __init__(self, config: IntercomConfig) -> None:
        super().__init__(config)
        self._config: IntercomConfig = config
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
        """Call ``GET /me`` to validate the access token."""
        client = self._ensure_client()
        try:
            resp = await client.get(_ME_PATH)
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
        """Fetch conversations from Intercom with pagination.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        params: dict[str, Any] = {"per_page": min(self._config.page_size, limit)}

        if since is not None:
            params["updated_after"] = int(since.timestamp())

        next_url: str | None = _CONVERSATIONS_PATH

        while next_url and len(conversations) < limit:
            try:
                if next_url.startswith("http"):
                    # Absolute URL returned by Intercom pagination
                    resp = await client.get(next_url)
                else:
                    resp = await client.get(next_url, params=params)
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

            for item in items:
                if len(conversations) >= limit:
                    break
                # The list endpoint often lacks full parts; fetch detail.
                try:
                    full = await self._fetch_conversation_detail(
                        client, str(item.get("id", ""))
                    )
                    conversations.append(full)
                except Exception:
                    # Fall back to the summary representation.
                    conversations.append(self._map_conversation_summary(item))

            # Determine next page
            pages = data.get("pages", {})
            next_page = pages.get("next")
            if isinstance(next_page, dict):
                next_url = next_page.get("starting_after")
                if next_url:
                    params["starting_after"] = next_url
                    next_url = _CONVERSATIONS_PATH
                else:
                    next_url = None
            elif isinstance(next_page, str):
                next_url = next_page
                params = {}  # absolute URL carries its own params
            else:
                next_url = None

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its Intercom ID."""
        self._require_connected()
        client = self._ensure_client()
        return await self._fetch_conversation_detail(client, external_id)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_conversation_detail(
        self, client: httpx.AsyncClient, conversation_id: str
    ) -> ConversationData:
        """GET /conversations/{id} and map to :class:`ConversationData`."""
        path = _CONVERSATION_DETAIL_PATH.format(conversation_id=conversation_id)
        try:
            resp = await client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{conversation_id}' not found on Intercom"
                ) from exc
            raise

        return self._map_conversation_detail(resp.json())

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_conversation_detail(raw: dict[str, Any]) -> ConversationData:
        """Map a full Intercom conversation (with parts) to :class:`ConversationData`."""
        messages: list[MessageData] = []

        # The initial message from the source (typically the user).
        source = raw.get("source", {})
        if source:
            messages.append(
                MessageData(
                    role=_map_author_role(source.get("author", {})),
                    content=_extract_body(source),
                    timestamp=_epoch_to_dt(raw.get("created_at")),
                    metadata={"part_type": "source"},
                )
            )

        # Conversation parts (subsequent messages).
        parts = raw.get("conversation_parts", {}).get("conversation_parts", [])
        for part in parts:
            body = _extract_body(part)
            if not body:
                continue
            messages.append(
                MessageData(
                    role=_map_author_role(part.get("author", {})),
                    content=body,
                    timestamp=_epoch_to_dt(part.get("created_at")),
                    metadata={
                        "part_type": part.get("part_type", ""),
                        "part_id": part.get("id", ""),
                    },
                )
            )

        return ConversationData(
            external_id=str(raw.get("id", "")),
            messages=messages,
            metadata={
                "state": raw.get("state", ""),
                "tags": [t.get("name", "") for t in raw.get("tags", {}).get("tags", [])],
                "assignee": raw.get("assignee", {}),
                "statistics": raw.get("statistics", {}),
            },
            started_at=_epoch_to_dt(raw.get("created_at")),
            ended_at=_epoch_to_dt(raw.get("updated_at")),
        )

    @staticmethod
    def _map_conversation_summary(raw: dict[str, Any]) -> ConversationData:
        """Map a list-level Intercom conversation (no parts) to :class:`ConversationData`."""
        messages: list[MessageData] = []
        source = raw.get("source", {})
        if source:
            messages.append(
                MessageData(
                    role=_map_author_role(source.get("author", {})),
                    content=_extract_body(source),
                    timestamp=_epoch_to_dt(raw.get("created_at")),
                    metadata={"part_type": "source"},
                )
            )

        return ConversationData(
            external_id=str(raw.get("id", "")),
            messages=messages,
            metadata={"state": raw.get("state", "")},
            started_at=_epoch_to_dt(raw.get("created_at")),
            ended_at=_epoch_to_dt(raw.get("updated_at")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.access_token}",
            "Accept": "application/json",
            "Intercom-Version": _API_VERSION,
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_author_role(author: dict[str, Any]) -> str:
    """Normalise an Intercom author type to a standard role string."""
    author_type = str(author.get("type", "")).lower()
    mapping: dict[str, str] = {
        "user": "user",
        "lead": "user",
        "contact": "user",
        "admin": "assistant",
        "bot": "assistant",
        "team": "assistant",
    }
    return mapping.get(author_type, "user")


def _extract_body(part: dict[str, Any]) -> str:
    """Extract the text body from a conversation source or part.

    Intercom can return HTML in ``body``; we take plain-text when available.
    """
    return str(part.get("body", "") or "").strip()


def _epoch_to_dt(value: int | str | None) -> datetime | None:
    """Convert an epoch timestamp (seconds) to a timezone-aware datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
