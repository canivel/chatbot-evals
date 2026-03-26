"""Voiceflow AI Agent Builder platform connector.

Fetches transcript data from the Voiceflow Dialog Management API.  Voiceflow
is a platform for building AI agents and chatbots with visual workflows.
Transcripts are listed via ``GET /v2/transcripts/{projectID}`` and individual
transcripts (with turns) via
``GET /v2/transcripts/{projectID}/{transcriptID}``.

Reference: https://developer.voiceflow.com/reference
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

_BASE_URL = "https://api.voiceflow.com"
_TRANSCRIPTS_LIST_PATH = "/v2/transcripts/{project_id}"
_TRANSCRIPT_DETAIL_PATH = "/v2/transcripts/{project_id}/{transcript_id}"
_PROJECT_PATH = "/v2/projects/{project_id}"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class VoiceflowConfig(ConnectorConfig):
    """Configuration specific to the Voiceflow connector."""

    connector_type: str = "voiceflow"
    api_key: str = Field(
        ..., description="Voiceflow API key (VF.xxx format)"
    )
    project_id: str = Field(
        ..., description="Voiceflow project ID"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Number of transcripts per page",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class VoiceflowConnector(BaseConnector):
    """Connector that pulls transcripts from Voiceflow via the Transcripts API."""

    def __init__(self, config: VoiceflowConfig) -> None:
        super().__init__(config)
        self._config: VoiceflowConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Create an HTTP client and verify the API key."""
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
        """Fetch the project metadata to validate the API key and project ID."""
        client = self._ensure_client()
        path = _PROJECT_PATH.format(project_id=self._config.project_id)
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
        """Fetch transcripts from Voiceflow with page/limit pagination.

        Args:
            since: Only return transcripts created after this timestamp.
            limit: Maximum number of transcripts to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []
        page = 1
        page_size = min(self._config.page_size, limit)

        list_path = _TRANSCRIPTS_LIST_PATH.format(
            project_id=self._config.project_id
        )

        while len(conversations) < limit:
            params: dict[str, Any] = {
                "page": page,
                "limit": page_size,
            }

            try:
                resp = await client.get(list_path, params=params)
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

            items: list[dict[str, Any]] = resp.json()
            if not items:
                break

            for item in items:
                if len(conversations) >= limit:
                    break

                created = _parse_iso_dt(item.get("createdAt"))
                if since is not None and created is not None and created <= since:
                    continue

                try:
                    full = await self._fetch_transcript_detail(
                        client, str(item.get("_id", ""))
                    )
                    conversations.append(full)
                except Exception:
                    conversations.append(self._map_transcript_summary(item))

            # If we got fewer items than page_size, we've reached the end
            if len(items) < page_size:
                break

            page += 1

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single transcript by its Voiceflow transcript ID."""
        self._require_connected()
        client = self._ensure_client()
        return await self._fetch_transcript_detail(client, external_id)

    # -- internal fetchers ---------------------------------------------------

    async def _fetch_transcript_detail(
        self, client: httpx.AsyncClient, transcript_id: str
    ) -> ConversationData:
        """GET /v2/transcripts/{projectID}/{transcriptID} and map to :class:`ConversationData`."""
        path = _TRANSCRIPT_DETAIL_PATH.format(
            project_id=self._config.project_id,
            transcript_id=transcript_id,
        )
        try:
            resp = await client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Transcript '{transcript_id}' not found on Voiceflow"
                ) from exc
            raise

        return self._map_transcript_detail(transcript_id, resp.json())

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_transcript_detail(
        transcript_id: str, turns: list[dict[str, Any]] | dict[str, Any]
    ) -> ConversationData:
        """Map Voiceflow transcript turns to :class:`ConversationData`.

        The transcript detail endpoint returns a list of turn objects.
        """
        if isinstance(turns, dict):
            turns = turns.get("turns", turns.get("data", []))

        messages: list[MessageData] = []
        first_ts: datetime | None = None
        last_ts: datetime | None = None
        flow_names: list[str] = []
        intents: list[str] = []

        for turn in turns:
            turn_type = str(turn.get("type", "")).lower()
            timestamp = _parse_iso_dt(turn.get("startTime") or turn.get("createdAt"))

            if first_ts is None and timestamp is not None:
                first_ts = timestamp
            if timestamp is not None:
                last_ts = timestamp

            # Track flow / intent metadata
            if turn.get("flow"):
                flow_names.append(str(turn["flow"]))

            payload = turn.get("payload", {}) or {}
            if isinstance(payload, dict) and payload.get("intent"):
                intent_data = payload["intent"]
                if isinstance(intent_data, dict):
                    intents.append(intent_data.get("name", ""))
                else:
                    intents.append(str(intent_data))

            role = _map_turn_type_role(turn_type)
            content = _extract_turn_content(turn)
            if not content:
                continue

            nlu_confidence: float | None = None
            if isinstance(payload, dict) and payload.get("confidence") is not None:
                try:
                    nlu_confidence = float(payload["confidence"])
                except (ValueError, TypeError):
                    pass

            messages.append(
                MessageData(
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    metadata={
                        "turn_type": turn_type,
                        "turn_id": turn.get("turnID", turn.get("_id", "")),
                        "nlu_confidence": nlu_confidence,
                    },
                )
            )

        return ConversationData(
            external_id=transcript_id,
            messages=messages,
            metadata={
                "flow_names": list(dict.fromkeys(flow_names)),
                "intents": list(dict.fromkeys(intents)),
            },
            started_at=first_ts,
            ended_at=last_ts,
        )

    @staticmethod
    def _map_transcript_summary(raw: dict[str, Any]) -> ConversationData:
        """Map a list-level Voiceflow transcript to :class:`ConversationData`."""
        return ConversationData(
            external_id=str(raw.get("_id", "")),
            messages=[],
            metadata={
                "name": raw.get("name", ""),
                "browser": raw.get("browser", ""),
                "device": raw.get("device", ""),
            },
            started_at=_parse_iso_dt(raw.get("createdAt")),
            ended_at=_parse_iso_dt(raw.get("updatedAt")),
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": self._config.api_key,
            "Accept": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_turn_type_role(turn_type: str) -> str:
    """Normalise a Voiceflow turn type to a standard role string.

    Voiceflow transcript turns have a ``type`` field:
    - ``"request"`` -> ``"user"`` (user input)
    - ``"text"`` / ``"speak"`` / ``"visual"`` -> ``"assistant"`` (bot response)
    - ``"choice"`` / ``"buttons"`` -> ``"assistant"``
    """
    user_types = {"request"}
    assistant_types = {"text", "speak", "visual", "choice", "buttons", "card", "carousel"}

    if turn_type in user_types:
        return "user"
    if turn_type in assistant_types:
        return "assistant"
    # Default: treat unknown types as assistant (system-generated)
    return "assistant"


def _extract_turn_content(turn: dict[str, Any]) -> str:
    """Extract text content from a Voiceflow transcript turn.

    Different turn types store content in different places within the payload.
    """
    turn_type = str(turn.get("type", "")).lower()
    payload = turn.get("payload", {}) or {}

    if turn_type == "request":
        # User input: payload may contain the text directly or nested
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            # The query or input text
            query = payload.get("query", "") or payload.get("input", "") or ""
            return str(query).strip()
        return ""

    if turn_type in ("text", "speak"):
        # Bot text/speak responses
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            message = payload.get("message", "") or payload.get("text", "") or ""
            return str(message).strip()
        return ""

    if turn_type == "visual":
        if isinstance(payload, dict):
            return str(payload.get("title", "") or payload.get("text", "") or "").strip()
        return ""

    if turn_type in ("choice", "buttons"):
        if isinstance(payload, dict):
            return str(payload.get("message", "") or payload.get("text", "") or "").strip()
        return ""

    # Fallback: try common content fields
    if isinstance(payload, dict):
        for key in ("message", "text", "content", "body"):
            val = payload.get(key)
            if val:
                return str(val).strip()

    return ""


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
