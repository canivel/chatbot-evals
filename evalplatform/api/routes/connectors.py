"""Connector CRUD and sync-trigger routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from evalplatform.api.deps import get_current_org, get_db
from evalplatform.api.models.connector import Connector
from evalplatform.api.models.organization import Organization
from evalplatform.api.schemas.connector import (
    ConnectorCreate,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorUpdate,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/connectors", tags=["connectors"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_connector_or_404(
    connector_id: uuid.UUID,
    org: Organization,
    db: AsyncSession,
) -> Connector:
    """Fetch a connector belonging to *org*, or raise 404."""
    result = await db.execute(
        select(Connector).where(
            Connector.id == connector_id,
            Connector.organization_id == org.id,
        )
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector not found",
        )
    return connector


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ConnectorListResponse,
    summary="List connectors for the current organization",
)
async def list_connectors(
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 50,
) -> ConnectorListResponse:
    """Return a paginated list of connectors owned by the organization."""
    base = select(Connector).where(Connector.organization_id == org.id)

    total_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_result.scalar_one()

    items_result = await db.execute(
        base.order_by(Connector.created_at.desc()).offset(skip).limit(limit)
    )
    items = list(items_result.scalars().all())

    return ConnectorListResponse(items=items, total=total)


@router.post(
    "",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new connector",
)
async def create_connector(
    body: ConnectorCreate,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Connector:
    """Create a connector and associate it with the current organization."""
    connector = Connector(
        name=body.name,
        connector_type=body.connector_type,
        config=body.config,
        organization_id=org.id,
        is_active=body.is_active,
    )
    db.add(connector)
    await db.flush()
    await db.refresh(connector)

    logger.info(
        "Connector created",
        connector_id=str(connector.id),
        connector_type=connector.connector_type.value,
    )
    return connector


@router.get(
    "/{connector_id}",
    response_model=ConnectorResponse,
    summary="Get a connector by ID",
)
async def get_connector(
    connector_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Connector:
    """Return a single connector owned by the current organization."""
    return await _get_connector_or_404(connector_id, org, db)


@router.put(
    "/{connector_id}",
    response_model=ConnectorResponse,
    summary="Update a connector",
)
async def update_connector(
    connector_id: uuid.UUID,
    body: ConnectorUpdate,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Connector:
    """Update one or more fields on a connector."""
    connector = await _get_connector_or_404(connector_id, org, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(connector, field, value)

    await db.flush()
    await db.refresh(connector)

    logger.info("Connector updated", connector_id=str(connector.id))
    return connector


@router.delete(
    "/{connector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connector",
)
async def delete_connector(
    connector_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Permanently remove a connector and its associated data."""
    connector = await _get_connector_or_404(connector_id, org, db)
    await db.delete(connector)
    await db.flush()
    logger.info("Connector deleted", connector_id=str(connector_id))


@router.post(
    "/{connector_id}/sync",
    response_model=ConnectorResponse,
    summary="Trigger a data sync for a connector",
)
async def sync_connector(
    connector_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Connector:
    """Trigger an asynchronous sync job for the specified connector.

    In a full implementation this would enqueue a Celery task.  For now it
    validates the connector and returns it so the caller knows the request
    was accepted.
    """
    connector = await _get_connector_or_404(connector_id, org, db)

    if not connector.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot sync an inactive connector",
        )

    # TODO: enqueue Celery sync task
    logger.info(
        "Connector sync requested",
        connector_id=str(connector.id),
        connector_type=connector.connector_type.value,
    )
    return connector
