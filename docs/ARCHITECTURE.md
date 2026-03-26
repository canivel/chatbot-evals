# Architecture

Comprehensive architecture documentation for the Chatbot Evals Platform.

## System Overview

The Chatbot Evals Platform is a dual-purpose system:

1. **Multi-Agent Development Framework** -- A team of 13 AI agents collaborating in sprint cycles to iteratively build and improve the platform itself.
2. **Eval SaaS Platform** -- The production artifact: an enterprise-grade chatbot evaluation service with connectors, an eval engine, report generation, and a dashboard.

```
+------------------------------------------------------------------+
|                    CHATBOT EVALS PLATFORM                         |
+------------------------------------------------------------------+
|                                                                   |
|  +-----------------------------+  +----------------------------+  |
|  |  MULTI-AGENT FRAMEWORK      |  |  EVAL SaaS PLATFORM        |  |
|  |                             |  |                            |  |
|  |  Orchestrator               |  |  Connectors (6 providers)  |  |
|  |    |                        |  |    |                       |  |
|  |    +-- PM Agent             |  |    v                       |  |
|  |    +-- Engineering (4)      |  |  Eval Engine (10+ metrics) |  |
|  |    +-- Research (3)         |  |    |                       |  |
|  |    +-- QA (3)               |  |    v                       |  |
|  |    +-- Monitor (1)          |  |  Report Engine             |  |
|  |                             |  |    |                       |  |
|  |  Message Bus <-> State      |  |    v                       |  |
|  |                             |  |  Dashboard (Next.js)       |  |
|  +-----------------------------+  +----------------------------+  |
|                                                                   |
+------------------------------------------------------------------+
```

## Multi-Agent Framework Architecture

### Design Inspirations

The multi-agent system draws from three open-source frameworks:

- **DeerFlow** -- Hierarchical delegation with isolated agent contexts. Each agent operates with its own context but shares state through a central store.
- **Stripe Minions** -- Deterministic sprint phases interleaved with LLM-driven creativity. The orchestrator enforces a fixed phase order while agents use LLMs freely within each phase.
- **Autoresearch** -- Constrained scope with clear evaluation metrics. Each agent has a well-defined role, and the monitor agent tracks measurable outcomes.

### Agent Team Overview

```
                        +------------------+
                        |   Orchestrator   |
                        | (Sprint Driver)  |
                        +--------+---------+
                                 |
            +--------------------+--------------------+
            |                    |                    |
     +------+------+    +-------+-------+    +-------+-------+
     |     PM      |    |  Engineering  |    |   Research    |
     +------+------+    +---+---+---+---+    +---+---+---+---+
     | Product Mgr |    | BE| FE|Data|Inf|    |Eval|ML |Lit |
     +-------------+    +---+---+---+---+    +---+---+---+---+
            |                    |                    |
            +--------------------+--------------------+
                                 |
                     +-----------+-----------+
                     |                       |
              +------+------+       +--------+-------+
              |     QA      |       |    Monitor     |
              +--+---+---+--+       +----------------+
              |Func|Perf|Sec|       | Project Monitor|
              +----+----+--+       +----------------+
```

**13 agents total across 5 teams:**

| Team | Agent | Class | Role |
|------|-------|-------|------|
| PM | Product Manager | `PMAgent` | Story generation, backlog management, sprint planning, bug triage |
| Engineering | Backend Engineer | `BackendAgent` | FastAPI endpoints, SQLAlchemy models, eval pipeline logic |
| Engineering | Frontend Engineer | `FrontendAgent` | React/Next.js components, TypeScript, TailwindCSS dashboard |
| Engineering | Data Engineer | `DataAgent` | Database schemas, Alembic migrations, ETL pipelines |
| Engineering | Infrastructure Engineer | `InfraAgent` | Dockerfiles, CI/CD pipelines, monitoring, Nginx configs |
| Research | Eval Researcher | `EvalResearcher` | Evaluation metric design and implementation |
| Research | ML Researcher | `MLResearcher` | LLM-as-Judge prompts, embedding metrics, eval strategies |
| Research | Literature Reviewer | `LiteratureReviewer` | Academic paper analysis, coverage gap identification |
| QA | Functional QA | `FunctionalQAAgent` | Test scenario generation, acceptance criteria verification |
| QA | Performance QA | `PerformanceQAAgent` | Throughput/latency benchmarking, threshold enforcement |
| QA | Security QA | `SecurityQAAgent` | OWASP Top 10 audits, prompt injection testing, PII checks |
| Monitor | Project Monitor | `MonitorAgent` | Sprint analysis, bottleneck detection, evolution tracking |
| -- | Orchestrator | `Orchestrator` | Central coordinator, sprint cycle driver |

