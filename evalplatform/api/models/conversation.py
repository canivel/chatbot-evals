"""Conversation and ConversationMessage SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from evalplatform.api.models.base import Base

if TYPE_CHECKING:
    from evalplatform.api.models.connector import Connector
    from evalplatform.api.models.eval_result import EvalResult
    from evalplatform.api.models.organization import Organization


class Conversation(Base):
    """A chatbot conversation ingested from an external connector."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, server_default="{}"
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # -- relationships -------------------------------------------------------
    connector: Mapped[Connector] = relationship(
        "Connector", back_populates="conversations", lazy="selectin"
    )
    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="conversations", lazy="selectin"
    )
    messages: Mapped[list[ConversationMessage]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        lazy="selectin",
        order_by="ConversationMessage.timestamp",
    )
    eval_results: Mapped[list[EvalResult]] = relationship(
        "EvalResult", back_populates="conversation", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id!r} external_id={self.external_id!r}>"


class ConversationMessage(Base):
    """A single message (turn) within a conversation."""

    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, server_default="{}"
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # -- relationships -------------------------------------------------------
    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<ConversationMessage role={self.role!r} conversation_id={self.conversation_id!r}>"
