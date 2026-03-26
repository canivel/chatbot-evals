"""Pydantic v2 schemas for connector CRUD operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from evalplatform.api.models.connector import ConnectorType


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ConnectorCreate(BaseModel):
    """Payload for creating a new connector."""

    name: str = Field(..., min_length=1, max_length=255)
    connector_type: ConnectorType
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ConnectorUpdate(BaseModel):
    """Payload for updating an existing connector.

    All fields are optional — only provided fields are applied.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    connector_type: ConnectorType | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ConnectorResponse(BaseModel):
    """Public representation of a connector."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    connector_type: ConnectorType
    config: dict[str, Any] = Field(default_factory=dict)
    organization_id: uuid.UUID
    is_active: bool
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ConnectorListResponse(BaseModel):
    """Paginated list of connectors."""

    items: list[ConnectorResponse]
    total: int
