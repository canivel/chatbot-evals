# Development Guide

Guide for developers working on the Chatbot Evals Platform.

## Development Setup

### Prerequisites

- Python 3.11+
- uv (package manager)
- Node.js 18+ (for frontend)
- Docker (for PostgreSQL and Redis, or use local instances)

### Installation

```bash
# Clone and install
git clone <repository-url>
cd chatbot-evals
uv sync

# Copy environment config
cp .env.example .env
# Edit .env with your API keys

# Start infrastructure (optional, for full platform)
docker-compose up db redis -d

# Verify installation
uv run pytest
```

### IDE Setup

The project uses:
- **ruff** for linting and formatting
- **mypy** for type checking
- **pytest** with `asyncio_mode = "auto"` for async tests

Recommended VS Code extensions: Python, Ruff, Pylance.

## Project Structure

The codebase has two main packages:

- **`agents/`** -- Multi-agent framework that builds the platform.
- **`evalplatform/`** -- The eval SaaS platform being built.

Both are installable packages (see `pyproject.toml` `[tool.hatch.build.targets.wheel]`).

Key design principles:
- All models use **Pydantic v2** (`BaseModel` with `Field` descriptors).
- All I/O operations are **async** (`async def`, `await`).
- Logging uses **structlog** with structured key-value pairs.
- Agents inherit from `BaseAgent`; metrics from `BaseMetric`; connectors from `BaseConnector`.

## How to Add a New Eval Metric

### Step 1: Create the metric file

Create a new file in `evalplatform/eval_engine/metrics/`:

```python
# evalplatform/eval_engine/metrics/empathy.py
"""Empathy metric.

Evaluates whether the chatbot's response demonstrates empathy
and emotional awareness toward the user.
"""

from __future__ import annotations

from typing import Any

import structlog

from evalplatform.eval_engine.judges.llm_judge import LLMJudge
from evalplatform.eval_engine.metrics.base import (
    BaseMetric,
    EvalContext,
    MetricCategory,
    MetricResult,
)
from evalplatform.eval_engine.registry import metric_registry

logger = structlog.get_logger(__name__)

# Define the judge prompt
EMPATHY_JUDGE_PROMPT = """\
You are an expert judge evaluating empathy in chatbot responses.

## Task
Evaluate whether the assistant's response demonstrates empathy toward
the user's situation and emotional state.

## Input
**User message:** {question}
**Assistant response:** {response}

## Output Format
Respond with ONLY a JSON object:
{{
  "score": <float 0.0 to 1.0>,
  "reasoning": "<explanation of the score>",
  "confidence": <float 0.0 to 1.0>,
  "empathy_signals": ["<signal 1>", "<signal 2>"],
  "missed_opportunities": ["<opportunity 1>"]
}}
"""


@metric_registry.register
class EmpathyMetric(BaseMetric):
    """Evaluates empathy in chatbot responses.

    A score of 1.0 means the response is highly empathetic.
    A score of 0.0 means the response shows no empathy.
    """

    name: str = "empathy"
    description: str = "Evaluates emotional awareness and empathy in responses"
    version: str = "1.0.0"
    category: MetricCategory = MetricCategory.QUALITY

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.0) -> None:
        self._judge = LLMJudge(model=model, temperature=temperature)

    async def evaluate(self, conversation: EvalContext) -> MetricResult:
        response = conversation.last_assistant_message
        question = conversation.last_user_message

        if not response:
            return self._build_result(
                score=0.0,
                explanation="No assistant response found.",
            )

        prompt = EMPATHY_JUDGE_PROMPT.format(
            question=question or "(no question)",
            response=response,
        )

        verdict = await self._judge.judge({"prompt": prompt})

        return self._build_result(
            score=verdict.score,
            explanation=verdict.reasoning,
            details={
                "empathy_signals": verdict.metadata.get("empathy_signals", []),
                "missed_opportunities": verdict.metadata.get("missed_opportunities", []),
                "confidence": verdict.confidence,
            },
        )
```

### Step 2: Register the metric

The `@metric_registry.register` decorator handles registration automatically. You just need to ensure the module is imported.

Add the import to `evalplatform/eval_engine/metrics/__init__.py`:

```python
from evalplatform.eval_engine.metrics.empathy import EmpathyMetric
```

And add it to `__all__`:

```python
__all__ = [
    # ... existing entries ...
    "EmpathyMetric",
]
```

### Step 3: Use the metric

```python
from evalplatform.eval_engine.engine import EvalEngine, EvalConfig

engine = EvalEngine()
config = EvalConfig(metric_names=["empathy"])
run = await engine.run_eval(conversations, config)
```

### Key rules for metrics

- **Scores must be 0.0 to 1.0.** Use `self._build_result()` which clamps automatically.
- **Return `MetricResult` from `evaluate()`.** This is enforced by the `BaseMetric` interface.
- **Use the `@metric_registry.register` decorator.** This makes the metric discoverable.
- **Use `LLMJudge` for LLM-based evaluation.** It handles retries, JSON parsing, and error recovery.
- **For computation-based metrics** (no LLM needed), compute the score directly (see `latency.py` and `cost.py`).

