"""Organization SQLAlchemy model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from evalplatform.api.models.base import Base

if TYPE_CHECKING:
    from evalplatform.api.models.connector import Connector
    from evalplatform.api.models.conversation import Conversation
    from evalplatform.api.models.eval_run import EvalRun
    from evalplatform.api.models.user import User


class Organization(Base):
    """An organization (tenant) that owns users, connectors, and eval runs."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    api_key: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True, index=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default="{}"
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
    users: Mapped[list[User]] = relationship(
        "User", back_populates="organization", lazy="selectin"
    )
    connectors: Mapped[list[Connector]] = relationship(
        "Connector", back_populates="organization", lazy="selectin"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation", back_populates="organization", lazy="selectin"
    )
    eval_runs: Mapped[list[EvalRun]] = relationship(
        "EvalRun", back_populates="organization", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Organization slug={self.slug!r}>"
