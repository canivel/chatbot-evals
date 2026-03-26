"""Authentication routes: register, login, current user, and org creation."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from evalplatform.api.config import Settings, get_settings
from evalplatform.api.deps import get_current_user, get_db
from evalplatform.api.models.organization import Organization
from evalplatform.api.models.user import User
from evalplatform.api.schemas.auth import (
    OrganizationCreate,
    OrganizationResponse,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def _verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def _create_access_token(
    user_id: uuid.UUID,
    settings: Settings,
) -> tuple[str, int]:
    """Return ``(encoded_jwt, expires_in_seconds)``."""
    expires_delta = timedelta(minutes=settings.jwt_expiration)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Create a new user account.

    Returns the created user (without password).
    """
    # Check for duplicate email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Validate organization if provided
    if body.organization_id is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == body.organization_id)
        )
        if org_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )

    user = User(
        email=body.email,
        hashed_password=_hash_password(body.password),
        full_name=body.full_name,
        organization_id=body.organization_id,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    logger.info("User registered", user_id=str(user.id), email=user.email)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Obtain a JWT access token",
)
async def login(
    body: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Authenticate with email and password, returning a JWT token."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not _verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    token, expires_in = _create_access_token(user.id, settings)
    logger.info("User logged in", user_id=str(user.id))
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the current authenticated user",
)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the profile of the currently authenticated user."""
    return user


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new organization",
)
async def create_organization(
    body: OrganizationCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Organization:
    """Create an organization and assign the current user to it.

    The user becomes the first member of the new organization.  A random API
    key is generated automatically.
    """
    # Check for duplicate slug
    existing = await db.execute(
        select(Organization).where(Organization.slug == body.slug)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An organization with this slug already exists",
        )

    org = Organization(
        name=body.name,
        slug=body.slug,
        api_key=secrets.token_urlsafe(32),
    )
    db.add(org)
    await db.flush()

    # Associate the user with the new organization
    user.organization_id = org.id
    await db.flush()
    await db.refresh(org)

    logger.info(
        "Organization created",
        org_id=str(org.id),
        slug=org.slug,
        created_by=str(user.id),
    )
    return org