## How to Add a New Connector

### Step 1: Create the connector file

Create a new file in `evalplatform/connectors/`:

```python
# evalplatform/connectors/freshdesk.py
"""Freshdesk connector for importing support ticket conversations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import structlog

from evalplatform.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    ConversationData,
    MessageData,
    SyncResult,
)

logger = structlog.get_logger(__name__)


class FreshdeskConnector(BaseConnector):
    """Connector for the Freshdesk customer support platform.

    Credentials required:
    - api_key: Freshdesk API key
    - domain: Freshdesk domain (e.g., 'mycompany')
    """

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> bool:
        api_key = self.config.credentials.get("api_key", "")
        domain = self.config.credentials.get("domain", "")

        if not api_key or not domain:
            self.logger.error("missing_credentials")
            return False

        self._client = httpx.AsyncClient(
            base_url=f"https://{domain}.freshdesk.com/api/v2",
            auth=(api_key, "X"),
            timeout=30.0,
        )
        self.status = ConnectorStatus.CONNECTED
        return True

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self.status = ConnectorStatus.DISCONNECTED

    async def test_connection(self) -> bool:
        self._require_connected()
        try:
            response = await self._client.get("/tickets", params={"per_page": 1})
            return response.status_code == 200
        except Exception as exc:
            self.logger.error("connection_test_failed", error=str(exc))
            return False

    async def fetch_conversations(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ConversationData]:
        self._require_connected()

        params: dict[str, Any] = {"per_page": min(limit, 100)}
        if since:
            params["updated_since"] = since.isoformat()

        response = await self._client.get("/tickets", params=params)
        response.raise_for_status()
        tickets = response.json()

        conversations = []
        for ticket in tickets:
            conv = await self._ticket_to_conversation(ticket)
            conversations.append(conv)

        return conversations

    async def fetch_conversation(self, external_id: str) -> ConversationData:
        self._require_connected()

        response = await self._client.get(f"/tickets/{external_id}/conversations")
        response.raise_for_status()
        messages_data = response.json()

        return ConversationData(
            external_id=external_id,
            messages=[
                MessageData(
                    role="user" if msg.get("incoming") else "assistant",
                    content=msg.get("body_text", ""),
                    timestamp=msg.get("created_at"),
                )
                for msg in messages_data
            ],
        )

    async def _ticket_to_conversation(
        self, ticket: dict[str, Any]
    ) -> ConversationData:
        """Convert a Freshdesk ticket to ConversationData."""
        return ConversationData(
            external_id=str(ticket["id"]),
            messages=[
                MessageData(
                    role="user",
                    content=ticket.get("description_text", ""),
                    timestamp=ticket.get("created_at"),
                )
            ],
            metadata={
                "subject": ticket.get("subject", ""),
                "priority": ticket.get("priority"),
                "status": ticket.get("status"),
            },
        )
```

### Key rules for connectors

- **Extend `BaseConnector`** and implement all abstract methods.
- **Normalize data** into `ConversationData` / `MessageData` models.
- **Call `self._require_connected()`** at the start of data-fetching methods.
- **Use `httpx.AsyncClient`** for HTTP calls (it is already a project dependency).
- **Use `structlog`** for logging (via `self.logger`).

## How to Add a New Agent

### Step 1: Create the agent file

Create a new file in the appropriate team directory under `agents/`:

```python
# agents/qa/accessibility_qa.py
"""Accessibility QA agent for testing WCAG compliance."""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import ProjectState, StoryStatus

logger = structlog.get_logger()


class AccessibilityQAAgent(BaseAgent):
    """Agent responsible for accessibility testing (WCAG compliance)."""

    def __init__(
        self,
        message_bus: MessageBus,
        project_state: ProjectState,
        config: AgentConfig | None = None,
    ) -> None:
        if config is None:
            config = AgentConfig(
                agent_id="qa-accessibility",
                name="Accessibility QA",
                role="Accessibility QA Engineer",
                team="qa",
            )
        super().__init__(config, message_bus, project_state)

    def _get_responsibilities(self) -> str:
        return (
            "- Test UI components for WCAG 2.1 AA compliance\n"
            "- Check color contrast ratios\n"
            "- Verify keyboard navigation\n"
            "- Test screen reader compatibility"
        )

    async def process_message(self, message: Message) -> list[Message]:
        if message.message_type == MessageType.STORY:
            story_id = message.payload.get("story_id", "")
            # Process the story...
            return []
        return []

    async def plan_work(self) -> list[dict[str, Any]]:
        tasks = []
        for story in self.state.stories.values():
            if (
                story.status == StoryStatus.IN_QA
                and "frontend" in story.tags
            ):
                tasks.append({
                    "type": "accessibility_audit",
                    "story_id": story.id,
                })
        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        if task["type"] == "accessibility_audit":
            # Use self.call_llm() for LLM-assisted analysis
            result = await self.call_llm(
                [{"role": "user", "content": f"Audit story {task['story_id']} for WCAG compliance"}],
                json_mode=True,
            )
            return {"status": "completed", "result": result}
        return {"status": "skipped"}
```

### Step 2: Register with the orchestrator

