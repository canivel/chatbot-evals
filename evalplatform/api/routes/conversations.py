"""Conversation listing, detail, and file-import routes."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from evalplatform.api.deps import get_current_org, get_db
from evalplatform.api.models.conversation import Conversation, ConversationMessage
from evalplatform.api.models.organization import Organization
from evalplatform.api.schemas.conversation import (
    ConversationListResponse,
    ConversationMessageResponse,
    ConversationResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_conversation_or_404(
    conversation_id: uuid.UUID,
    org: Organization,
    db: AsyncSession,
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == org.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conversation


def _conversation_to_response(conv: Conversation, msg_count: int = 0) -> ConversationResponse:
    """Build a response DTO from an ORM conversation."""
    return ConversationResponse(
        id=conv.id,
        external_id=conv.external_id,
        connector_id=conv.connector_id,
        organization_id=conv.organization_id,
        metadata=conv.metadata_,
        started_at=conv.started_at,
        ended_at=conv.ended_at,
        message_count=msg_count,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=ConversationListResponse,
    summary="List conversations for the current organization",
)
async def list_conversations(
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
    connector_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> ConversationListResponse:
    """Return a paginated list of conversations, optionally filtered by connector."""
    base = select(Conversation).where(Conversation.organization_id == org.id)
    if connector_id is not None:
        base = base.where(Conversation.connector_id == connector_id)

    total_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_result.scalar_one()

    items_result = await db.execute(
        base.order_by(Conversation.created_at.desc()).offset(skip).limit(limit)
    )
    conversations = list(items_result.scalars().all())

    # Fetch message counts in a single query
    if conversations:
        conv_ids = [c.id for c in conversations]
        count_result = await db.execute(
            select(
                ConversationMessage.conversation_id,
                func.count(ConversationMessage.id).label("msg_count"),
            )
            .where(ConversationMessage.conversation_id.in_(conv_ids))
            .group_by(ConversationMessage.conversation_id)
        )
        counts: dict[uuid.UUID, int] = {
            row.conversation_id: row.msg_count for row in count_result
        }
    else:
        counts = {}

    items = [
        _conversation_to_response(c, counts.get(c.id, 0))
        for c in conversations
    ]
    return ConversationListResponse(items=items, total=total)


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get a conversation by ID",
)
async def get_conversation(
    conversation_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationResponse:
    """Return a single conversation with its message count."""
    conv = await _get_conversation_or_404(conversation_id, org, db)

    count_result = await db.execute(
        select(func.count(ConversationMessage.id)).where(
            ConversationMessage.conversation_id == conv.id
        )
    )
    msg_count = count_result.scalar_one()

    return _conversation_to_response(conv, msg_count)


@router.get(
    "/{conversation_id}/messages",
    response_model=list[ConversationMessageResponse],
    summary="List messages for a conversation",
)
async def get_messages(
    conversation_id: uuid.UUID,
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ConversationMessageResponse]:
    """Return all messages in a conversation, ordered by timestamp."""
    # Validate ownership
    await _get_conversation_or_404(conversation_id, org, db)

    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.timestamp)
    )
    messages = list(result.scalars().all())

    return [
        ConversationMessageResponse(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            metadata=m.metadata_,
            timestamp=m.timestamp,
        )
        for m in messages
    ]


@router.post(
    "/import",
    response_model=ConversationListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import conversations from a JSON file",
)
async def import_conversations(
    org: Annotated[Organization, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(..., description="JSON file containing conversations"),
    connector_id: uuid.UUID | None = None,
) -> ConversationListResponse:
    """Import conversations from an uploaded JSON file.

    The expected format is a JSON array of objects, each with:

    .. code-block:: json

        {
          "external_id": "optional-id",
          "metadata": {},
          "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
          ]
        }

    If ``connector_id`` is not provided, a default "file_import" connector is
    expected to exist.
    """
    if file.content_type not in ("application/json", "text/json", None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}. Expected JSON.",
        )

    try:
        raw = await file.read()
        data: list[dict[str, Any]] = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid JSON file: {exc}",
        ) from exc

    if not isinstance(data, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Expected a JSON array of conversation objects",
        )

    if connector_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="connector_id query parameter is required for file imports",
        )

    created_conversations: list[Conversation] = []
    msg_counts: dict[uuid.UUID, int] = {}

    for entry in data:
        conv = Conversation(
            external_id=entry.get("external_id"),
            connector_id=connector_id,
            organization_id=org.id,
            metadata_=entry.get("metadata", {}),
        )
        db.add(conv)
        await db.flush()

        messages_data = entry.get("messages", [])
        for msg_data in messages_data:
            msg = ConversationMessage(
                conversation_id=conv.id,
                role=msg_data["role"],
                content=msg_data["content"],
                metadata_=msg_data.get("metadata", {}),
            )
            db.add(msg)

        await db.flush()
        await db.refresh(conv)
        created_conversations.append(conv)
        msg_counts[conv.id] = len(messages_data)

    logger.info(
        "Conversations imported",
        count=len(created_conversations),
        org_id=str(org.id),
    )

    items = [
        _conversation_to_response(c, msg_counts.get(c.id, 0))
        for c in created_conversations
    ]
    return ConversationListResponse(items=items, total=len(items))
