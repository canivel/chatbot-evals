# Multi-Agent System

Documentation for the 13-agent development team that builds the Chatbot Evals Platform.

## Agent Team Overview

The multi-agent system simulates a complete software development team where each agent is an LLM-powered specialist. Agents communicate through a message bus, share state through a central store, and are coordinated by an orchestrator that drives sprint cycles.

```
                          Orchestrator
                         (Sprint Driver)
                               |
         +----------+----------+----------+---------+
         |          |          |          |         |
        PM      Engineering  Research    QA      Monitor
      (1 agent)  (4 agents)  (3 agents) (3 agents) (1 agent)
```

## Agent Roles and Responsibilities

| Agent | ID | Team | Key Capabilities |
|-------|----|------|-----------------|
| **Product Manager** | `pm-lead` | pm | Story generation from requirements; bug triage and fix-story creation; feature request evaluation; sprint planning with LLM-assisted prioritization; backlog management with velocity tracking |
| **Backend Engineer** | `eng-backend` | engineering | FastAPI endpoint generation; SQLAlchemy model scaffolding; Pydantic schema creation; eval pipeline logic; architecture proposals; code review |
| **Frontend Engineer** | `eng-frontend` | engineering | React/Next.js component generation; TypeScript interfaces; TailwindCSS styling; dashboard pages; custom hooks; code review |
| **Data Engineer** | `eng-data` | engineering | Database schema design; Alembic migration generation; ETL pipeline implementation; data validation rules; query optimization |
| **Infra Engineer** | `eng-infra` | engineering | Multi-stage Dockerfile generation; docker-compose configs; GitHub Actions CI/CD; Prometheus/Grafana monitoring; Nginx reverse proxy |
| **Eval Researcher** | `res-eval` | research | Evaluation metric research and design; BaseMetric implementations; coverage gap analysis; DeepEval/RAGAS expertise |
| **ML Researcher** | `res-ml` | research | LLM-as-Judge prompt design; embedding metric research; eval pipeline architecture; fine-tuning strategy research; bias mitigation |
| **Literature Reviewer** | `res-literature` | research | Academic paper analysis; structured literature reviews; gap analysis; research direction proposals; evidence-based recommendations |
| **Functional QA** | `qa-functional` | qa | Test scenario generation from acceptance criteria; LLM-driven test evaluation; bug reporting with reproduction steps; feature request suggestions |
| **Performance QA** | `qa-performance` | qa | Performance test design; latency/throughput benchmarking; threshold enforcement; bottleneck identification; regression detection |
| **Security QA** | `qa-security` | qa | OWASP Top 10 auditing; prompt injection testing; PII leakage checks; API key management verification; all security bugs filed as CRITICAL |
| **Project Monitor** | `monitor` | monitor | Sprint velocity tracking; bottleneck detection; workload balance analysis; bug pattern analysis; project health checks; evolution reports |
| **Orchestrator** | `orchestrator` | orchestrator | Sprint cycle coordination; story-to-team routing; load-balanced assignment; phase management; cross-team communication |

## Sprint Cycle

### Overview

The orchestrator drives a 5-phase sprint cycle. Each sprint produces stories, code artifacts, test results, bug reports, and metrics.

```
Sprint N
  |
  +-- Phase 1: PLANNING
  |   PM generates stories -> Orchestrator assigns to teams
  |
  +-- Phase 2: DEVELOPMENT
  |   Engineering + Research agents build in parallel
  |
  +-- Phase 3: REVIEW
  |   Cross-team review, stories move to QA
  |
  +-- Phase 4: QA
  |   Functional + Performance + Security testing
  |   Bugs filed, stories pass or fail
  |
  +-- Phase 5: RETROSPECTIVE
  |   Collect metrics, feed bugs to PM, notify Monitor
  |
Sprint N+1 begins
```

### Phase 1: Planning

1. The orchestrator sends a `SPRINT_EVENT` message to the PM agent with:
   - Current sprint number
   - Open bugs from previous sprints
   - Unconverted feature requests
   - Project metrics
