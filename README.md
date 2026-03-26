# Chatbot Evals Platform

Open-source multi-agent SaaS platform for enterprise chatbot evaluation. Connects to any chatbot platform (MavenAGI, Intercom, Zendesk, etc.) and produces state-of-the-art evaluations using LLM-as-Judge, statistical metrics, and custom evaluators.

## Architecture

### Multi-Agent Development Team
A team of AI agents collaborates in sprint cycles to iteratively build and improve the platform:

| Team | Agents | Role |
|------|--------|------|
| **PM** | Product Manager | Story generation, backlog management, sprint planning |
| **Engineering** | Backend, Frontend, Data, Infra | Build platform features |
| **Research** | Eval Researcher, ML Researcher, Literature Reviewer | Design and implement eval metrics |
| **QA** | Functional, Performance, Security | Test features, report bugs |
| **Monitor** | Project Monitor | Track evolution, detect bottlenecks, update agents |

### Eval Platform
```
Chatbot Platform --> Connector --> Eval Engine --> Report Engine --> Dashboard
(MavenAGI, etc.)    (REST/WH)    (10+ metrics)   (Aggregation)   (Next.js)
```

## Eval Metrics

| Metric | Description |
|--------|-------------|
| Faithfulness | Is the response grounded in provided context? |
| Relevance | Does the response answer the user's question? |
| Hallucination | Does the response contain fabricated information? |
| Toxicity | Is the response free from harmful content? |
| Coherence | Is the response logically structured? |
| Completeness | Does the response fully address the query? |
| Context Adherence | Does the chatbot stay within its knowledge boundary? |
| Conversation Quality | Multi-turn coherence and topic tracking |
| Latency | Response time statistics |
| Cost | Token usage and estimated cost |

## Quick Start

```bash
# Install dependencies
uv sync

# Run the eval demo on sample conversations
uv run python scripts/demo.py

# Run the multi-agent development team
uv run python scripts/run_agents.py --sprints 3

# Start the full platform with Docker
docker-compose up

# Run tests
uv run pytest
```

## Tech Stack

- **Agent Framework**: LangGraph + OpenAI SDK
- **Eval Libraries**: DeepEval, RAGAS, custom LLM-as-Judge
- **Backend**: FastAPI + SQLAlchemy + Celery
- **Frontend**: Next.js 14 + React + TailwindCSS + shadcn/ui
- **Database**: PostgreSQL + Redis
- **Infrastructure**: Docker + docker-compose

## Project Structure

```
chatbot-evals/
├── agents/                    # Multi-agent development framework
│   ├── orchestrator.py        # Central coordinator
│   ├── base_agent.py          # Base agent class
│   ├── message_bus.py         # Inter-agent communication
│   ├── state.py               # Shared project state
│   ├── pm/                    # Product Manager agent
│   ├── engineering/           # Engineering team
│   ├── research/              # Research team
│   ├── qa/                    # QA team
│   └── monitor/               # Project monitor agent
├── evalplatform/              # Eval SaaS platform
│   ├── api/                   # FastAPI backend
│   ├── connectors/            # Chatbot platform connectors
│   ├── eval_engine/           # Evaluation engine + metrics
│   ├── reports/               # Report generation
│   └── workers/               # Async task workers
├── frontend/                  # Next.js dashboard
├── docs/                      # Documentation
├── tests/                     # Test suite
├── scripts/                   # Entry points
└── .claude/agents/            # Agent definitions (14 agents)
```

## Connectors

| Platform | Status |
|----------|--------|
| MavenAGI | Implemented |
| Intercom | Implemented |
| Zendesk | Implemented |
| Generic Webhook | Implemented |
| Generic REST API | Implemented |
| File Import (CSV/JSON) | Implemented |

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System design, data flow, design decisions |
| [Getting Started](docs/GETTING_STARTED.md) | Installation, quick start, first eval |
| [Development Guide](docs/DEVELOPMENT.md) | Adding metrics, connectors, agents |
| [Agent System](docs/AGENTS.md) | Multi-agent team, sprint cycles, communication |
| [Metrics Reference](docs/METRICS.md) | All eval metrics with examples |
| [Integrations](docs/INTEGRATIONS.md) | Connector setup for each platform |
| [API Reference](docs/API.md) | REST API endpoints with examples |

### Interactive API Docs

Start the API server and visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## License

MIT