### Sprint Cycle

Each sprint follows a deterministic 5-phase cycle:

```
+----------+     +-----------+     +--------+     +------+     +---------------+
| PLANNING | --> | DEVELOP-  | --> | REVIEW | --> |  QA  | --> | RETROSPECTIVE |
|          |     | MENT      |     |        |     |      |     |               |
| PM plans |     | Eng+Res   |     | Cross- |     | QA   |     | Collect       |
| stories, |     | build in  |     | team   |     | tests|     | metrics,      |
| assigns  |     | parallel  |     | review |     | bugs |     | feed bugs     |
| to teams |     |           |     |        |     |      |     | back to PM    |
+----------+     +-----------+     +--------+     +------+     +---------------+
```

**Phase details:**

1. **Planning** -- The orchestrator asks the PM agent to generate stories. The PM uses an LLM to create prioritized user stories with acceptance criteria. The orchestrator assigns stories to teams based on tags (`backend` -> engineering, `eval` -> research, etc.) using load-balanced assignment.

2. **Development** -- Engineering and research agents run concurrently (DeerFlow-style parallel execution). Each agent picks up assigned stories, plans implementation via LLM, generates code artifacts, and stores them in the shared project state.

3. **Review** -- Completed stories move to `IN_QA` status. Cross-team review is facilitated through `REVIEW_REQUEST` messages.

4. **QA** -- All three QA agents run concurrently against stories in QA:
   - Functional QA generates test scenarios from acceptance criteria
   - Performance QA benchmarks against latency/throughput thresholds
   - Security QA runs OWASP audits and prompt injection tests

5. **Retrospective** -- The orchestrator collects metrics, feeds open bugs back to the PM, and notifies the Monitor agent. The monitor analyzes sprint results and sends recommendations.

### Message Bus

The `MessageBus` provides async pub/sub inter-agent communication:

```
+----------+                              +----------+
| Agent A  | -- direct message ---------> | Agent B  |
+----------+                              +----------+
     |                                         ^
     |  -- team message --> [engineering] ------+
     |                          |               |
     |                          +-- Agent C ----+
     |
     +-- broadcast --> ALL agents
```

**Message types** (defined in `MessageType` enum):

| Type | Purpose |
|------|---------|
| `STORY` | New story assignment |
| `TASK` | Ad-hoc task request |
| `BUG_REPORT` | Bug filed by QA |
| `FEATURE_REQUEST` | New feature proposal |
| `REVIEW_REQUEST` | Code review request |
| `REVIEW_RESULT` | Code review response |
| `COMPLETION` | Work item completed |
| `STATUS_UPDATE` | Status change notification |
| `SPRINT_EVENT` | Phase change broadcast |
| `QUERY` | Question to another agent |
| `RESPONSE` | Answer to a query |
| `BROADCAST` | Message to all agents |
| `ESCALATION` | Priority escalation |
| `MONITOR_UPDATE` | Monitor agent analytics |

**Routing rules:**
- `to_agent` set: direct delivery to that agent's queue
- `to_team` set: delivered to all members of that team (except sender)
- Neither set: broadcast to all agents (except sender)

### Shared Project State

