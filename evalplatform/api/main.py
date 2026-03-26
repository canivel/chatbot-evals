"""FastAPI application entry point for the chatbot-evals platform."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import structlog

from evalplatform.api.config import get_settings
from evalplatform.api.models.base import close_db, init_db
from evalplatform.api.routes import auth, connectors, conversations, evals, reports

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# OpenAPI tag metadata
# ---------------------------------------------------------------------------

tags_metadata: list[dict[str, Any]] = [
    {
        "name": "auth",
        "description": (
            "User registration, login, JWT token management, and organization "
            "creation. Most other endpoints require a valid Bearer token obtained "
            "from **POST /auth/login**."
        ),
    },
    {
        "name": "connectors",
        "description": (
            "CRUD operations for data connectors that ingest conversations from "
            "external chatbot platforms (MavenAGI, Intercom, Zendesk, webhook, "
            "REST API, file import). Includes triggering data sync jobs."
        ),
    },
    {
        "name": "conversations",
        "description": (
            "Browse and retrieve synced conversations and their messages. "
            "Supports filtering by connector and file-based bulk import."
        ),
    },
    {
        "name": "evals",
        "description": (
            "Create and manage evaluation runs that score conversations using "
            "LLM-as-judge metrics (faithfulness, relevance, coherence, safety, "
            "and more). View per-conversation results and cancel in-progress runs."
        ),
    },
    {
        "name": "reports",
        "description": (
            "Analytics and reporting endpoints: organisation-level dashboard, "
            "per-run detailed reports, side-by-side run comparison, metric "
            "trend analysis over time, and CSV/JSON export."
        ),
    },
    {
        "name": "health",
        "description": "Lightweight liveness / readiness probe for load balancers and orchestrators.",
    },
]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup / shutdown resources."""
    logger.info("Starting chatbot-evals API")
    await init_db()
    yield
    await close_db()
    logger.info("Chatbot-evals API shut down")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    application = FastAPI(
        title="Chatbot Evals Platform",
        summary="Evaluate enterprise chatbot quality with LLM-as-judge metrics.",
        description=(
            "The **Chatbot Evals Platform** is an open-source SaaS solution for "
            "enterprise chatbot evaluation.\n\n"
            "### Capabilities\n\n"
            "- **Ingest** conversations from MavenAGI, Intercom, Zendesk, webhooks, "
            "REST APIs, or file uploads (CSV/JSON/JSONL).\n"
            "- **Evaluate** conversations using configurable LLM-as-judge metrics: "
            "faithfulness, relevance, coherence, safety, completeness, and custom metrics.\n"
            "- **Report** on quality trends over time, compare evaluation runs "
            "side-by-side, and export results as CSV or JSON.\n\n"
            "### Authentication\n\n"
            "Register via `POST /api/v1/auth/register`, then obtain a JWT token with "
            "`POST /api/v1/auth/login`. Include the token in the `Authorization: Bearer <token>` "
            "header for all authenticated endpoints."
        ),
        version="0.1.0",
        contact={
            "name": "Chatbot Evals Team",
            "url": "https://github.com/chatbot-evals/chatbot-evals",
            "email": "support@chatbot-evals.dev",
        },
        license_info={
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT",
        },
        openapi_tags=tags_metadata,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # -- CORS ----------------------------------------------------------------
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Routers -------------------------------------------------------------
    api_prefix = "/api/v1"
    application.include_router(auth.router, prefix=api_prefix)
    application.include_router(connectors.router, prefix=api_prefix)
    application.include_router(conversations.router, prefix=api_prefix)
    application.include_router(evals.router, prefix=api_prefix)
    application.include_router(reports.router, prefix=api_prefix)

    # -- Health check --------------------------------------------------------
    @application.get(
        "/health",
        tags=["health"],
        summary="Health check",
        response_description="Returns status 'ok' when the service is healthy.",
    )
    async def health() -> dict[str, str]:
        """Return a simple health-check response.

        Use this endpoint for liveness and readiness probes. It does not require
        authentication and performs no database or downstream checks.
        """
        return {"status": "ok"}

    # -- Global exception handler --------------------------------------------
    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.error(
            "Unhandled exception",
            path=str(request.url),
            method=request.method,
            error=str(exc),
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    return application


app = create_app()
