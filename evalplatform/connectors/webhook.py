"""Generic webhook connector.

Receives conversation data via inbound HTTP POST requests, validates optional
webhook signatures, and stores incoming conversations in memory for later
retrieval by the eval engine.

The connector exposes a ``handle_webhook`` method that can be mounted as a
FastAPI route.  Payload structure is configurable via JSONPath-like field
mappings so that arbitrary webhook payloads can be normalised to
:class:`ConversationData`.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

import structlog

from evalplatform.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    ConversationData,
    MessageData,
    SyncResult,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class WebhookFieldMapping(BaseModel):
    """JSONPath-like mapping from an incoming payload to ConversationData fields.

    Each value is a dot-separated path into the payload JSON, e.g.
    ``"data.conversation.id"`` resolves ``payload["data"]["conversation"]["id"]``.
    """

    conversation_id: str = Field(
        default="id", description="Path to the conversation external ID"
    )
    messages: str = Field(
        default="messages", description="Path to the list of messages"
    )
    message_role: str = Field(
        default="role", description="Path (relative to message item) to role"
    )
    message_content: str = Field(
        default="content",
        description="Path (relative to message item) to text content",
    )
    message_timestamp: str = Field(
        default="timestamp",
        description="Path (relative to message item) to timestamp",
    )
    started_at: str = Field(
        default="started_at", description="Path to conversation start timestamp"
    )
    ended_at: str = Field(
        default="ended_at", description="Path to conversation end timestamp"
    )


class WebhookConfig(ConnectorConfig):
    """Configuration specific to the webhook connector."""

    connector_type: str = "webhook"
    webhook_secret: str = Field(
        default="", description="Shared secret for HMAC signature validation"
    )
    signature_header: str = Field(
        default="X-Signature-256",
        description="HTTP header that carries the HMAC signature",
    )
    signature_algorithm: str = Field(
        default="sha256",
        description="Hash algorithm for HMAC signature (sha256, sha1)",
    )
    field_mapping: WebhookFieldMapping = Field(
        default_factory=WebhookFieldMapping,
        description="JSONPath-like mapping from webhook payload to ConversationData",
    )
    max_stored_conversations: int = Field(
        default=10_000,
        description="Maximum number of conversations to keep in memory",
    )


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class WebhookConnector(BaseConnector):
    """Connector that receives conversations via inbound webhook POSTs.

    Conversations are held in an in-memory store and served via the standard
    ``fetch_conversations`` / ``fetch_conversation`` interface.  In a
    production deployment this would be backed by a persistent store; the
    in-memory approach is suitable for development and lightweight usage.
    """

    def __init__(self, config: WebhookConfig) -> None:
        super().__init__(config)
        self._config: WebhookConfig = config
        self._conversations: dict[str, ConversationData] = {}
        self._webhook_id: str = uuid.uuid4().hex[:12]

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> bool:
        """Mark the connector as ready to receive webhooks."""
        self.status = ConnectorStatus.CONNECTED
        self.logger.info("webhook_connector_ready", webhook_id=self._webhook_id)
        return True

    async def disconnect(self) -> None:
        """Disconnect and clear stored conversations."""
        self.status = ConnectorStatus.DISCONNECTED
        self._conversations.clear()
        self.logger.info("webhook_connector_disconnected")

    async def test_connection(self) -> bool:
        """Always returns True; the webhook connector is passive."""
        return True

    # -- data fetching -------------------------------------------------------

    async def fetch_conversations(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Return stored conversations, optionally filtered by time.

        Args:
            since: Only return conversations received after this timestamp.
            limit: Maximum number of conversations to return.
        """
        conversations = list(self._conversations.values())

        if since is not None:
            conversations = [
                c
                for c in conversations
                if c.started_at is not None and c.started_at >= since
            ]

        # Sort by started_at descending (most recent first)
        conversations.sort(
            key=lambda c: c.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return conversations[:limit]

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Return a single stored conversation by external ID."""
        conv = self._conversations.get(external_id)
        if conv is None:
            raise ValueError(
                f"Conversation '{external_id}' not found in webhook store"
            )
        return conv

    # -- sync override -------------------------------------------------------

    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Return a summary of the stored conversations (no external fetch)."""
        start = time.monotonic()
        conversations = await self.fetch_conversations(since=since, limit=self._config.max_stored_conversations)
        duration = time.monotonic() - start
        return SyncResult(
            conversations_synced=len(conversations),
            errors=[],
            duration_seconds=round(duration, 3),
        )

    # -- webhook handling ----------------------------------------------------

    async def handle_webhook(
        self,
        payload: dict[str, Any],
        signature: str | None = None,
    ) -> ConversationData:
        """Process an inbound webhook payload.

        Args:
            payload: The decoded JSON body of the webhook POST.
            signature: The value of the signature header, if present.

        Returns:
            The :class:`ConversationData` that was parsed and stored.

        Raises:
            PermissionError: If signature validation fails.
            ValueError: If the payload cannot be mapped to a conversation.
        """
        # Validate signature if a secret is configured
        if self._config.webhook_secret:
            self._validate_signature(payload, signature)

        conversation = self._map_payload(payload)
        self._store_conversation(conversation)

        self.logger.info(
            "webhook_received",
            external_id=conversation.external_id,
            message_count=len(conversation.messages),
        )
        return conversation

    @property
    def webhook_url_path(self) -> str:
        """Suggested URL path for mounting this webhook endpoint."""
        return f"/webhooks/{self._config.connector_type}/{self._webhook_id}"

    # -- signature validation ------------------------------------------------

    def _validate_signature(
        self,
        payload: dict[str, Any],
        signature: str | None,
    ) -> None:
        """Validate the HMAC signature of the webhook payload.

        Raises:
            PermissionError: If the signature is missing or invalid.
        """
        if not signature:
            raise PermissionError("Missing webhook signature")

        import json

        body_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        algo = self._config.signature_algorithm
        expected = hmac.new(
            self._config.webhook_secret.encode(),
            body_bytes,
            getattr(hashlib, algo),
        ).hexdigest()

        # Support "sha256=<hex>" prefix format
        sig_value = signature.split("=", 1)[-1] if "=" in signature else signature

        if not hmac.compare_digest(expected, sig_value):
            self.logger.warning("webhook_signature_invalid")
            raise PermissionError("Invalid webhook signature")

    # -- payload mapping -----------------------------------------------------

    def _map_payload(self, payload: dict[str, Any]) -> ConversationData:
        """Map an arbitrary webhook payload to :class:`ConversationData` using field mapping."""
        mapping = self._config.field_mapping

        external_id = str(
            _resolve_path(payload, mapping.conversation_id)
            or uuid.uuid4().hex
        )

        raw_messages = _resolve_path(payload, mapping.messages)
        messages: list[MessageData] = []

        if isinstance(raw_messages, list):
            for raw_msg in raw_messages:
                if not isinstance(raw_msg, dict):
                    continue
                role = str(_resolve_path(raw_msg, mapping.message_role) or "user")
                content = str(_resolve_path(raw_msg, mapping.message_content) or "")
                ts_raw = _resolve_path(raw_msg, mapping.message_timestamp)
                timestamp = _parse_timestamp(ts_raw)

                messages.append(
                    MessageData(
                        role=role,
                        content=content,
                        timestamp=timestamp,
                        metadata={
                            k: v
                            for k, v in raw_msg.items()
                            if k
                            not in (
                                mapping.message_role,
                                mapping.message_content,
                                mapping.message_timestamp,
                            )
                        },
                    )
                )

        started_at = _parse_timestamp(_resolve_path(payload, mapping.started_at))
        ended_at = _parse_timestamp(_resolve_path(payload, mapping.ended_at))

        return ConversationData(
            external_id=external_id,
            messages=messages,
            metadata={"source": "webhook", "raw_keys": list(payload.keys())},
            started_at=started_at,
            ended_at=ended_at,
        )

    # -- storage helpers -----------------------------------------------------

    def _store_conversation(self, conversation: ConversationData) -> None:
        """Store a conversation, evicting the oldest if at capacity."""
        self._conversations[conversation.external_id] = conversation

        # Evict oldest conversations if we exceed capacity
        if len(self._conversations) > self._config.max_stored_conversations:
            sorted_keys = sorted(
                self._conversations.keys(),
                key=lambda k: (
                    self._conversations[k].started_at
                    or datetime.min.replace(tzinfo=timezone.utc)
                ),
            )
            excess = len(self._conversations) - self._config.max_stored_conversations
            for key in sorted_keys[:excess]:
                del self._conversations[key]
            self.logger.debug("evicted_old_conversations", count=excess)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _resolve_path(data: dict[str, Any] | Any, path: str) -> Any:
    """Resolve a dot-separated path against a nested dict.

    Example::

        _resolve_path({"a": {"b": 1}}, "a.b")  # -> 1

    Returns ``None`` if any segment is missing.
    """
    current: Any = data
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            return None
    return current


def _parse_timestamp(value: Any) -> datetime | None:
    """Best-effort timestamp parse from various formats."""
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError):
            return None

    value_str = str(value)
    try:
        dt = datetime.fromisoformat(value_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        pass

    # Numeric string (epoch seconds)
    try:
        return datetime.fromtimestamp(float(value_str), tz=timezone.utc)
    except (ValueError, OSError):
        return None
