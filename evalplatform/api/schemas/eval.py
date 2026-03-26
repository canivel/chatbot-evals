"""Pydantic v2 schemas for evaluation runs and results."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from evalplatform.api.models.eval_run import EvalRunStatus


# ---------------------------------------------------------------------------
# Metric metadata
# ---------------------------------------------------------------------------

class MetricInfo(BaseModel):
    """Metadata about a single available metric."""

    name: str
    description: str
    category: str
    version: str


class MetricListResponse(BaseModel):
    """List of available metrics the platform can evaluate."""

    metrics: list[MetricInfo]


# ---------------------------------------------------------------------------
# Eval run
# ---------------------------------------------------------------------------

class EvalRunCreate(BaseModel):
    """Payload for starting a new evaluation run."""

    name: str = Field(..., min_length=1, max_length=255)
    connector_id: uuid.UUID | None = None
    metrics: list[str] = Field(
        ..., min_length=1, description="List of metric names to run"
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional configuration (judge model, batch size, etc.)",
    )
    conversation_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Specific conversations to evaluate; if None, all from connector",
    )


class EvalRunResponse(BaseModel):
    """Public representation of an evaluation run."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    organization_id: uuid.UUID
    connector_id: uuid.UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    status: EvalRunStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    conversation_count: int = 0
    created_at: datetime
    updated_at: datetime


class EvalRunListResponse(BaseModel):
    """Paginated list of evaluation runs."""

    items: list[EvalRunResponse]
    total: int


# ---------------------------------------------------------------------------
# Eval result
# ---------------------------------------------------------------------------

class EvalResultResponse(BaseModel):
    """Public representation of a single evaluation result."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    eval_run_id: uuid.UUID
    conversation_id: uuid.UUID
    metric_name: str
    score: float
    explanation: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class EvalResultListResponse(BaseModel):
    """Paginated list of evaluation results."""

    items: list[EvalResultResponse]
    total: int
