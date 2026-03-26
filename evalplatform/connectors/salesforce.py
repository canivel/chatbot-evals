"""Salesforce Service Cloud / Einstein Bot connector.

Fetches chat transcript data from the Salesforce REST API.  Live chat
transcripts are retrieved via SOQL queries against the ``LiveChatTranscript``
and ``LiveChatTranscriptEvent`` objects.

Reference: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/
"""

from __future__ import annotations

import re
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

_API_VERSION = "v59.0"
_QUERY_PATH = f"/services/data/{_API_VERSION}/query/"
_LIMITS_PATH = f"/services/data/{_API_VERSION}/limits/"

_TRANSCRIPTS_SOQL = (
    "SELECT Id, Body, CreatedDate, EndTime, StartTime, Status, OwnerId, CaseId, LiveChatButtonId "
    "FROM LiveChatTranscript"
)
_TRANSCRIPT_EVENTS_SOQL = (
    "SELECT Id, LiveChatTranscriptId, Type, Detail, CreatedDate, AgentId "
    "FROM LiveChatTranscriptEvent "
    "WHERE LiveChatTranscriptId = '{transcript_id}' "
    "ORDER BY CreatedDate ASC"
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class SalesforceConfig(ConnectorConfig):
    """Configuration specific to the Salesforce connector."""

    connector_type: str = "salesforce"
    access_token: str = Field(
        ..., description="Salesforce OAuth access token"
    )
    instance_url: str = Field(
        ...,
        description="Salesforce instance URL (e.g. https://yourorg.my.salesforce.com)",
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Number of records per SOQL query page (max 2000)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class SalesforceConnector(BaseConnector):
    """Connector that pulls chat transcripts from Salesforce via the REST API.

    Salesforce Live Chat transcripts are queried using SOQL.  The transcript
    ``Body`` field (which contains the full chat as HTML/text) is parsed into
    individual messages.  When the body is not available or too coarse,
    ``LiveChatTranscriptEvent`` records are fetched for finer-grained messages.

    Reference: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/
    """

    def __init__(self, config: SalesforceConfig) -> None:
        super().__init__(config)
        self._config: SalesforceConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify the access token."""
        self.logger.info("connecting")
        # Strip trailing slashes from instance URL
        base_url = self._config.instance_url.rstrip("/")
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
        """Call ``GET /services/data/{version}/limits/`` to validate the token."""
        client = self._ensure_client()
        try:
            resp = await client.get(_LIMITS_PATH)
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
        """Fetch chat transcripts from Salesforce with SOQL pagination.

        Args:
            since: Only return transcripts created after this timestamp.
            limit: Maximum number of transcripts to return.
        """
        self._require_connected()
        client = self._ensure_client()

        soql = _TRANSCRIPTS_SOQL
        conditions: list[str] = []
        if since is not None:
            conditions.append(
                f"CreatedDate > {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            )
        if conditions:
            soql += " WHERE " + " AND ".join(conditions)
        soql += " ORDER BY CreatedDate DESC"
        soql += f" LIMIT {limit}"

        conversations: list[ConversationData] = []
        next_url: str | None = None

        # First request
        try:
            resp = await client.get(_QUERY_PATH, params={"q": soql})
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                "fetch_transcripts_http_error",
                status_code=exc.response.status_code,
                detail=exc.response.text[:500],
            )
            raise
        except httpx.HTTPError as exc:
            self.logger.error("fetch_transcripts_error", error=str(exc))
            raise

        data = resp.json()
        records: list[dict[str, Any]] = data.get("records", [])
        for record in records:
            if len(conversations) >= limit:
                break
            conv = await self._map_transcript(client, record)
            conversations.append(conv)

        next_url = data.get("nextRecordsUrl")

        # Handle SOQL pagination with nextRecordsUrl
        while next_url and len(conversations) < limit:
            try:
                resp = await client.get(next_url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_transcripts_pagination_error",
                    status_code=exc.response.status_code,
                )
                break
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_transcripts_pagination_transport_error",
                    error=str(exc),
                )
                break

            data = resp.json()
            records = data.get("records", [])
            for record in records:
                if len(conversations) >= limit:
                    break
                conv = await self._map_transcript(client, record)
                conversations.append(conv)

            next_url = data.get("nextRecordsUrl")

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single chat transcript by its Salesforce ID."""
        self._require_connected()
        client = self._ensure_client()

        soql = f"{_TRANSCRIPTS_SOQL} WHERE Id = '{external_id}'"
        try:
            resp = await client.get(_QUERY_PATH, params={"q": soql})
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Transcript '{external_id}' not found on Salesforce"
                ) from exc
            raise

        data = resp.json()
        records: list[dict[str, Any]] = data.get("records", [])
        if not records:
            raise ValueError(f"Transcript '{external_id}' not found on Salesforce")

        return await self._map_transcript(client, records[0])

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_transcript_events(
        self, client: httpx.AsyncClient, transcript_id: str
    ) -> list[dict[str, Any]]:
        """Fetch LiveChatTranscriptEvent records for a transcript."""
        soql = _TRANSCRIPT_EVENTS_SOQL.format(transcript_id=transcript_id)
        all_events: list[dict[str, Any]] = []
        next_url: str | None = None

        try:
            resp = await client.get(_QUERY_PATH, params={"q": soql})
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            return all_events
        except httpx.HTTPError:
            return all_events

        data = resp.json()
        all_events.extend(data.get("records", []))
        next_url = data.get("nextRecordsUrl")

        while next_url:
            try:
                resp = await client.get(next_url)
                resp.raise_for_status()
            except (httpx.HTTPStatusError, httpx.HTTPError):
                break
            data = resp.json()
            all_events.extend(data.get("records", []))
            next_url = data.get("nextRecordsUrl")

        return all_events

    # -- mapping helpers -----------------------------------------------------

    async def _map_transcript(
        self, client: httpx.AsyncClient, record: dict[str, Any]
    ) -> ConversationData:
        """Map a Salesforce LiveChatTranscript record to :class:`ConversationData`."""
        transcript_id = str(record.get("Id", ""))
        body = record.get("Body") or ""
        owner_id = record.get("OwnerId", "")

        # Try to parse the body into messages first.
        messages = _parse_transcript_body(body, owner_id)

        # If body parsing yielded no messages, fall back to transcript events.
        if not messages:
            events = await self._fetch_transcript_events(client, transcript_id)
            messages = _map_transcript_events(events)

        return ConversationData(
            external_id=transcript_id,
            messages=messages,
            metadata={
                "status": record.get("Status", ""),
                "case_id": record.get("CaseId", ""),
                "owner_id": owner_id,
                "button_id": record.get("LiveChatButtonId", ""),
            },
            started_at=_parse_sf_dt(record.get("StartTime") or record.get("CreatedDate")),
            ended_at=_parse_sf_dt(record.get("EndTime")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _parse_transcript_body(body: str, owner_id: str) -> list[MessageData]:
    """Parse the transcript Body field into individual messages.

    Salesforce stores the chat as semi-structured text/HTML.  Common formats:

    - ``Agent Name (HH:MM:SS): message text``
    - ``Visitor (HH:MM:SS): message text``
    - ``<p>Agent Name: message</p>`` (HTML variant)

    We apply heuristics to distinguish visitor (user) from agent (assistant).
    """
    if not body or not body.strip():
        return []

    messages: list[MessageData] = []

    # Strip HTML tags for a plain-text representation.
    clean = re.sub(r"<[^>]+>", "\n", body)
    clean = re.sub(r"\n{2,}", "\n", clean).strip()

    # Try to split on the common "Name (timestamp): message" pattern.
    line_pattern = re.compile(
        r"^(?P<sender>[^(]+?)\s*\((?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)\)\s*:\s*(?P<text>.+)$",
        re.MULTILINE,
    )

    matches = list(line_pattern.finditer(clean))
    if matches:
        for match in matches:
            sender = match.group("sender").strip()
            text = match.group("text").strip()
            if not text:
                continue
            role = _classify_sender(sender)
            messages.append(
                MessageData(
                    role=role,
                    content=text,
                    timestamp=None,
                    metadata={"sender_name": sender},
                )
            )
    else:
        # If we can't parse individual messages, treat the whole body as a
        # single system-level transcript.
        messages.append(
            MessageData(
                role="system",
                content=clean,
                timestamp=None,
                metadata={"raw_body": True},
            )
        )

    return messages


def _classify_sender(sender: str) -> str:
    """Classify a sender name as user or assistant."""
    lower = sender.lower().strip()
    visitor_keywords = {"visitor", "customer", "client", "guest", "end user", "chat visitor"}
    for keyword in visitor_keywords:
        if keyword in lower:
            return "user"
    # If not clearly a visitor, assume agent/bot.
    return "assistant"


def _map_transcript_events(events: list[dict[str, Any]]) -> list[MessageData]:
    """Map LiveChatTranscriptEvent records to messages."""
    messages: list[MessageData] = []
    for event in events:
        event_type = str(event.get("Type", "")).lower()
        detail = str(event.get("Detail", "") or "").strip()
        if not detail:
            continue

        # ChatMessage events contain actual conversation text.
        if event_type in ("chatmessage", "chat message", "chatrequest"):
            agent_id = event.get("AgentId")
            # If AgentId is set, this is an agent message; otherwise visitor.
            role = "assistant" if agent_id else "user"
            messages.append(
                MessageData(
                    role=role,
                    content=detail,
                    timestamp=_parse_sf_dt(event.get("CreatedDate")),
                    metadata={
                        "event_id": event.get("Id", ""),
                        "event_type": event_type,
                        "agent_id": agent_id or "",
                    },
                )
            )

    return messages


def _parse_sf_dt(value: str | None) -> datetime | None:
    """Parse a Salesforce ISO-8601 datetime string into a timezone-aware datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
