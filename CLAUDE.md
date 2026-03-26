# Chatbot Evals Platform

## Project Overview
Multi-agent development framework that builds an open-source SaaS platform for enterprise chatbot evaluation. Agents collaborate as PM, Engineers, Researchers, and QA in sprint cycles.

## Tech Stack
- **Python 3.11+** with **uv** for package management
- **LangGraph** for agent orchestration
- **FastAPI** for backend API
- **Next.js 14 + React + TailwindCSS + shadcn/ui** for frontend
- **PostgreSQL** + **Redis/Celery** for data and task queue
- **DeepEval + RAGAS** for eval metrics
- **LiteLLM** for multi-provider LLM support

## Commands
- `uv sync` - Install dependencies
- `uv run pytest` - Run tests
- `uv run python scripts/run_agents.py` - Run agent team
- `uv run uvicorn evalplatform.api.main:app --reload` - Run API server

## Architecture
- `agents/` - Multi-agent framework (orchestrator, PM, engineering, research, QA, monitor)
- `evalplatform/` - The eval SaaS platform (API, connectors, eval engine, reports)
- `frontend/` - Next.js dashboard
- `scripts/` - Entry points and utilities
- `tests/` - Test suite

## Agent Definitions
- `.claude/agents/` - All 14 agent definitions (orchestrator, PM, 4 engineers, 3 researchers, 3 QA, monitor, auto-dream)
- `.claude/agents/dream-log.md` - Auto-dream cycle log tracking project evolution
- Run `claude --agent auto-dream` to review project state and compact memory
- See `.claude/agents/README.md` for full agent index

## Documentation
- `docs/ARCHITECTURE.md` - System architecture and design decisions
- `docs/GETTING_STARTED.md` - Installation and quick start
- `docs/DEVELOPMENT.md` - Developer guide (adding metrics, connectors, agents)
- `docs/AGENTS.md` - Multi-agent system documentation
- `docs/METRICS.md` - Eval metrics reference
- `docs/INTEGRATIONS.md` - Connector integration guides
- `docs/API.md` - REST API reference
- Interactive API docs: `http://localhost:8000/docs` (Swagger) and `http://localhost:8000/redoc`

## Conventions
- Use `uv` for all Python package management (never pip/poetry)
- Use `structlog` for logging
- Use Pydantic v2 for all schemas
- Use async/await throughout
- All agents inherit from `BaseAgent`
- Metrics implement `BaseMetric` interface with `@metric_registry.register`
- Connectors implement `BaseConnector` interface
- Package name is `evalplatform` (not `platform`, to avoid stdlib conflict)