The `ProjectState` (Pydantic model) is the central state store accessed by all agents:

```
ProjectState
  +-- current_sprint: SprintState
  |     +-- number, stories[], completed_stories[], velocity
  +-- stories: dict[str, Story]
  |     +-- id, title, description, status, assigned_to, tags, etc.
  +-- bugs: dict[str, BugReport]
  +-- feature_requests: dict[str, FeatureRequest]
  +-- completed_sprints: list[SprintState]
  +-- agent_activity_log: list[dict]
  +-- artifacts: dict[str, str]  (code, configs, designs)
```

**Story lifecycle:**
```
BACKLOG -> READY -> IN_PROGRESS -> IN_REVIEW -> IN_QA -> DONE
                                                    |
                                                    +-> BLOCKED
```

### BaseAgent Interface

Every agent extends `BaseAgent` and implements four abstract methods:

```python
class BaseAgent(ABC):
    def _get_responsibilities(self) -> str: ...
    async def process_message(self, message: Message) -> list[Message]: ...
    async def plan_work(self) -> list[dict[str, Any]]: ...
    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]: ...
```

The base class provides:
- LLM integration via `call_llm()` using OpenAI SDK (multi-provider)
- Message bus connectivity via `send_message()` and `broadcast()`
- Access to shared project state via `self.state`
- Standard agent lifecycle: `run_turn()` loops through receive -> process -> plan -> execute

---

## Eval Platform Architecture

### High-Level Pipeline

```
External Chatbot       Connectors        Eval Engine         Reports        Dashboard
+--------------+     +-----------+     +------------+     +---------+     +---------+
|  MavenAGI    | --> |           | --> |            | --> |         | --> |         |
|  Intercom    |     |  REST API |     | 10+ Metrics|     | Aggreg. |     | Next.js |
|  Zendesk     |     |  Webhook  |     | LLM Judge  |     | Alerting|     | Charts  |
|  Custom API  |     |  CSV/JSON |     | Pairwise   |     | Export  |     | Tables  |
|              |     |           |     |            |     | HTML/CSV|     |         |
+--------------+     +-----------+     +------------+     +---------+     +---------+
```

### Connectors Layer

All connectors implement `BaseConnector`:

```python
class BaseConnector(ABC):
    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    async def test_connection(self) -> bool: ...
    async def fetch_conversations(self, since, limit) -> list[ConversationData]: ...
    async def fetch_conversation(self, external_id) -> ConversationData: ...
    async def sync(self, since) -> SyncResult: ...
```

**Implemented connectors:**

| Connector | Module | Description |
|-----------|--------|-------------|
| MavenAGI | `connectors/maven_agi.py` | MavenAGI chatbot platform |
| Intercom | `connectors/intercom.py` | Intercom messenger conversations |
| Zendesk | `connectors/zendesk.py` | Zendesk support ticket conversations |
| Webhook | `connectors/webhook.py` | Generic inbound webhook receiver |
| REST API | `connectors/rest_api.py` | Generic configurable REST client |
| File Import | `connectors/file_import.py` | CSV and JSON file import |

Connectors normalize external data into `ConversationData` with `MessageData` turns, which map directly to the eval engine's `EvalContext` and `ConversationTurn`.

### Eval Engine

The `EvalEngine` orchestrates metric evaluation:

```
EvalEngine.run_eval(conversations, config)
    |
    +-- Resolve metrics from MetricRegistry
    |
    +-- For each conversation:
    |     +-- Run all metrics concurrently (semaphore-bounded)
    |     +-- Each metric calls LLMJudge or computes directly
    |     +-- Collect MetricResult objects
    |
    +-- Compute per-metric aggregates
    +-- Compute overall score
    +-- Return EvalRun
```

**Key components:**

