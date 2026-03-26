# Getting Started

Guide for setting up and running the Chatbot Evals Platform.

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | 3.11+ | Runtime for agents and eval engine |
| uv | Latest | Python package management |
| Node.js | 18+ | Frontend dashboard |
| Docker | 20+ | Containerized deployment (optional) |
| docker-compose | 2.0+ | Multi-service orchestration (optional) |

You also need an API key for at least one LLM provider:
- OpenAI API key (`OPENAI_API_KEY`)
- Anthropic API key (`ANTHROPIC_API_KEY`)

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd chatbot-evals
```

### 2. Install Python dependencies with uv

```bash
# Install uv if you don't have it
pip install uv

# Install all dependencies (including dev tools)
uv sync

# Or install without dev dependencies
uv sync --no-dev
```

### 3. Configure environment

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```bash
# LLM Configuration (required -- at least one provider)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...

# Database (required for full platform, not needed for demo/agents)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chatbot_evals

# Redis (required for Celery workers)
REDIS_URL=redis://localhost:6379/0

# Auth
JWT_SECRET_KEY=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=60

# Agent Configuration
AGENT_MODEL=gpt-4o-mini
AGENT_MAX_TURNS=20
AGENT_TIMEOUT_SECONDS=900

# Eval Configuration
EVAL_JUDGE_MODEL=gpt-4o
EVAL_BATCH_SIZE=10
```

### 4. Install frontend dependencies (optional)

```bash
cd frontend
npm install
cd ..
```

## Quick Start

### Run the eval demo

The fastest way to see the platform in action. Evaluates sample conversations against 5 metrics:

```bash
uv run python scripts/demo.py
```

This will:
1. Register all 10 evaluation metrics.
2. Evaluate 3 sample customer support conversations.
3. Run faithfulness, relevance, hallucination, coherence, and completeness checks.
4. Generate an HTML report at `demo_report.html` and a JSON report at `demo_report.json`.
5. Print a summary with pass/warn/fail status for each metric.

**Note:** This requires an OpenAI API key since the LLM judge defaults to `gpt-4o`.

### Run the multi-agent development team

Launch the full team of 13 agents running sprint cycles:

```bash
# Run 3 sprint cycles with gpt-4o-mini
uv run python scripts/run_agents.py --sprints 3

# Use a different model
uv run python scripts/run_agents.py --sprints 1 --model gpt-4o

# Use Anthropic
uv run python scripts/run_agents.py --sprints 2 --model claude-3-haiku-20240307
```

This will:
1. Initialize the message bus and shared project state.
2. Create all 13 agents (PM, 4 engineering, 3 research, 3 QA, 1 monitor).
3. Register agents with the orchestrator.
4. Run sprint cycles (planning -> development -> review -> QA -> retrospective).
5. Print results for each sprint and final project metrics.

### Start the API server

```bash
uv run uvicorn evalplatform.api.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

### Start the frontend

```bash
cd frontend
npm run dev
```

The dashboard will be available at `http://localhost:3000`.

## Docker Quick Start

The simplest way to run the full platform with all dependencies:

```bash
# Start everything (PostgreSQL, Redis, API, Worker, Frontend)
docker-compose up

# Or start in detached mode
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop everything
docker-compose down
```

**Services started by docker-compose:**

| Service | Port | Description |
|---------|------|-------------|
| `db` | 5432 | PostgreSQL 16 database |
| `redis` | 6379 | Redis for Celery task queue |
| `api` | 8000 | FastAPI backend with hot-reload |
| `worker` | -- | Celery worker (4 concurrent tasks) |
| `frontend` | 3000 | Next.js dashboard |

The API automatically connects to the database and Redis. The `.env` file is loaded by all services.

## Configuration Reference

### LLM Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | -- | OpenAI API key (for gpt-* models) |
| `ANTHROPIC_API_KEY` | -- | Anthropic API key (for claude-* models) |
| `GOOGLE_API_KEY` | -- | Google API key (for gemini-* models) |
| `EVAL_JUDGE_MODEL` | `gpt-4o` | Model used by the LLM judge for evaluations |
| `AGENT_MODEL` | `gpt-4o-mini` | Model used by multi-agent team |

