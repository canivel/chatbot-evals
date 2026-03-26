"""EvalResult SQLAlchemy model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from evalplatform.api.models.base import Base

if TYPE_CHECKING:
    from evalplatform.api.models.conversation import Conversation
    from evalplatform.api.models.eval_run import EvalRun


class EvalResult(Base):
    """The result of a single metric evaluation for one conversation."""

    __tablename__ = "eval_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    metric_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict[str, Any]] = mapped_column(
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
    eval_run: Mapped[EvalRun] = relationship(
        "EvalRun", back_populates="results", lazy="selectin"
    )
    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="eval_results", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<EvalResult metric={self.metric_name!r} score={self.score:.2f} "
            f"eval_run_id={self.eval_run_id!r}>"
        )