- **MetricRegistry** -- Singleton, thread-safe registry using `@metric_registry.register` decorator. Provides lookup by name and category.
- **EvalEngine** -- Main entry point. Accepts `EvalConfig` (metric names, concurrency, fail mode) and returns `EvalRun` with all results.
- **BaseMetric** -- Abstract class. All metrics implement `evaluate(EvalContext) -> MetricResult`. Scores normalized to 0.0-1.0.
- **LLMJudge** -- Sends structured prompts to an LLM via OpenAI SDK, parses JSON responses into `JudgeVerdict` with score, reasoning, confidence, and metadata. Includes retry logic via tenacity.
- **PairwiseJudge** -- Compares two responses for the same question, returns winner (A/B/tie) with per-criterion breakdown.

### Reports Layer

```
evalplatform/reports/
  +-- generator.py    # ReportGenerator: metric summaries, top issues, recommendations
  +-- aggregator.py   # Cross-run aggregation and trend analysis
  +-- alerting.py     # Threshold-based alerts for metric regressions
  +-- exporters.py    # Export to HTML, JSON, CSV formats
```

The `ReportGenerator` produces `EvalReport` objects containing:
- Per-metric summaries (mean, median, min, max, std dev, pass rate)
- Per-conversation breakdowns with flags
- Top issues (low-scoring metrics, multi-flag conversations)
- Automated recommendations (hallucination fixes, safety guardrails, etc.)
- Comparison reports for A/B testing eval runs

### API Layer

```
evalplatform/api/
  +-- main.py          # FastAPI application setup
  +-- config.py        # Settings via pydantic-settings
  +-- deps.py          # Dependency injection (DB sessions, auth)
  +-- routes/
  |   +-- auth.py      # JWT authentication
  |   +-- connectors.py # CRUD for connector configurations
  |   +-- conversations.py # Conversation data access
  |   +-- evals.py     # Eval run management
  |   +-- reports.py   # Report generation and retrieval
  +-- models/          # SQLAlchemy ORM models
  +-- schemas/         # Pydantic request/response schemas
```

### Workers

Celery workers handle async tasks:

```
evalplatform/workers/
  +-- connector_worker.py  # Periodic connector sync
  +-- eval_worker.py       # Background eval runs
  +-- report_worker.py     # Report generation
```

### Frontend

