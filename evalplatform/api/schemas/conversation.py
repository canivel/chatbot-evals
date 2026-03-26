"""Pydantic v2 schemas for conversation and message endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConversationMessageResponse(BaseModel):
    """Public representation of a single conversation message."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class ConversationResponse(BaseModel):
    """Public representation of a conversation (without messages)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str | None = None
    connector_id: uuid.UUID
    organization_id: uuid.UUID
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """Paginated list of conversations."""

    items: list[ConversationResponse]
    total: int
