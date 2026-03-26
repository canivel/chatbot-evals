"""Cognigy.AI Enterprise Conversational AI platform connector.

Fetches conversation data from the Cognigy OData/REST API for analytics.
Cognigy is an enterprise conversational AI platform.  Conversations and their
messages are retrieved via the OData feed at
``GET /odata/v1/Conversations`` with ``$skip`` / ``$top`` pagination.

Reference: https://docs.cognigy.com/reference/analytics-odata
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

_CONVERSATIONS_PATH = "/odata/v1/Conversations"
_DEFAULT_PAGE_SIZE = 50

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class CognigyConfig(ConnectorConfig):
    """Configuration specific to the Cognigy connector."""

    connector_type: str = "cognigy"
    api_key: str = Field(..., description="Cognigy OData API key")
    base_url: str = Field(
        ...,
        description="Base URL of the Cognigy OData endpoint (e.g. https://odata-trial.cognigy.ai)",
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=_DEFAULT_PAGE_SIZE,
        ge=1,
        le=500,
        description="Number of conversations per OData page ($top)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class CognigyConnector(BaseConnector):
    """Connector that pulls conversations from Cognigy via the OData Analytics API."""

    def __init__(self, config: CognigyConfig) -> None:
        super().__init__(config)
        self._config: CognigyConfig = config
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
        """Fetch a single record from the OData feed to validate the API key."""
        client = self._ensure_client()
        try:
            resp = await client.get(
                _CONVERSATIONS_PATH,
                params={"$top": 1, "$select": "sessionId"},
            )
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
        """Fetch conversations from Cognigy with OData $skip/$top pagination.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        skip = 0
        top = min(self._config.page_size, limit)

        while len(conversations) < limit:
            params: dict[str, Any] = {
                "$top": top,
                "$skip": skip,
                "$orderby": "timestamp desc",
            }

            if since is not None:
                # OData datetime filter
                params["$filter"] = (
                    f"timestamp gt {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                )

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
            items: list[dict[str, Any]] = data.get("value", [])

            if not items:
                break

            # Group OData records by sessionId (each record is an
            # input/output pair within a session).
            session_groups: dict[str, list[dict[str, Any]]] = {}
            for record in items:
                session_id = str(record.get("sessionId", ""))
                if session_id:
                    session_groups.setdefault(session_id, []).append(record)

            for session_id, records in session_groups.items():
                if len(conversations) >= limit:
                    break
                conversations.append(
                    self._map_session_to_conversation(session_id, records)
                )

            # If we got fewer items than $top, no more pages
            if len(items) < top:
                break

            skip += top

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation (session) by its Cognigy session ID.

        Args:
            external_id: The Cognigy sessionId.

        Raises:
            ValueError: If the session cannot be found.
        """
        self._require_connected()
        client = self._ensure_client()

        params: dict[str, Any] = {
            "$filter": f"sessionId eq '{external_id}'",
            "$orderby": "timestamp asc",
        }

        try:
            resp = await client.get(_CONVERSATIONS_PATH, params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Session '{external_id}' not found on Cognigy"
                ) from exc
            raise

        data = resp.json()
        records: list[dict[str, Any]] = data.get("value", [])

        if not records:
            raise ValueError(f"Session '{external_id}' not found on Cognigy")

        return self._map_session_to_conversation(external_id, records)

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_session_to_conversation(
        session_id: str, records: list[dict[str, Any]]
    ) -> ConversationData:
        """Map a set of Cognigy OData records (one session) to :class:`ConversationData`.

        Each OData record typically contains an ``inputText`` (user message)
        and an ``outputText`` (assistant response) along with metadata like
        intent, flow, score, and channel.
        """
        messages: list[MessageData] = []
        first_ts: datetime | None = None
        last_ts: datetime | None = None
        intents: list[str] = []
        flows: list[str] = []
        channels: list[str] = []

        # Sort records by timestamp
        sorted_records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
        )

        for record in sorted_records:
            timestamp = _parse_iso_dt(record.get("timestamp"))
            if first_ts is None and timestamp is not None:
                first_ts = timestamp
            if timestamp is not None:
                last_ts = timestamp

            intent = record.get("intent", "") or record.get("intentName", "")
            if intent:
                intents.append(str(intent))

            flow = record.get("flow", "") or record.get("flowName", "")
            if flow:
                flows.append(str(flow))

            channel = record.get("channel", "")
            if channel:
                channels.append(str(channel))

            score = record.get("score") or record.get("intentScore")

            # User input
            input_text = str(record.get("inputText", "") or "").strip()
            if input_text:
                messages.append(
                    MessageData(
                        role="user",
                        content=input_text,
                        timestamp=timestamp,
                        metadata={
                            "intent": str(intent) if intent else "",
                            "score": score,
                            "input_id": record.get("inputId", ""),
                        },
                    )
                )

            # Assistant output
            output_text = str(record.get("outputText", "") or "").strip()
            if output_text:
                messages.append(
                    MessageData(
                        role="assistant",
                        content=output_text,
                        timestamp=timestamp,
                        metadata={
                            "flow": str(flow) if flow else "",
                            "output_id": record.get("outputId", ""),
                        },
                    )
                )

        return ConversationData(
            external_id=session_id,
            messages=messages,
            metadata={
                "intents": list(dict.fromkeys(intents)),
                "flows": list(dict.fromkeys(flows)),
                "channels": list(dict.fromkeys(channels)),
                "session_id": session_id,
            },
            started_at=first_ts,
            ended_at=last_ts,
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
