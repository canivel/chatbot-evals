"""Amazon Connect / Amazon Lex connector.

Supports importing exported contact transcripts from Amazon Connect (JSON
files stored in S3 or on disk).  For live API access the connector can also
call the Amazon Connect Contact Lens ``ListRealtimeContactAnalysisSegments``
endpoint via ``httpx`` with AWS Signature Version 4 signing.

Because the AWS SDK (``boto3``) may not be available in every environment the
connector is purposely designed around two modes:

1. **File / S3-export mode** (default) -- reads pre-exported JSON transcript
   files from a local directory or an S3-compatible URL.
2. **API mode** -- calls the Contact Lens real-time analytics endpoint to
   retrieve transcript segments directly.  Requires valid AWS credentials.

Credential fields:
    ``aws_access_key_id``, ``aws_secret_access_key``, ``region_name``,
    ``instance_id``.

Role mapping:
    ``CUSTOMER`` -> ``"user"``, ``AGENT`` / ``BOT`` -> ``"assistant"``,
    ``SYSTEM`` -> ``"system"``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
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

_SERVICE = "connect"
_CONTACT_LENS_SERVICE = "connect"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class AmazonConnectConfig(ConnectorConfig):
    """Configuration specific to the Amazon Connect connector."""

    connector_type: str = "amazon_connect"
    aws_access_key_id: str = Field(
        default="", description="AWS access key ID"
    )
    aws_secret_access_key: str = Field(
        default="", description="AWS secret access key"
    )
    region_name: str = Field(
        default="us-east-1", description="AWS region name"
    )
    instance_id: str = Field(
        default="", description="Amazon Connect instance ID"
    )
    transcript_dir: str = Field(
        default="",
        description=(
            "Path to a directory containing exported transcript JSON files. "
            "When set the connector operates in file-import mode."
        ),
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class AmazonConnectConnector(BaseConnector):
    """Connector that imports Amazon Connect / Lex conversation transcripts."""

    def __init__(self, config: AmazonConnectConfig) -> None:
        super().__init__(config)
        self._config: AmazonConnectConfig = config
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Initialise the connector.

        In file-import mode the transcript directory is validated.  In API
        mode an HTTP client is created and a lightweight request is issued
        to confirm connectivity.
        """
        self.logger.info("connecting")

        if self._config.transcript_dir:
            # File-import mode -- just verify the directory exists.
            transcript_path = Path(self._config.transcript_dir)
            if transcript_path.is_dir():
                self.status = ConnectorStatus.CONNECTED
                self.logger.info("connected", mode="file_import")
                return True
            self.logger.error(
                "transcript_dir_missing", path=self._config.transcript_dir
            )
            self.status = ConnectorStatus.ERROR
            return False

        # API mode
        base_url = (
            f"https://connect.{self._config.region_name}.amazonaws.com"
        )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(self._config.timeout_seconds),
        )

        if await self.test_connection():
            self.status = ConnectorStatus.CONNECTED
            self.logger.info("connected", mode="api")
            return True

        self.status = ConnectorStatus.ERROR
        self.logger.error("connection_failed")
        return False

    async def disconnect(self) -> None:
        """Close the underlying HTTP client if one is open."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self.status = ConnectorStatus.DISCONNECTED
        self.logger.info("disconnected")

    async def test_connection(self) -> bool:
        """Verify connectivity.

        File-import mode checks the transcript directory; API mode issues a
        ``GET /instance/{instance_id}`` style request.
        """
        if self._config.transcript_dir:
            return Path(self._config.transcript_dir).is_dir()

        client = self._ensure_client()
        path = f"/connect/instances/{self._config.instance_id}"
        try:
            headers = self._sign_request("GET", path)
            resp = await client.get(path, headers=headers)
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
        """Fetch conversations from exported transcripts or the API.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()

        if self._config.transcript_dir:
            return self._load_transcripts_from_dir(since=since, limit=limit)

        return await self._fetch_from_api(since=since, limit=limit)

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its contact ID.

        In file-import mode ``external_id`` should match a JSON filename
        (without extension).
        """
        self._require_connected()

        if self._config.transcript_dir:
            transcript_path = Path(self._config.transcript_dir)
            for suffix in (".json",):
                candidate = transcript_path / f"{external_id}{suffix}"
                if candidate.is_file():
                    raw = json.loads(candidate.read_text(encoding="utf-8"))
                    return _map_transcript(raw, external_id)
            raise ValueError(
                f"Transcript file for contact '{external_id}' not found "
                f"in {self._config.transcript_dir}"
            )

        # API mode
        client = self._ensure_client()
        path = (
            f"/contact/contact-lens/{self._config.instance_id}"
            f"/contacts/{external_id}/analysis"
        )
        headers = self._sign_request("GET", path)
        try:
            resp = await client.get(path, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Contact '{external_id}' not found"
                ) from exc
            raise

        return _map_transcript(resp.json(), external_id)

    # -- file-import mode ----------------------------------------------------

    def _load_transcripts_from_dir(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Load transcript JSON files from the configured directory."""
        transcript_path = Path(self._config.transcript_dir)
        conversations: list[ConversationData] = []

        json_files = sorted(transcript_path.glob("*.json"))
        for fpath in json_files:
            if len(conversations) >= limit:
                break
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
                contact_id = fpath.stem
                conv = _map_transcript(raw, contact_id)

                if since is not None and conv.started_at is not None:
                    if conv.started_at <= since:
                        continue

                conversations.append(conv)
            except Exception as exc:
                self.logger.warning(
                    "transcript_parse_error", file=str(fpath), error=str(exc)
                )

        self.logger.info("load_transcripts_done", count=len(conversations))
        return conversations

    # -- API mode ------------------------------------------------------------

    async def _fetch_from_api(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch transcript data from the Contact Lens API."""
        client = self._ensure_client()

        # List recent contacts
        path = f"/contacts/{self._config.instance_id}"
        params: dict[str, Any] = {"maxResults": min(limit, 100)}
        if since is not None:
            params["startTime"] = since.isoformat()

        headers = self._sign_request("GET", path)
        try:
            resp = await client.get(path, headers=headers, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            self.logger.error("fetch_contacts_error", error=str(exc))
            raise

        body = resp.json()
        contacts: list[dict[str, Any]] = body.get("Contacts", body.get("contacts", []))

        conversations: list[ConversationData] = []
        for contact in contacts[:limit]:
            contact_id = str(
                contact.get("ContactId", contact.get("contactId", contact.get("Id", "")))
            )
            if not contact_id:
                continue
            try:
                conv = await self.fetch_conversation(contact_id)
                conversations.append(conv)
            except Exception as exc:
                self.logger.warning(
                    "fetch_contact_error", contact_id=contact_id, error=str(exc)
                )

        self.logger.info("fetch_from_api_done", count=len(conversations))
        return conversations

    # -- AWS SigV4 signing ---------------------------------------------------

    def _sign_request(
        self,
        method: str,
        path: str,
        payload: str = "",
    ) -> dict[str, str]:
        """Generate AWS Signature Version 4 headers for a request.

        This is a minimal SigV4 implementation sufficient for unauthenticated
        environments where ``boto3`` is unavailable.
        """
        now = datetime.now(tz=timezone.utc)
        datestamp = now.strftime("%Y%m%d")
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")

        region = self._config.region_name
        service = _SERVICE
        host = f"connect.{region}.amazonaws.com"

        canonical_uri = path
        canonical_querystring = ""
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        canonical_headers = (
            f"host:{host}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-date"

        canonical_request = (
            f"{method}\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )

        credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
            + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        )

        signing_key = _get_signature_key(
            self._config.aws_secret_access_key, datestamp, region, service
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        authorization = (
            f"AWS4-HMAC-SHA256 Credential="
            f"{self._config.aws_access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        return {
            "Authorization": authorization,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Host": host,
        }

    # -- internal helpers ----------------------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Transcript mapping
# ---------------------------------------------------------------------------


def _map_transcript(raw: dict[str, Any], contact_id: str) -> ConversationData:
    """Map an Amazon Connect transcript JSON to :class:`ConversationData`.

    Supports both Contact Lens analysis output and the simpler chat-transcript
    export format.
    """
    messages: list[MessageData] = []
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    # Contact Lens segments
    segments: list[dict[str, Any]] = (
        raw.get("Segments", [])
        or raw.get("segments", [])
        or raw.get("Transcript", [])
        or raw.get("transcript", [])
    )

    for segment in segments:
        transcript_seg = (
            segment.get("Transcript", segment)
            if isinstance(segment, dict)
            else segment
        )
        if not isinstance(transcript_seg, dict):
            continue

        content = str(
            transcript_seg.get("Content", "")
            or transcript_seg.get("content", "")
            or transcript_seg.get("Text", "")
            or transcript_seg.get("text", "")
        ).strip()
        if not content:
            continue

        participant = str(
            transcript_seg.get("ParticipantRole", "")
            or transcript_seg.get("participantRole", "")
            or transcript_seg.get("Participant", "")
            or transcript_seg.get("participant", "")
        )

        role = _map_participant_role(participant)
        timestamp = _parse_timestamp(
            transcript_seg.get("BeginOffsetMillis")
            or transcript_seg.get("Timestamp")
            or transcript_seg.get("timestamp")
        )

        metadata: dict[str, Any] = {}
        sentiment = (
            transcript_seg.get("Sentiment")
            or transcript_seg.get("sentiment")
        )
        if sentiment:
            metadata["sentiment"] = sentiment

        sentiment_score = (
            transcript_seg.get("SentimentScore")
            or transcript_seg.get("sentimentScore")
        )
        if sentiment_score:
            metadata["sentiment_score"] = sentiment_score

        messages.append(
            MessageData(
                role=role,
                content=content,
                timestamp=timestamp,
                metadata=metadata,
            )
        )

        if timestamp is not None:
            if first_ts is None or timestamp < first_ts:
                first_ts = timestamp
            if last_ts is None or timestamp > last_ts:
                last_ts = timestamp

    # Top-level metadata
    conv_metadata: dict[str, Any] = {}
    for key in ("Channel", "channel", "Queue", "queue", "InitiationMethod"):
        if key in raw:
            conv_metadata[key.lower()] = raw[key]

    overall_sentiment = raw.get("OverallSentiment") or raw.get("overallSentiment")
    if overall_sentiment:
        conv_metadata["overall_sentiment"] = overall_sentiment

    return ConversationData(
        external_id=contact_id,
        messages=messages,
        metadata=conv_metadata,
        started_at=first_ts,
        ended_at=last_ts,
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _map_participant_role(participant: str) -> str:
    """Normalise an Amazon Connect participant role to a standard role."""
    participant_upper = participant.upper()
    if participant_upper == "CUSTOMER":
        return "user"
    if participant_upper in ("AGENT", "BOT"):
        return "assistant"
    if participant_upper == "SYSTEM":
        return "system"
    return "user"


def _parse_timestamp(value: Any) -> datetime | None:
    """Best-effort conversion of various timestamp formats to datetime."""
    if value is None:
        return None
    # Millisecond offset
    if isinstance(value, (int, float)):
        try:
            if value > 1e12:
                return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None
    # ISO-8601 string
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
    return None


def _sign(key: bytes, msg: str) -> bytes:
    """HMAC-SHA256 helper for AWS SigV4."""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(
    secret: str, datestamp: str, region: str, service: str
) -> bytes:
    """Derive the AWS SigV4 signing key."""
    k_date = _sign(f"AWS4{secret}".encode("utf-8"), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")
