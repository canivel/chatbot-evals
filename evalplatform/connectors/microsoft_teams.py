"""Microsoft Teams Bot platform connector.

Fetches conversation data from Microsoft Teams channels via the Microsoft
Graph API.  Each Teams channel message thread (root message + replies) is
mapped to a single conversation.

Authentication uses the OAuth 2.0 client-credentials flow against Azure AD.

Reference: https://learn.microsoft.com/en-us/graph/api/resources/chatmessage
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

_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
_TOKEN_URL_TEMPLATE = (
    "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TeamsConfig(ConnectorConfig):
    """Configuration specific to the Microsoft Teams connector."""

    connector_type: str = "microsoft_teams"
    tenant_id: str = Field(..., description="Azure AD tenant ID")
    client_id: str = Field(..., description="Azure AD application (client) ID")
    client_secret: str = Field(..., description="Azure AD client secret")
    team_id: str = Field(..., description="Teams team ID")
    channel_ids: list[str] = Field(
        ..., description="List of Teams channel IDs to monitor"
    )
    timeout_seconds: float = Field(
        default=30.0, description="HTTP request timeout in seconds"
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Number of messages per page (max 50 for Graph API)",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class TeamsConnector(BaseConnector):
    """Connector that pulls threaded conversations from Microsoft Teams channels."""

    def __init__(self, config: TeamsConfig) -> None:
        super().__init__(config)
        self._config: TeamsConfig = config
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Acquire an OAuth token and create an HTTP client."""
        self.logger.info("connecting")

        token = await self._acquire_token()
        if not token:
            self.status = ConnectorStatus.ERROR
            self.logger.error("connection_failed", reason="token_acquisition_failed")
            return False

        self._access_token = token
        self._client = httpx.AsyncClient(
            base_url=_GRAPH_BASE_URL,
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
        """Call ``GET /teams/{team-id}`` to validate credentials and permissions."""
        client = self._ensure_client()
        try:
            resp = await client.get(f"/teams/{self._config.team_id}")
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
        """Fetch threaded conversations from all configured Teams channels.

        Each root channel message and its replies form one conversation.

        Args:
            since: Only return conversations updated after this timestamp.
            limit: Maximum number of conversations to return.
        """
        self._require_connected()
        client = self._ensure_client()

        conversations: list[ConversationData] = []

        for channel_id in self._config.channel_ids:
            if len(conversations) >= limit:
                break
            channel_convos = await self._fetch_channel_conversations(
                client,
                channel_id,
                since=since,
                limit=limit - len(conversations),
            )
            conversations.extend(channel_convos)

        self.logger.info("fetch_conversations_done", count=len(conversations))
        return conversations[:limit]

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single Teams conversation by ``channel_id:message_id``.

        Args:
            external_id: A string in the form ``"<channel_id>:<message_id>"``.

        Raises:
            ValueError: If the format is invalid or the conversation is not found.
        """
        self._require_connected()
        client = self._ensure_client()

        parts = external_id.split(":", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid external_id '{external_id}'. "
                "Expected format: '<channel_id>:<message_id>'"
            )
        channel_id, message_id = parts

        path = (
            f"/teams/{self._config.team_id}/channels/{channel_id}"
            f"/messages/{message_id}"
        )
        try:
            resp = await client.get(path)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ValueError(
                    f"Message '{message_id}' not found in channel '{channel_id}'"
                ) from exc
            raise

        root_msg = resp.json()

        # Fetch replies
        replies = await self._fetch_message_replies(client, channel_id, message_id)

        return self._map_thread(channel_id, message_id, root_msg, replies)

    # -- internal fetchers ---------------------------------------------------

    async def _acquire_token(self) -> str | None:
        """Acquire an OAuth 2.0 access token using client credentials."""
        token_url = _TOKEN_URL_TEMPLATE.format(tenant_id=self._config.tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._config.timeout_seconds)
            ) as token_client:
                resp = await token_client.post(token_url, data=data)
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

    async def _fetch_channel_conversations(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch root messages from a channel and their replies."""
        conversations: list[ConversationData] = []
        path = (
            f"/teams/{self._config.team_id}/channels/{channel_id}/messages"
        )
        params: dict[str, Any] = {"$top": self._config.page_size}

        if since is not None:
            # OData filter for messages created after the given timestamp
            since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            params["$filter"] = f"lastModifiedDateTime gt {since_str}"

        next_link: str | None = None

        while len(conversations) < limit:
            try:
                if next_link:
                    # @odata.nextLink is an absolute URL
                    resp = await client.get(next_link)
                else:
                    resp = await client.get(path, params=params)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self.logger.error(
                    "fetch_channel_messages_error",
                    channel=channel_id,
                    status_code=exc.response.status_code,
                    detail=exc.response.text[:500],
                )
                raise
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_channel_messages_error",
                    channel=channel_id,
                    error=str(exc),
                )
                raise

            data = resp.json()
            items: list[dict[str, Any]] = data.get("value", [])

            for item in items:
                if len(conversations) >= limit:
                    break
                message_id = item.get("id", "")
                if not message_id:
                    continue

                try:
                    replies = await self._fetch_message_replies(
                        client, channel_id, message_id
                    )
                    conversations.append(
                        self._map_thread(channel_id, message_id, item, replies)
                    )
                except Exception:
                    self.logger.warning(
                        "fetch_replies_failed",
                        channel=channel_id,
                        message_id=message_id,
                        exc_info=True,
                    )

            next_link = data.get("@odata.nextLink")
            if not next_link:
                break

        return conversations

    async def _fetch_message_replies(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
        message_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch all replies to a root channel message, handling pagination."""
        all_replies: list[dict[str, Any]] = []
        path = (
            f"/teams/{self._config.team_id}/channels/{channel_id}"
            f"/messages/{message_id}/replies"
        )
        params: dict[str, Any] = {"$top": self._config.page_size}
        next_link: str | None = None

        while True:
            try:
                if next_link:
                    resp = await client.get(next_link)
                else:
                    resp = await client.get(path, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                self.logger.error(
                    "fetch_replies_error",
                    channel=channel_id,
                    message_id=message_id,
                    error=str(exc),
                )
                raise

            data = resp.json()
            all_replies.extend(data.get("value", []))

            next_link = data.get("@odata.nextLink")
            if not next_link:
                break

        return all_replies

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _map_thread(
        channel_id: str,
        message_id: str,
        root_message: dict[str, Any],
        replies: list[dict[str, Any]],
    ) -> ConversationData:
        """Map a Teams root message and its replies to :class:`ConversationData`."""
        all_raw = [root_message] + replies
        # Sort by creation time ascending
        all_raw.sort(key=lambda m: m.get("createdDateTime", ""))

        messages: list[MessageData] = []
        for msg in all_raw:
            body = msg.get("body", {})
            content = (body.get("content") or "").strip()
            if not content:
                continue

            messages.append(
                MessageData(
                    role=_map_teams_role(msg),
                    content=content,
                    timestamp=_parse_graph_timestamp(msg.get("createdDateTime")),
                    metadata={
                        "message_id": msg.get("id", ""),
                        "content_type": body.get("contentType", ""),
                        "from": msg.get("from", {}),
                    },
                )
            )

        started_at = _parse_graph_timestamp(root_message.get("createdDateTime"))
        ended_at = (
            _parse_graph_timestamp(all_raw[-1].get("createdDateTime"))
            if all_raw
            else None
        )

        return ConversationData(
            external_id=f"{channel_id}:{message_id}",
            messages=messages,
            metadata={
                "team_id": root_message.get("channelIdentity", {}).get("teamId", ""),
                "channel_id": channel_id,
                "importance": root_message.get("importance", ""),
            },
            started_at=started_at,
            ended_at=ended_at,
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


def _map_teams_role(msg: dict[str, Any]) -> str:
    """Determine the role of a Teams message author.

    Messages from application identities are mapped to ``"assistant"``;
    messages from regular users are mapped to ``"user"``.  System-generated
    event messages are mapped to ``"system"``.
    """
    msg_type = msg.get("messageType", "")
    if msg_type == "systemEventMessage":
        return "system"

    from_field = msg.get("from", {})
    if not from_field:
        return "user"

    # Application-identity messages are from bots
    if from_field.get("application"):
        return "assistant"

    # Check userIdentityType on the user object
    user = from_field.get("user", {})
    identity_type = user.get("userIdentityType", "")
    if identity_type in ("anonymousGuest", "federatedUser", "aadUser"):
        # Regular human users
        return "user"

    return "user"


def _parse_graph_timestamp(ts: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp from the Microsoft Graph API."""
    if ts is None:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