2. The PM agent runs `plan_work()`, which triggers either initial backlog generation (if empty) or sprint planning.
3. For sprint planning, the PM's `BacklogManager` provides an algorithmic suggestion (capacity-based), then an LLM refines the selection.
4. The orchestrator assigns each story to the appropriate team using tag-based routing:

   | Tags | Team |
   |------|------|
   | `backend`, `frontend`, `api`, `database`, `infra`, `docker` | engineering |
   | `eval`, `metrics`, `ml`, `llm` | research |
   | `testing`, `security` | qa |
   | (default) | engineering |

5. Within a team, the agent with the fewest active stories is selected (load balancing).

### Phase 2: Development

1. The orchestrator runs all engineering and research agents concurrently via `asyncio.gather()`.
2. Each agent's `run_turn()` method:
   - Checks the message bus for incoming messages
   - Processes each message (accepts story assignments, handles queries)
   - Plans work (scans for assigned stories that are READY or IN_PROGRESS)
   - Executes tasks (generates code via LLM, stores artifacts)
3. Engineering agents use the shared `CodeGenerator` to produce Python, TypeScript, Dockerfile, and YAML code with built-in validation.
4. Research agents produce metric designs, judge prompts, literature reviews, and eval strategies.

### Phase 3: Review

Completed stories are moved from `DONE` or `IN_REVIEW` to `IN_QA` status. Engineering agents send `REVIEW_REQUEST` messages with code artifacts for cross-team review.

### Phase 4: QA

1. All QA agents receive stories in `IN_QA` status.
2. **Functional QA** generates test scenarios from acceptance criteria, evaluates each via LLM, and files bugs for failures.
3. **Performance QA** designs performance test plans, evaluates against thresholds (p95 < 500ms, etc.), and files bugs for violations.
4. **Security QA** runs OWASP Top 10 audits, checks for prompt injection vulnerabilities, validates PII handling, and files all findings as CRITICAL severity.
5. Stories that pass all QA move to DONE. Failed stories move back to IN_PROGRESS.

### Phase 5: Retrospective

1. The orchestrator collects project metrics (total stories, completed, open bugs, velocity).
2. Open bugs are sent to the PM for triage in the next sprint.
3. The Monitor agent receives metrics and:
   - Analyzes sprint results via LLM
   - Checks project health (velocity drops, bug ratios, critical bugs)
   - Sends recommendations to the PM
   - Sends config change suggestions to the orchestrator

## Message Bus Protocol

### Message Structure

Every message on the bus is a `Message` Pydantic model:

```python
class Message(BaseModel):
    id: str              # Unique hex ID (12 chars)
    from_agent: str      # Sender agent ID
    to_agent: str | None # Recipient (None = broadcast or team)
    to_team: str | None  # Target team (None = direct or broadcast)
    message_type: MessageType  # Enum value
    subject: str         # Human-readable subject line
    payload: dict        # Message-specific data
    references: list[str]  # IDs of related messages
    priority: str        # "low", "medium", "high"
    timestamp: datetime  # UTC timestamp
    reply_to: str | None # ID of message being replied to
    requires_ack: bool   # Whether acknowledgment is expected
    acknowledged: bool   # Whether acknowledged
```

### Routing Rules

| Condition | Behavior |
|-----------|----------|
| `to_agent` is set | Delivered to that agent's queue only |
| `to_team` is set | Delivered to all members of that team (excluding sender) |
| Neither set | Broadcast to all registered agents (excluding sender) |

### Message Types