```
frontend/
  +-- src/app/
  |   +-- dashboard/
  |       +-- page.tsx           # Overview dashboard
  |       +-- evals/page.tsx     # Eval runs list
  |       +-- evals/[id]/page.tsx # Eval run detail
  |       +-- connectors/page.tsx # Connector management
  |       +-- reports/page.tsx    # Reports viewer
  |       +-- settings/page.tsx   # Settings
  |       +-- layout.tsx          # Dashboard layout with sidebar
  +-- src/components/
  |   +-- dashboard/
  |       +-- metric-chart.tsx    # Recharts-based metric visualization
  |       +-- nav-sidebar.tsx     # Navigation sidebar
  |       +-- score-card.tsx      # Summary score cards
  +-- src/lib/
      +-- api.ts                  # API client
      +-- utils.ts                # Utility functions
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Agent Framework | LangGraph + OpenAI SDK | Agent orchestration and multi-provider LLM access |
| Eval Libraries | DeepEval + RAGAS | Baseline eval metric implementations |
| Backend | FastAPI + Pydantic v2 | REST API with typed schemas |
| ORM | SQLAlchemy 2.0 + Alembic | Database access and migrations |
| Database | PostgreSQL | Primary data store |
| Task Queue | Celery + Redis | Async background jobs |
| Auth | python-jose + passlib | JWT authentication and password hashing |
| HTTP Client | httpx + tenacity | Async HTTP with retry logic |
| Logging | structlog | Structured logging throughout |
| Frontend | Next.js 14 + React | Dashboard application |
| Styling | TailwindCSS + shadcn/ui | UI component library |
| Infrastructure | Docker + docker-compose | Containerized deployment |
| Package Manager | uv | Fast Python dependency management |
| Linting | ruff | Python linting and formatting |
| Type Checking | mypy | Static type analysis |
| Testing | pytest + pytest-asyncio | Async test framework |

---

## Directory Structure

```
chatbot-evals/
+-- agents/                         # Multi-agent development framework
|   +-- __init__.py
|   +-- base_agent.py               # BaseAgent ABC with LLM integration
|   +-- orchestrator.py             # Sprint cycle coordinator
|   +-- message_bus.py              # Async pub/sub message bus
|   +-- state.py                    # Shared project state (stories, bugs, sprints)
|   +-- pm/                         # Product Manager agent
|   |   +-- agent.py                # PMAgent implementation
|   |   +-- backlog.py              # BacklogManager (prioritization, capacity)
|   |   +-- story_generator.py      # LLM-driven story generation
|   |   +-- prompts.py              # PM prompt templates
|   +-- engineering/                # Engineering team (4 agents)
|   |   +-- backend_agent.py        # Backend engineer
|   |   +-- frontend_agent.py       # Frontend engineer
|   |   +-- data_agent.py           # Data engineer
|   |   +-- infra_agent.py          # Infrastructure engineer
|   |   +-- code_generator.py       # Shared code generation utility
|   |   +-- prompts.py              # Engineering prompt templates
|   +-- research/                   # Research team (3 agents)
|   |   +-- eval_researcher.py      # Evaluation metrics researcher
|   |   +-- ml_researcher.py        # ML/LLM-as-Judge researcher
|   |   +-- literature_reviewer.py  # Academic literature reviewer
|   |   +-- prompts.py              # Research prompt templates
|   +-- qa/                         # QA team (3 agents)
|   |   +-- functional_qa.py        # Functional test generation
|   |   +-- performance_qa.py       # Performance benchmarking
|   |   +-- security_qa.py          # Security auditing (OWASP)
|   |   +-- bug_reporter.py         # Shared bug report creation
|   |   +-- prompts.py              # QA prompt templates
|   +-- monitor/                    # Monitor agent
|       +-- agent.py                # Project evolution tracker
|       +-- prompts.py              # Monitor prompt templates
+-- evalplatform/                   # Eval SaaS platform
|   +-- api/                        # FastAPI backend
|   |   +-- main.py                 # App setup and middleware
|   |   +-- config.py               # pydantic-settings configuration
|   |   +-- deps.py                 # Dependency injection
|   |   +-- routes/                 # API route handlers
|   |   +-- models/                 # SQLAlchemy ORM models
|   |   +-- schemas/                # Pydantic request/response schemas
|   +-- connectors/                 # External chatbot platform connectors
|   |   +-- base.py                 # BaseConnector ABC
|   |   +-- maven_agi.py            # MavenAGI connector
|   |   +-- intercom.py             # Intercom connector
|   |   +-- zendesk.py              # Zendesk connector
|   |   +-- webhook.py              # Generic webhook receiver
|   |   +-- rest_api.py             # Generic REST API client
|   |   +-- file_import.py          # CSV/JSON file importer
|   +-- eval_engine/                # Core evaluation engine
|   |   +-- engine.py               # EvalEngine orchestrator
|   |   +-- registry.py             # Singleton MetricRegistry
|   |   +-- pipeline.py             # Eval pipeline coordination
|   |   +-- metrics/                # Evaluation metrics
|   |   |   +-- base.py             # BaseMetric, EvalContext, MetricResult
|   |   |   +-- faithfulness.py     # Faithfulness / groundedness
|   |   |   +-- relevance.py        # Answer relevance
|   |   |   +-- hallucination.py    # Hallucination detection
|   |   |   +-- toxicity.py         # Safety / toxicity
|   |   |   +-- coherence.py        # Logical coherence
|   |   |   +-- completeness.py     # Answer completeness
|   |   |   +-- context_adherence.py # Knowledge boundary adherence
|   |   |   +-- conversation_quality.py # Multi-turn quality
|   |   |   +-- latency.py          # Response time (computation-based)
|   |   |   +-- cost.py             # Token cost (computation-based)
|   |   |   +-- custom.py           # Custom metric support
|   |   +-- judges/                 # LLM judge implementations
|   |       +-- base_judge.py       # BaseJudge, JudgeVerdict
|   |       +-- llm_judge.py        # LLMJudge with retry logic
|   |       +-- pairwise_judge.py   # PairwiseJudge for A/B testing
|   |       +-- prompts.py          # Judge prompt templates
|   +-- reports/                    # Report generation
|   |   +-- generator.py            # ReportGenerator, EvalReport
|   |   +-- aggregator.py           # Cross-run aggregation
|   |   +-- alerting.py             # Threshold-based alerts
|   |   +-- exporters.py            # HTML, JSON, CSV export
|   +-- workers/                    # Celery async workers
|       +-- connector_worker.py     # Periodic sync
|       +-- eval_worker.py          # Background eval runs
|       +-- report_worker.py        # Report generation
+-- frontend/                       # Next.js dashboard
|   +-- src/app/                    # App Router pages
|   +-- src/components/             # React components
|   +-- src/lib/                    # API client and utilities
+-- scripts/                        # Entry points
|   +-- demo.py                     # Eval demo on sample conversations
|   +-- run_agents.py               # Run the multi-agent team
|   +-- seed_data.py                # Seed database with sample data
+-- tests/                          # Test suite
|   +-- agents/                     # Agent unit tests
|   +-- platform/                   # Platform unit tests
+-- .claude/agents/                 # Claude Code agent definitions
+-- docker-compose.yml              # Full-stack Docker setup
+-- Dockerfile                      # Python API container
+-- pyproject.toml                  # Project config and dependencies
+-- CLAUDE.md                       # Claude Code project context
```

---

## Key Design Decisions

### 1. Multi-Agent Over Monolith

Instead of a single LLM generating the entire platform, work is distributed across specialized agents. This provides:
- **Separation of concerns** -- Each agent has deep domain expertise in its role.
- **Parallel execution** -- Engineering and research agents run concurrently within a sprint.
- **Quality gates** -- QA agents independently verify engineering output.
- **Evolving system** -- The monitor agent tracks progress and adapts the team.

### 2. Deterministic Sprint Cycle with LLM Creativity

The orchestrator enforces a fixed 5-phase sprint cycle (deterministic structure) while individual agents use LLMs freely within each phase (creative execution). This balances predictability with the generative power of LLMs.

### 3. Message Bus Over Direct Calls

Agents communicate exclusively through the message bus rather than direct method calls. This provides:
- **Decoupling** -- Agents can be added or removed without changing others.
- **Auditability** -- Full message history is maintained for debugging and analysis.
- **Routing flexibility** -- Direct, team-level, and broadcast messaging patterns.

### 4. LLM-as-Judge for Evaluation

Most metrics use an LLM judge (via `LLMJudge`) rather than heuristic scoring. This provides:
- **Nuanced assessment** -- LLMs can evaluate subjective qualities like coherence and helpfulness.
- **Structured output** -- Judges return JSON with scores, reasoning, and per-claim breakdowns.
- **Multi-provider support** -- OpenAI SDK allows switching between OpenAI, Anthropic, and other providers.
- **Fallback scores** -- Computation-based metrics (latency, cost) handle non-LLM evaluation.

### 5. Plugin-Based Metric Registry

Metrics are registered via decorator (`@metric_registry.register`) and discovered at runtime. This enables:
- **Easy extensibility** -- New metrics are added by creating a class and decorating it.
- **Runtime registration** -- Custom metrics can be added programmatically via `register_custom_metric()`.
- **Category filtering** -- Metrics can be queried by category for selective evaluation.

### 6. Normalized 0-1 Scoring

All metrics output scores between 0.0 and 1.0:
- `1.0` = best possible (e.g., fully faithful, no hallucinations, completely safe)
- `0.0` = worst possible
- This enables consistent aggregation, comparison, and threshold-based alerting across all metrics.
