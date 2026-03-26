"""Abstract connector interface and shared data models for platform connectors.

Every connector that pulls conversation data from an external chatbot platform
must implement :class:`BaseConnector`.  The shared Pydantic models defined here
(``ConnectorConfig``, ``MessageData``, ``ConversationData``, ``SyncResult``)
provide a canonical representation that the rest of the eval engine consumes.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConnectorConfig(BaseModel):
    """Base configuration shared by all connectors."""

    name: str = Field(..., description="Human-readable connector name")
    connector_type: str = Field(
        ..., description="Connector type identifier (e.g. 'intercom', 'zendesk')"
    )
    credentials: dict[str, Any] = Field(
        default_factory=dict, description="Platform-specific authentication credentials"
    )
    settings: dict[str, Any] = Field(
        default_factory=dict, description="Additional connector-specific settings"
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConnectorStatus(str, Enum):
    """Runtime status of a connector instance."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    SYNCING = "syncing"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Conversation data models
# ---------------------------------------------------------------------------


class MessageData(BaseModel):
    """A single message within a conversation."""

    role: str = Field(
        ...,
        description="Role of the message author: 'user', 'assistant', or 'system'",
    )
    content: str = Field(..., description="Text content of the message")
    timestamp: datetime | None = Field(
        default=None, description="When this message was sent"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary metadata attached to the message"
    )


class ConversationData(BaseModel):
    """Canonical representation of a conversation fetched from an external platform."""

    external_id: str = Field(
        ..., description="Unique identifier of the conversation on the source platform"
    )
    messages: list[MessageData] = Field(
        default_factory=list, description="Ordered list of messages in the conversation"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Platform-specific metadata for the conversation"
    )
    started_at: datetime | None = Field(
        default=None, description="When the conversation started"
    )
    ended_at: datetime | None = Field(
        default=None, description="When the conversation ended"
    )


# ---------------------------------------------------------------------------
# Sync result
# ---------------------------------------------------------------------------


class SyncResult(BaseModel):
    """Summary returned after a connector sync operation."""

    conversations_synced: int = Field(
        0, description="Number of conversations successfully synced"
    )
    errors: list[str] = Field(
        default_factory=list, description="Error messages encountered during sync"
    )
    duration_seconds: float = Field(
        0.0, description="Wall-clock duration of the sync in seconds"
    )


# ---------------------------------------------------------------------------
# Abstract base connector
# ---------------------------------------------------------------------------


class BaseConnector(ABC):
    """Abstract base class for all platform connectors.

    Subclasses must implement the connection lifecycle methods
    (:meth:`connect`, :meth:`disconnect`, :meth:`test_connection`) as well as
    the data-fetching methods (:meth:`fetch_conversations`,
    :meth:`fetch_conversation`).

    The default :meth:`sync` implementation delegates to
    :meth:`fetch_conversations` and captures timing / errors automatically.
    Subclasses may override it for more sophisticated sync strategies.
    """

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config
        self.status: ConnectorStatus = ConnectorStatus.DISCONNECTED
        self.logger = structlog.get_logger(
            __name__,
            connector_name=config.name,
            connector_type=config.connector_type,
        )

    # -- lifecycle -----------------------------------------------------------

    @abstractmethod
    async def connect(self) -> bool:
        """Establish a connection to the external platform.

        Returns:
            ``True`` if the connection was established successfully.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Cleanly disconnect from the external platform."""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """Verify that the current credentials and configuration are valid.

        Returns:
            ``True`` if the platform responds successfully to a lightweight
            health / authentication check.
        """
        ...

    # -- data fetching -------------------------------------------------------

    @abstractmethod
    async def fetch_conversations(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        """Fetch a batch of conversations from the platform.

        Args:
            since: If provided, only return conversations updated after this
                timestamp.
            limit: Maximum number of conversations to return.

        Returns:
            A list of :class:`ConversationData` instances.
        """
        ...

    @abstractmethod
    async def fetch_conversation(self, external_id: str) -> ConversationData:
        """Fetch a single conversation by its platform-specific identifier.

        Args:
            external_id: The conversation ID on the source platform.

        Returns:
            A :class:`ConversationData` instance.

        Raises:
            ValueError: If the conversation cannot be found.
        """
        ...

    # -- sync ----------------------------------------------------------------

    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Run a full sync, fetching conversations and returning a summary.

        The default implementation fetches conversations via
        :meth:`fetch_conversations` and records timing and errors.  Subclasses
        may override for incremental / cursor-based strategies.

        Args:
            since: If provided, only sync conversations updated after this
                timestamp.
        """
        self.status = ConnectorStatus.SYNCING
        self.logger.info("sync_started", since=since)

        start = time.monotonic()
        errors: list[str] = []
        conversations_synced = 0

        try:
            conversations = await self.fetch_conversations(since=since)
            conversations_synced = len(conversations)
        except Exception as exc:
            error_msg = f"Sync failed: {exc}"
            errors.append(error_msg)
            self.logger.error("sync_error", error=error_msg, exc_info=True)
            self.status = ConnectorStatus.ERROR
        else:
            self.status = ConnectorStatus.CONNECTED
            self.logger.info("sync_completed", conversations_synced=conversations_synced)

        duration = time.monotonic() - start

        return SyncResult(
            conversations_synced=conversations_synced,
            errors=errors,
            duration_seconds=round(duration, 3),
        )

    # -- helpers -------------------------------------------------------------

    def _require_connected(self) -> None:
        """Raise if the connector is not in a connected state."""
        if self.status not in (ConnectorStatus.CONNECTED, ConnectorStatus.SYNCING):
            raise RuntimeError(
                f"Connector '{self.config.name}' is not connected "
                f"(status={self.status.value}). Call connect() first."
            )

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} name={self.config.name!r} "
            f"type={self.config.connector_type!r} status={self.status.value!r}>"
        )