| Type | Typical Sender | Typical Receiver | Purpose |
|------|---------------|-----------------|---------|
| `STORY` | PM, Orchestrator | Engineering, Research | New story assignment |
| `TASK` | Orchestrator, any agent | Specific agent | Ad-hoc task request |
| `BUG_REPORT` | QA agents | PM | Bug filed with reproduction steps |
| `FEATURE_REQUEST` | Any agent | PM | Feature proposal |
| `REVIEW_REQUEST` | Engineering | Engineering (cross-review) | Code review request |
| `REVIEW_RESULT` | Engineering, Research | Requesting agent | Review response |
| `COMPLETION` | Any agent | Orchestrator, PM | Work item completed |
| `STATUS_UPDATE` | Any agent | PM, Orchestrator | Status change (e.g., story moved) |
| `SPRINT_EVENT` | Orchestrator | All agents | Phase change broadcast |
| `QUERY` | Any agent | Any agent | Question |
| `RESPONSE` | Any agent | Querying agent | Answer to a query |
| `BROADCAST` | Monitor, Orchestrator | All agents | Broadcast announcement |
| `ESCALATION` | Monitor, QA | PM, Orchestrator | Priority escalation |
| `MONITOR_UPDATE` | Orchestrator, Monitor | Monitor, PM | Analytics/recommendations |

### Communication Patterns

**Story assignment flow:**
```
Orchestrator --[TASK]--> BackendAgent
BackendAgent --[STATUS_UPDATE]--> Orchestrator   (accepted)
BackendAgent --[REVIEW_REQUEST]--> engineering    (code ready)
FrontendAgent --[REVIEW_RESULT]--> BackendAgent   (review done)
BackendAgent --[COMPLETION]--> Orchestrator       (story done)
```

**Bug reporting flow:**
```
FunctionalQA --[BUG_REPORT]--> PM
PM --[RESPONSE]--> FunctionalQA                  (bug received)
PM --[STORY]--> engineering                       (fix story created)
```

**Monitor feedback flow:**
```
Orchestrator --[MONITOR_UPDATE]--> Monitor        (sprint metrics)
Monitor --[MONITOR_UPDATE]--> PM                  (recommendations)
Monitor --[ESCALATION]--> Orchestrator            (blocked stories)
Monitor --[BROADCAST]--> all                      (health alerts)
```

## How to Run the Agent Team

### Basic usage

```bash
# Run 3 sprints with gpt-4o-mini
uv run python scripts/run_agents.py --sprints 3

# Run 1 sprint with gpt-4o
uv run python scripts/run_agents.py --sprints 1 --model gpt-4o

# Run with an Anthropic model
uv run python scripts/run_agents.py --sprints 2 --model claude-3-haiku-20240307
```

### What happens during a run

1. **Initialization** -- `MessageBus` and `ProjectState` are created, all 13 agents are instantiated and registered with the orchestrator.
2. **Sprint execution** -- The orchestrator runs `run_sprint()` for each cycle, progressing through all 5 phases.
3. **Output** -- After all sprints, the script prints:
   - Per-sprint phase results
   - Final project metrics (stories completed, bugs, velocity)
   - An evolution report from the Monitor agent

### Programmatic usage

```python
import asyncio
from agents.message_bus import MessageBus
from agents.orchestrator import Orchestrator, OrchestratorState
from agents.state import ProjectState
from agents.base_agent import AgentConfig
from agents.pm.agent import PMAgent
from agents.engineering.backend_agent import BackendAgent

async def main():
    bus = MessageBus()
    state = ProjectState()

    # Create agents
    pm = PMAgent(
        message_bus=bus,
        project_state=state,
        config=AgentConfig(
            agent_id="pm", name="PM", role="Product Manager",
            team="pm", model="gpt-4o-mini",
        ),
    )
    backend = BackendAgent(
        message_bus=bus,
        project_state=state,
        config=AgentConfig(
            agent_id="backend", name="Backend", role="Backend Engineer",
            team="engineering", model="gpt-4o-mini",
        ),
    )

    # Create and configure orchestrator
    orchestrator = Orchestrator(
        message_bus=bus,
        project_state=state,
        config=OrchestratorState(max_sprints=1, stories_per_sprint=3),
    )
    orchestrator.register_agent(pm)
    orchestrator.register_agent(backend)

    # Run
    results = await orchestrator.run(max_sprints=1)
    print(state.get_metrics())

asyncio.run(main())
```

