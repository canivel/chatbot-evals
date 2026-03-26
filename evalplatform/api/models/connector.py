"""Connector SQLAlchemy model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from evalplatform.api.models.base import Base

if TYPE_CHECKING:
    from evalplatform.api.models.conversation import Conversation
    from evalplatform.api.models.eval_run import EvalRun
    from evalplatform.api.models.organization import Organization


class ConnectorType(str, enum.Enum):
    """Supported third-party connector integrations."""

    MAVEN_AGI = "maven_agi"
    INTERCOM = "intercom"
    ZENDESK = "zendesk"
    WEBHOOK = "webhook"
    REST_API = "rest_api"
    FILE_IMPORT = "file_import"


class Connector(Base):
    """A configured data connector that ingests conversations from an external source."""

    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    connector_type: Mapped[ConnectorType] = mapped_column(
        Enum(ConnectorType, name="connector_type_enum", native_enum=False),
        nullable=False,
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default="{}"
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(
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
    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="connectors", lazy="selectin"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation", back_populates="connector", lazy="selectin"
    )
    eval_runs: Mapped[list[EvalRun]] = relationship(
        "EvalRun", back_populates="connector", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Connector name={self.name!r} type={self.connector_type.value!r}>"