The platform auto-routes to the correct provider based on model name: `gpt-*` -> OpenAI, `claude-*` -> Anthropic, `gemini-*` -> Google.

### Agent Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_MAX_TURNS` | `20` | Maximum turns per agent per sprint phase |
| `AGENT_TIMEOUT_SECONDS` | `900` | Timeout for agent operations |

### Eval Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EVAL_BATCH_SIZE` | `10` | Number of conversations per eval batch |

### Infrastructure

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | -- | PostgreSQL connection string (asyncpg) |
| `REDIS_URL` | -- | Redis connection string |
| `JWT_SECRET_KEY` | -- | Secret key for JWT tokens |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRATION_MINUTES` | `60` | JWT token expiration |

## First Eval Run Walkthrough

Here is a step-by-step walkthrough of running your first evaluation programmatically:

### Step 1: Import the eval engine

```python
import asyncio
from evalplatform.eval_engine.engine import EvalEngine, EvalConfig
from evalplatform.eval_engine.metrics.base import ConversationTurn, EvalContext

# Import metrics to trigger registration
import evalplatform.eval_engine.metrics  # noqa: F401
```

### Step 2: Prepare conversation data

```python
conversation = EvalContext(
    conversation=[
        ConversationTurn(role="user", content="What are your business hours?"),
        ConversationTurn(
            role="assistant",
            content="Our business hours are Monday to Friday, 9 AM to 5 PM EST. "
                    "We are closed on weekends and federal holidays."
        ),
    ],
    ground_truth="Business hours: Mon-Fri 9 AM - 5 PM EST. Closed weekends and holidays.",
    retrieved_context=[
        "Business Hours: Monday through Friday, 9:00 AM to 5:00 PM Eastern Time. "
        "Closed on weekends and all federal holidays."
    ],
    metadata={"conversation_id": "test-001"},
)
```

### Step 3: Run the evaluation

```python
async def run():
    engine = EvalEngine()
    config = EvalConfig(
        metric_names=["faithfulness", "relevance", "hallucination"],
        max_concurrency=5,
    )

    run_result = await engine.run_eval(
        conversations=[conversation],
        config=config,
    )

    # Print results
    print(f"Overall score: {run_result.overall_score:.4f}")
    for metric_name, score in run_result.aggregate_scores.items():
        print(f"  {metric_name}: {score:.4f}")

    # Access per-conversation details
    for conv_result in run_result.conversation_results:
        for mr in conv_result.metric_results:
            print(f"  [{mr.metric_name}] {mr.score:.4f} -- {mr.explanation}")

asyncio.run(run())
```

### Step 4: Generate a report

```python
from evalplatform.reports.generator import ReportGenerator
from evalplatform.reports.exporters import ReportExporter

# Build results list from eval run
results = []
for conv_result in run_result.conversation_results:
    for mr in conv_result.metric_results:
        results.append({
            "conversation_id": conv_result.conversation_id,
            "metric_name": mr.metric_name,
            "score": mr.score,
            "explanation": mr.explanation,
        })

# Generate and export report
generator = ReportGenerator(pass_threshold=0.7)
report = generator.generate_eval_report("my-first-run", results)

exporter = ReportExporter()
html = exporter.to_html(report)
with open("my_report.html", "w") as f:
    f.write(html)
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/agents/test_message_bus.py

# Run with coverage
uv run pytest --cov=evalplatform --cov=agents
```

## Troubleshooting

### "No API key provided"

Ensure your `.env` file has at least one LLM provider API key set, and that you copied `.env.example` to `.env`.

### Import errors

Run `uv sync` to ensure all dependencies are installed. The project uses `hatchling` as the build backend and packages `evalplatform`, `agents`, and `scripts`.

### Database connection errors

If running the full API, ensure PostgreSQL is running. The easiest approach is `docker-compose up db` to start just the database service.

### Metric not found errors

Metrics must be imported before use to trigger registration. Either import `evalplatform.eval_engine.metrics` (which imports all metrics) or import individual metric modules directly.