Add the agent to `scripts/run_agents.py` in the `create_agents()` function:

```python
from agents.qa.accessibility_qa import AccessibilityQAAgent

# In create_agents():
agents.append(
    AccessibilityQAAgent(
        message_bus=bus,
        project_state=state,
        config=AgentConfig(
            agent_id="qa-accessibility",
            name="Accessibility QA",
            role="Accessibility QA Engineer",
            team="qa",
            model=model,
        ),
    )
)
```

### Key rules for agents

- **Extend `BaseAgent`** and implement all four abstract methods.
- **Use `self.call_llm()`** for LLM interactions -- it handles system prompts and logging.
- **Use `self.send_message()` / `self.broadcast()`** for communication.
- **Access shared state via `self.state`** (stories, bugs, artifacts).
- **Store artifacts in `self.state.artifacts[key] = content`** for code and designs.
- **Log with `structlog`** using structured key-value pairs.

## Testing

### Running tests

```bash
# All tests
uv run pytest

# Verbose
uv run pytest -v

# Specific file
uv run pytest tests/agents/test_message_bus.py

# Specific test
uv run pytest tests/agents/test_message_bus.py::test_send_direct_message

# With coverage
uv run pytest --cov=evalplatform --cov=agents --cov-report=html
```

### Writing tests

Tests use `pytest` with `pytest-asyncio`. The `asyncio_mode = "auto"` setting in `pyproject.toml` means all async test functions are automatically detected.

```python
# tests/platform/test_my_metric.py
import pytest
from evalplatform.eval_engine.metrics.base import ConversationTurn, EvalContext
from evalplatform.eval_engine.metrics.empathy import EmpathyMetric


@pytest.fixture
def metric():
    return EmpathyMetric()


@pytest.fixture
def sample_context():
    return EvalContext(
        conversation=[
            ConversationTurn(role="user", content="I'm really frustrated with this."),
            ConversationTurn(
                role="assistant",
                content="I understand your frustration and I'm sorry for the inconvenience.",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_empathy_metric_returns_result(metric, sample_context):
    result = await metric.evaluate(sample_context)
    assert 0.0 <= result.score <= 1.0
    assert result.metric_name == "empathy"


@pytest.mark.asyncio
async def test_empathy_metric_no_response(metric):
    ctx = EvalContext(
        conversation=[ConversationTurn(role="user", content="Hello")],
    )
    result = await metric.evaluate(ctx)
    assert result.score == 0.0
```

For agent tests, you can test the message bus and state independently:

```python
import pytest
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import ProjectState, Story


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def state():
    return ProjectState()


@pytest.mark.asyncio
async def test_agent_receives_messages(bus):
    bus.register_agent("test-agent", team="qa")
    msg = Message(
        from_agent="orchestrator",
        to_agent="test-agent",
        message_type=MessageType.TASK,
        subject="Test",
    )
    await bus.send(msg)

    received = await bus.receive("test-agent", timeout=1.0)
    assert received is not None
    assert received.subject == "Test"
```

### Test structure

```
tests/
+-- __init__.py
+-- agents/
|   +-- __init__.py
|   +-- test_message_bus.py     # Message bus unit tests
|   +-- test_state.py           # Project state unit tests
+-- platform/
    +-- __init__.py
    +-- test_reports.py          # Report generation tests
```

## Code Style

### Ruff configuration

The project uses ruff for linting with these rules enabled (from `pyproject.toml`):

```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

Rules:
- **E** -- pycodestyle errors
- **F** -- pyflakes
- **I** -- isort (import ordering)
- **N** -- pep8-naming
- **W** -- pycodestyle warnings
- **UP** -- pyupgrade (modern Python syntax)

```bash
# Check
uv run ruff check .

# Fix automatically
uv run ruff check --fix .

# Format
uv run ruff format .
```

### Type checking

```bash
uv run mypy evalplatform agents
```

### Coding conventions

1. **Use `from __future__ import annotations`** at the top of every module for deferred type evaluation.
2. **Use `str | None`** syntax (not `Optional[str]`) -- the `UP` ruff rule enforces this.
3. **All public functions have docstrings** with Args/Returns sections.
4. **Structured logging** -- use `structlog.get_logger()` and pass key-value pairs:
   ```python
   logger.info("story_completed", story_id=story.id, score=0.85)
   ```
5. **Pydantic models with `Field`** -- always provide `description` for API-facing fields.
6. **Async by default** -- use `async def` for any function that does I/O.
7. **Error handling** -- catch specific exceptions, log with `logger.error()` or `logger.exception()`, and return graceful fallbacks.

## Git Workflow

1. Create a feature branch from `main`.
2. Make changes following the coding conventions above.
3. Run the linter and tests:
   ```bash
   uv run ruff check .
   uv run pytest
   ```
4. Commit with a descriptive message.
5. Open a pull request against `main`.

### Commit message style

Use a short imperative summary (under 72 characters) followed by an optional body:

```
Add empathy evaluation metric

Implements a new LLM-as-Judge metric that evaluates chatbot responses
for emotional awareness and empathy. Registered with the metric
registry as "empathy" under the QUALITY category.
```
