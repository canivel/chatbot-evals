"""Google Dialogflow CX / ES platform connector.

Fetches conversation (session) data from Dialogflow agents via the REST API.
Supports both:

1. **Live API** -- Querying conversation history from Dialogflow CX
   ``projects/{project}/locations/{location}/agents/{agent}/conversations``.
2. **Imported logs** -- Reading exported interaction logs from JSON or CSV
   files for offline evaluation.

User query inputs are mapped to ``"user"`` and fulfillment responses are
mapped to ``"assistant"``.  Intent metadata (name, confidence) is attached to
each assistant message.

Reference: https://cloud.google.com/dialogflow/cx/docs/reference/rest
"""

from __future__ import annotations

import csv
import io
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

_DIALOGFLOW_BASE_URL = "https://dialogflow.googleapis.com"

# CX API version
_CX_API_VERSION = "v3"

# ES API version
_ES_API_VERSION = "v2"

# Google OAuth token endpoint
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class DialogflowConfig(ConnectorConfig):
    """Configuration specific to the Dialogflow connector."""

    connector_type: str = "dialogflow"
    project_id: str = Field(..., description="Google Cloud project ID")
    location: str = Field(
        default="us-central1",
        description="Dialogflow agent location (e.g. 'us-central1', 'global')",
    )
    agent_id: str = Field(
        default="", description="Dialogflow CX agent ID (leave empty for ES)"
    )
    credentials_json: str | dict[str, Any] = Field(
        ...,
        description=(
            "Google service account credentials -- either a file path to "
            "a JSON key file or an inline dict of the key contents"
        ),
    )
    api_variant: str = Field(
        default="cx",
        description="Dialogflow variant: 'cx' for CX or 'es' for ES",
    )
    import_path: str = Field(
        default="",
        description=(
            "Optional path to a JSON or CSV file of exported interaction "
            "logs.  When set, logs are read from this file instead of the "
            "live API."
        ),
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of conversations per page",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class DialogflowConnector(BaseConnector):
    """Connector that pulls conversation data from Google Dialogflow CX/ES."""

    def __init__(self, config: DialogflowConfig) -> None:
        super().__init__(config)
        self._config: DialogflowConfig = config
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Acquire a Google OAuth token and create an HTTP client."""
        self.logger.info("connecting")

        # For import-only mode, skip token acquisition
        if self._config.import_path:
            self.status = ConnectorStatus.CONNECTED
            self.logger.info("connected", mode="import")
            return True

        token = await self._acquire_token()
        if not token:
            self.status = ConnectorStatus.ERROR
            self.logger.error("connection_failed", reason="token_acquisition_failed")
            return False

        self._access_token = token
        self._client = httpx.AsyncClient(
            base_url=_DIALOGFLOW_BASE_URL,
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
        self._access_token = None
        self.status = ConnectorStatus.DISCONNECTED
        self.logger.info("disconnected")

    async def test_connection(self) -> bool:
        """Validate credentials by listing agents or checking the project.

        For CX, call ``GET /v3/projects/{project}/locations/{location}/agents/{agent}``.
        For ES, call ``GET /v2/projects/{project}/agent``.
        """
        # Import-only mode does not need an API check
        if self._config.import_path:
            return Path(self._config.import_path).exists()

        client = self._ensure_client()
        try:
            path = self._agent_path()
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
        """Fetch conversations from Dialogflow or from an imported log file.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()

        # If an import path is configured, read from file instead of API
        if self._config.import_path:
            return self._import_from_file(since=since, limit=limit)

        client = self._ensure_client()
        return await self._fetch_from_api(client, since=since, limit=limit)

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its session / conversation ID.

        Args:
            external_id: The Dialogflow session or conversation ID.

        Raises:
            ValueError: If the conversation cannot be found.
        """
        self._require_connected()

        # Import mode: scan the file for the matching ID
        if self._config.import_path:
            all_convos = self._import_from_file()
            for convo in all_convos:
                if convo.external_id == external_id:
                    return convo
            raise ValueError(
                f"Conversation '{external_id}' not found in import file "
                f"'{self._config.import_path}'"
            )

        client = self._ensure_client()

        if self._config.api_variant == "cx":
            path = (
                f"/{_CX_API_VERSION}/projects/{self._config.project_id}"
                f"/locations/{self._config.location}"
                f"/agents/{self._config.agent_id}"
                f"/conversations/{external_id}"
            )
        else:
            path = (
                f"/{_ES_API_VERSION}/projects/{self._config.project_id}"
                f"/agent/sessions/{external_id}"
            )

        try:
            resp = await client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Conversation '{external_id}' not found on Dialogflow"
                ) from exc
            raise

        return self._map_conversation(resp.json())

    # -- live API fetching ---------------------------------------------------

    async def _fetch_from_api(
        self,
        client: httpx.AsyncClient,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch conversation history from the Dialogflow REST API."""
        conversations: list[ConversationData] = []

        if self._config.api_variant == "cx":
            base_path = (
                f"/{_CX_API_VERSION}/projects/{self._config.project_id}"
                f"/locations/{self._config.location}"
                f"/agents/{self._config.agent_id}"
                f"/conversations"
            )
        else:
            # ES does not have a native conversation-list endpoint; the
            # recommended approach is BigQuery export.  We attempt the
            # sessions listing as a best-effort.
            base_path = (
                f"/{_ES_API_VERSION}/projects/{self._config.project_id}"
                f"/agent/sessions"
            )

        page_token: str | None = None

        while len(conversations) < limit:
            params: dict[str, Any] = {"pageSize": min(self._config.page_size, limit)}
            if page_token:
                params["pageToken"] = page_token
            if since is not None:
                params["filter"] = (
                    f'createTime > "{since.strftime("%Y-%m-%dT%H:%M:%SZ")}"'
                )

            try:
                resp = await client.get(base_path, params=params)
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
            items: list[dict[str, Any]] = data.get("conversations", data.get("sessions", []))

            for item in items:
                if len(conversations) >= limit:
                    break
                conversations.append(self._map_conversation(item))

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations

    # -- file import ---------------------------------------------------------

    def _import_from_file(
        self,
        *,
        since: datetime | None = None,
        limit: int = 0,
    ) -> list[ConversationData]:
        """Read Dialogflow interaction logs from an exported JSON or CSV file.

        Supported formats:

        - **JSON / JSONL** -- Each record (or line) is a dict containing at
          minimum ``session_id``, ``query_text``, ``fulfillment_text``.
          Optional: ``intent_name``, ``intent_confidence``, ``timestamp``.
        - **CSV** -- Same fields as column headers.
        """
        file_path = Path(self._config.import_path)
        if not file_path.exists():
            raise FileNotFoundError(
                f"Import file not found: {self._config.import_path}"
            )

        suffix = file_path.suffix.lower()
        if suffix in (".json", ".jsonl"):
            records = self._read_json_records(file_path)
        elif suffix == ".csv":
            records = self._read_csv_records(file_path)
        else:
            raise ValueError(
                f"Unsupported import file format '{suffix}'. "
                "Expected .json, .jsonl, or .csv"
            )

        # Group records by session_id
        sessions: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            sid = record.get("session_id", record.get("sessionId", "unknown"))
            sessions.setdefault(str(sid), []).append(record)

        conversations: list[ConversationData] = []
        for session_id, session_records in sessions.items():
            convo = self._map_import_session(session_id, session_records)

            if since and convo.started_at and convo.started_at < since:
                continue

            conversations.append(convo)
            if limit and len(conversations) >= limit:
                break

        self.logger.info(
            "import_from_file_done",
            file=str(file_path),
            count=len(conversations),
        )
        return conversations

    @staticmethod
    def _read_json_records(file_path: Path) -> list[dict[str, Any]]:
        """Read records from a JSON or JSONL file."""
        content = file_path.read_text(encoding="utf-8")
        # Try parsing as a JSON array first
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

        # Fall back to JSONL (one JSON object per line)
        records: list[dict[str, Any]] = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
            except json.JSONDecodeError:
                continue
        return records

    @staticmethod
    def _read_csv_records(file_path: Path) -> list[dict[str, Any]]:
        """Read records from a CSV file with headers."""
        content = file_path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(content))
        return [dict(row) for row in reader]

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_conversation(raw: dict[str, Any]) -> ConversationData:
        """Map a Dialogflow conversation / session response to :class:`ConversationData`.

        The structure differs between CX and ES, but we normalise both into
        a user-query / assistant-response message pair sequence.
        """
        messages: list[MessageData] = []
        external_id = raw.get("name", raw.get("sessionId", ""))

        # CX conversations have an ``interactions`` list
        interactions = raw.get("interactions", [])
        for interaction in interactions:
            request = interaction.get("request", {})
            response = interaction.get("response", {})

            # User query
            query_input = request.get("queryInput", {})
            user_text = (
                query_input.get("text", {}).get("text", "")
                or query_input.get("intent", {}).get("intent", "")
                or query_input.get("event", {}).get("event", "")
            )
            if user_text:
                messages.append(
                    MessageData(
                        role="user",
                        content=user_text.strip(),
                        timestamp=_parse_google_timestamp(
                            interaction.get("createTime")
                        ),
                        metadata={},
                    )
                )

            # Assistant response
            query_result = response.get("queryResult", {})
            fulfillment = _extract_fulfillment_text(query_result)
            if fulfillment:
                intent_info = query_result.get("intent", {})
                messages.append(
                    MessageData(
                        role="assistant",
                        content=fulfillment,
                        timestamp=_parse_google_timestamp(
                            interaction.get("createTime")
                        ),
                        metadata={
                            "intent_name": intent_info.get(
                                "displayName", ""
                            ),
                            "intent_confidence": query_result.get(
                                "intentDetectionConfidence", 0.0
                            ),
                        },
                    )
                )

        # If no interactions found, try ES-style flat structure
        if not interactions and raw.get("queryResult"):
            qr = raw["queryResult"]
            user_text = raw.get("queryText", qr.get("queryText", ""))
            if user_text:
                messages.append(
                    MessageData(
                        role="user",
                        content=str(user_text).strip(),
                        timestamp=_parse_google_timestamp(raw.get("createTime")),
                        metadata={},
                    )
                )
            fulfillment = _extract_fulfillment_text(qr)
            if fulfillment:
                messages.append(
                    MessageData(
                        role="assistant",
                        content=fulfillment,
                        timestamp=_parse_google_timestamp(raw.get("createTime")),
                        metadata={
                            "intent_name": qr.get("intent", {}).get(
                                "displayName", ""
                            ),
                            "intent_confidence": qr.get(
                                "intentDetectionConfidence", 0.0
                            ),
                        },
                    )
                )

        started_at = _parse_google_timestamp(raw.get("createTime"))
        ended_at = _parse_google_timestamp(
            raw.get("endTime", raw.get("createTime"))
        )

        return ConversationData(
            external_id=external_id,
            messages=messages,
            metadata={
                "agent": raw.get("agent", ""),
                "flow": raw.get("flow", ""),
            },
            started_at=started_at,
            ended_at=ended_at,
        )

    @staticmethod
    def _map_import_session(
        session_id: str,
        records: list[dict[str, Any]],
    ) -> ConversationData:
        """Map a group of imported log records into a single conversation."""
        messages: list[MessageData] = []

        # Sort records by timestamp if available
        records.sort(key=lambda r: r.get("timestamp", ""))

        for record in records:
            ts = _parse_google_timestamp(record.get("timestamp"))

            # User query
            query_text = record.get("query_text", record.get("queryText", ""))
            if query_text:
                messages.append(
                    MessageData(
                        role="user",
                        content=str(query_text).strip(),
                        timestamp=ts,
                        metadata={},
                    )
                )

            # Assistant response
            fulfillment_text = record.get(
                "fulfillment_text", record.get("fulfillmentText", "")
            )
            if fulfillment_text:
                intent_name = record.get(
                    "intent_name", record.get("intentName", "")
                )
                intent_confidence = record.get(
                    "intent_confidence",
                    record.get("intentConfidence", 0.0),
                )
                try:
                    confidence_val = float(intent_confidence)
                except (ValueError, TypeError):
                    confidence_val = 0.0

                messages.append(
                    MessageData(
                        role="assistant",
                        content=str(fulfillment_text).strip(),
                        timestamp=ts,
                        metadata={
                            "intent_name": str(intent_name),
                            "intent_confidence": confidence_val,
                        },
                    )
                )

        started_at = messages[0].timestamp if messages else None
        ended_at = messages[-1].timestamp if messages else None

        return ConversationData(
            external_id=session_id,
            messages=messages,
            metadata={"source": "import"},
            started_at=started_at,
            ended_at=ended_at,
        )

    # -- token acquisition ---------------------------------------------------

    async def _acquire_token(self) -> str | None:
        """Acquire a Google OAuth 2.0 access token using service account credentials.

        Uses the JWT-based service-account flow to request an access token
        from Google's OAuth endpoint.
        """
        creds = self._load_credentials()
        if creds is None:
            return None

        # Build a JWT for the token request
        import time as _time
        import hashlib
        import hmac
        import base64

        now = int(_time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": creds.get("client_email", ""),
            "scope": "https://www.googleapis.com/auth/dialogflow",
            "aud": _GOOGLE_TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }

        # For simplicity in this connector, we attempt to use the token
        # endpoint directly with an assertion.  In production, a library
        # like google-auth would handle the full JWT signing with RSA.
        # Here we submit the credentials for a direct exchange.
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._config.timeout_seconds)
            ) as token_client:
                # Use the OAuth2 token endpoint with a JWT assertion
                # This requires the private_key from the service account JSON.
                jwt_assertion = _build_jwt_assertion(creds)
                if not jwt_assertion:
                    self.logger.error(
                        "jwt_build_failed",
                        reason="Could not build JWT from credentials",
                    )
                    return None

                resp = await token_client.post(
                    _GOOGLE_TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": jwt_assertion,
                    },
                )
                resp.raise_for_status()
                token_data = resp.json()
                return token_data.get("access_token")
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                "token_acquisition_failed",
                status_code=exc.response.status_code,
                detail=exc.response.text[:500],
            )
            return None
        except httpx.HTTPError as exc:
            self.logger.error("token_acquisition_error", error=str(exc))
            return None

    def _load_credentials(self) -> dict[str, Any] | None:
        """Load service account credentials from a file path or inline dict."""
        creds = self._config.credentials_json
        if isinstance(creds, dict):
            return creds
        # Treat as file path
        path = Path(creds)
        if not path.exists():
            self.logger.error("credentials_file_not_found", path=str(path))
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self.logger.error("credentials_load_error", error=str(exc))
            return None

    def _agent_path(self) -> str:
        """Return the API path for the configured agent."""
        if self._config.api_variant == "cx":
            return (
                f"/{_CX_API_VERSION}/projects/{self._config.project_id}"
                f"/locations/{self._config.location}"
                f"/agents/{self._config.agent_id}"
            )
        return (
            f"/{_ES_API_VERSION}/projects/{self._config.project_id}/agent"
        )

    # -- internal helpers ----------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HTTP client not initialised. Call connect() first.")
        return self._client


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _extract_fulfillment_text(query_result: dict[str, Any]) -> str:
    """Extract the assistant's response text from a Dialogflow queryResult.

    Checks ``fulfillmentText`` first, then falls back to the first
    ``fulfillmentMessages`` text entry.
    """
    text = (query_result.get("fulfillmentText") or "").strip()
    if text:
        return text

    for fm in query_result.get("fulfillmentMessages", []):
        text_block = fm.get("text", {})
        texts = text_block.get("text", [])
        if texts:
            return str(texts[0]).strip()

    # CX responseMessages
    for rm in query_result.get("responseMessages", []):
        text_block = rm.get("text", {})
        texts = text_block.get("text", [])
        if texts:
            return str(texts[0]).strip()

    return ""


def _parse_google_timestamp(ts: str | None) -> datetime | None:
    """Parse an ISO 8601 / RFC 3339 timestamp from Google APIs."""
    if ts is None:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _build_jwt_assertion(creds: dict[str, Any]) -> str | None:
    """Build a signed JWT assertion for Google OAuth token exchange.

    Uses RS256 signing with the private key from the service account
    credentials.  Returns ``None`` if the private key is missing or
    the ``cryptography`` library is not available.
    """
    import base64
    import json as _json
    import time as _time

    private_key_pem = creds.get("private_key")
    client_email = creds.get("client_email")
    if not private_key_pem or not client_email:
        return None

    now = int(_time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": client_email,
        "scope": "https://www.googleapis.com/auth/dialogflow",
        "aud": _GOOGLE_TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header_b64 = _b64url(_json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(_json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"), password=None
        )
        signature = private_key.sign(  # type: ignore[union-attr]
            signing_input.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        signature_b64 = _b64url(signature)
        return f"{signing_input}.{signature_b64}"
    except ImportError:
        # cryptography not installed; cannot sign JWT
        return None
    except Exception:
        return None