## Agent Configuration

### AgentConfig

Every agent is configured via an `AgentConfig` Pydantic model:

```python
class AgentConfig(BaseModel):
    agent_id: str          # Unique identifier (e.g., "eng-backend")
    name: str              # Display name (e.g., "Backend Engineer")
    role: str              # Role description
    team: str              # Team name (pm, engineering, research, qa, monitor)
    model: str = "gpt-4o-mini"   # LiteLLM model identifier
    temperature: float = 0.7      # LLM sampling temperature
    max_tokens: int = 4096        # Max response tokens
    max_turns: int = 20           # Max turns before agent stops
    system_prompt: str = ""       # Additional system prompt context
```

### OrchestratorState

```python
class OrchestratorState(BaseModel):
    phase: SprintPhase = SprintPhase.PLANNING
    agents_registered: dict[str, str] = {}  # agent_id -> team
    phase_results: dict[str, list[dict]] = {}
    max_sprints: int = 10
    stories_per_sprint: int = 5
```

## Monitor Agent and Evolution Tracking

The Monitor agent provides continuous project health monitoring:

### Health checks performed

| Check | Trigger | Action |
|-------|---------|--------|
| High bug count | > 5 open bugs | Sends ESCALATION to PM recommending bug-fix sprint |
| Blocked stories | Any story in BLOCKED status | Sends ESCALATION to orchestrator |
| Workload imbalance | Max team load > 2x min team load | Recommends rebalancing |
| Velocity drop | Current velocity < 50% of average | Broadcasts health alert |
| High bug ratio | Open bugs / total stories > 30% | Broadcasts critical alert |
| Critical bugs | Any BLOCKER or CRITICAL severity bugs | Broadcasts critical alert |
| Bug patterns | Any story with 3+ bugs | Escalates to PM for re-architecture |

### Evolution reports

The Monitor can generate comprehensive evolution reports:

```python
monitor = MonitorAgent(message_bus=bus, project_state=state)
report = await monitor.generate_evolution_report()
# Returns: progress summary, velocity trends, quality trends,
#          team performance, risks, recommended focus areas
```

## Auto-Dream Cycle

The Auto-Dream agent (defined in `.claude/agents/auto-dream.md`) provides autonomous project review and planning:

1. **Review Project State** -- Checks metrics, tests, and code health.
2. **Compact Memory** -- Removes stale data, consolidates overlapping information.
3. **Update Agent Definitions** -- Ensures agent files match the current codebase.
4. **Analyze Evolution** -- Compares current state against the architecture plan.
5. **Propose Next Steps** -- Generates prioritized features and writes to `dream-log.md`.

Run it with:
```bash
claude -p "Run the auto-dream cycle" --agent auto-dream
```

## Agent Lifecycle

Each agent follows the same lifecycle managed by `BaseAgent.run_turn()`:

```
run_turn()
  |
  +-- 1. Receive messages from bus
  |       bus.receive_all(agent_id) -> list[Message]
  |
  +-- 2. Process each message
  |       process_message(msg) -> list[Message] (responses)
  |       Send responses back to bus
  |
  +-- 3. Plan next work
  |       plan_work() -> list[dict] (tasks)
  |
  +-- 4. Execute each task
  |       execute_task(task) -> dict (result)
  |       Log activity to project state
  |
  +-- Return True (continue) or False (done)
```

The `run()` method loops `run_turn()` up to `max_turns` times. The orchestrator calls `run_turn()` during the appropriate sprint phase.

### LLM Integration

All agents use `self.call_llm()` from `BaseAgent`:

```python
response = await self.call_llm(
    messages=[{"role": "user", "content": "Your prompt here"}],
    temperature=0.5,      # Override default
    max_tokens=4096,       # Override default
    json_mode=True,        # Request JSON output
)
```

Under the hood, this uses LiteLLM's `acompletion()` which supports OpenAI, Anthropic, Google, and 100+ other providers. The model is configurable per-agent via `AgentConfig.model`.
