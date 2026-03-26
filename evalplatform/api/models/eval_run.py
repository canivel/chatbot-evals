"""EvalRun SQLAlchemy model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from evalplatform.api.models.base import Base

if TYPE_CHECKING:
    from evalplatform.api.models.connector import Connector
    from evalplatform.api.models.eval_result import EvalResult
    from evalplatform.api.models.organization import Organization


class EvalRunStatus(str, enum.Enum):
    """Lifecycle status of an evaluation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvalRun(Base):
    """A single evaluation run across a set of conversations."""

    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, server_default="{}"
    )
    status: Mapped[EvalRunStatus] = mapped_column(
        Enum(EvalRunStatus, name="eval_run_status_enum", native_enum=False),
        default=EvalRunStatus.PENDING,
        nullable=False,
        index=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    conversation_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
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
        "Organization", back_populates="eval_runs", lazy="selectin"
    )
    connector: Mapped[Connector | None] = relationship(
        "Connector", back_populates="eval_runs", lazy="selectin"
    )
    results: Mapped[list[EvalResult]] = relationship(
        "EvalResult", back_populates="eval_run", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<EvalRun name={self.name!r} status={self.status.value!r}>"
