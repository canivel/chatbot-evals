"""Rasa Open Source connector.

Fetches conversation data from the Rasa tracker store REST API.  Individual
conversation trackers are retrieved via
``GET /conversations/{conversation_id}/tracker`` and parsed for ``user`` and
``bot`` events that become messages.

The Rasa HTTP API may be secured with a JWT token or a simple API key passed
as a query parameter.

Reference: https://rasa.com/docs/rasa/pages/http-api
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

_STATUS_PATH = "/status"
_CONVERSATIONS_PATH = "/conversations"
_TRACKER_PATH = "/conversations/{conversation_id}/tracker"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class RasaConfig(ConnectorConfig):
    """Configuration specific to the Rasa connector."""

    connector_type: str = "rasa"
    rasa_url: str = Field(
        ...,
        description="Base URL of the Rasa server (e.g. http://localhost:5005)",
    )
    token: str = Field(
        default="",
        description="Optional authentication token (JWT or API key)",
    )
    conversation_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit list of conversation IDs to fetch. "
            "When empty the connector will attempt to list via GET /conversations."
        ),
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class RasaConnector(BaseConnector):
    """Connector that pulls conversation trackers from a Rasa server."""

    def __init__(self, config: RasaConfig) -> None:
        super().__init__(config)
        self._config: RasaConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify the Rasa server is reachable."""
        self.logger.info("connecting")
        base_url = self._config.rasa_url.rstrip("/")
        headers = self._build_headers()

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
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
        """Call ``GET /status`` to verify the Rasa server is running."""
        client = self._ensure_client()
        try:
            resp = await client.get(_STATUS_PATH, params=self._auth_params())
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
        """Fetch conversations from the Rasa tracker store.

        If explicit ``conversation_ids`` are configured they are used directly;
        otherwise the connector tries ``GET /conversations`` to discover IDs.

        Args:
            since: Only return conversations with events after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        ids = list(self._config.conversation_ids)

        # Try listing conversations from the API when no explicit IDs given.
        if not ids:
            ids = await self._list_conversation_ids(client)

        conversations: list[ConversationData] = []
        for cid in ids[:limit]:
            try:
                conv = await self._fetch_tracker(client, cid, since=since)
                if conv is not None:
                    conversations.append(conv)
            except Exception as exc:
                self.logger.warning(
                    "fetch_tracker_error", conversation_id=cid, error=str(exc)
                )

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its sender ID / conversation ID."""
        self._require_connected()
        client = self._ensure_client()
        conv = await self._fetch_tracker(client, external_id)
        if conv is None:
            raise ValueError(
                f"Conversation '{external_id}' not found or contains no events"
            )
        return conv

    # -- internal fetchers ---------------------------------------------------

    async def _list_conversation_ids(
        self, client: httpx.AsyncClient
    ) -> list[str]:
        """Attempt to list conversation IDs via ``GET /conversations``."""
        try:
            resp = await client.get(_CONVERSATIONS_PATH, params=self._auth_params())
            resp.raise_for_status()
            data = resp.json()
            # The response is a list of sender IDs (strings).
            if isinstance(data, list):
                return [str(cid) for cid in data]
            return []
        except (httpx.HTTPError, Exception) as exc:
            self.logger.warning(
                "list_conversations_unavailable",
                error=str(exc),
            )
            return []

    async def _fetch_tracker(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
        since: datetime | None = None,
    ) -> ConversationData | None:
        """GET a tracker and map its events to :class:`ConversationData`."""
        path = _TRACKER_PATH.format(conversation_id=conversation_id)
        params = self._auth_params()
        params["include_events"] = "AFTER_RESTART"

        try:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{conversation_id}' not found on Rasa"
                ) from exc
            raise

        tracker: dict[str, Any] = resp.json()
        events: list[dict[str, Any]] = tracker.get("events", [])

        messages: list[MessageData] = []
        first_ts: datetime | None = None
        last_ts: datetime | None = None

        for event in events:
            event_type = event.get("event", "")
            timestamp = _epoch_to_dt(event.get("timestamp"))

            if since is not None and timestamp is not None and timestamp <= since:
                continue

            if event_type == "user":
                text = str(event.get("text", "") or "").strip()
                if not text:
                    continue
                parse_data = event.get("parse_data", {})
                messages.append(
                    MessageData(
                        role="user",
                        content=text,
                        timestamp=timestamp,
                        metadata={
                            "intent": parse_data.get("intent", {}).get("name", ""),
                            "intent_confidence": parse_data.get("intent", {}).get(
                                "confidence"
                            ),
                            "entities": parse_data.get("entities", []),
                        },
                    )
                )
            elif event_type == "bot":
                text = str(event.get("text", "") or "").strip()
                if not text:
                    continue
                metadata: dict[str, Any] = {}
                if event.get("data"):
                    metadata["action"] = event["data"].get("action", "")
                    metadata["buttons"] = event["data"].get("buttons", [])
                messages.append(
                    MessageData(
                        role="assistant",
                        content=text,
                        timestamp=timestamp,
                        metadata=metadata,
                    )
                )
            else:
                # Skip non-message events (action, slot, restart, etc.)
                continue

            if timestamp is not None:
                if first_ts is None or timestamp < first_ts:
                    first_ts = timestamp
                if last_ts is None or timestamp > last_ts:
                    last_ts = timestamp

        if not messages:
            return None

        slots = tracker.get("slots", {})
        active_loop = tracker.get("active_loop", {})

        return ConversationData(
            external_id=str(tracker.get("sender_id", conversation_id)),
            messages=messages,
            metadata={
                "slots": slots,
                "active_loop": active_loop,
                "latest_action_name": tracker.get("latest_action_name", ""),
            },
            started_at=first_ts,
            ended_at=last_ts,
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers; attach JWT bearer token if configured."""
        headers: dict[str, str] = {"Accept": "application/json"}
        token = self._config.token
        if token and token.startswith("ey"):
            # Looks like a JWT
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _auth_params(self) -> dict[str, str]:
        """Return query params for authentication.

        Rasa supports a ``token`` query parameter for simple API-key auth.
        """
        token = self._config.token
        if token and not token.startswith("ey"):
            return {"token": token}
        return {}

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _epoch_to_dt(value: float | int | str | None) -> datetime | None:
    """Convert an epoch timestamp (seconds) to a timezone-aware datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None
