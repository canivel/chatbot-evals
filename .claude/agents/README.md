# Agent Definitions

This directory contains the Claude Code agent definitions for the Chatbot Evals Platform multi-agent development team.

## Agents

### Core
| Agent | File | Model | Description |
|-------|------|-------|-------------|
| Orchestrator | [orchestrator.md](orchestrator.md) | opus | Central sprint cycle coordinator |
| Auto Dream | [auto-dream.md](auto-dream.md) | opus | Autonomous memory compaction and evolution |
| Monitor | [monitor.md](monitor.md) | sonnet | Project health tracking and alerts |

### Product
| Agent | File | Model | Description |
|-------|------|-------|-------------|
| Product Manager | [product-manager.md](product-manager.md) | opus | Story generation, backlog, sprint planning |

### Engineering
| Agent | File | Model | Description |
|-------|------|-------|-------------|
| Backend Engineer | [backend-engineer.md](backend-engineer.md) | sonnet | FastAPI, DB models, eval pipeline |
| Frontend Engineer | [frontend-engineer.md](frontend-engineer.md) | sonnet | Next.js dashboard, React components |
| Data Engineer | [data-engineer.md](data-engineer.md) | sonnet | Data pipelines, schemas, ETL |
| Infra Engineer | [infra-engineer.md](infra-engineer.md) | sonnet | Docker, CI/CD, deployment |

### Research
| Agent | File | Model | Description |
|-------|------|-------|-------------|
| Eval Researcher | [eval-researcher.md](eval-researcher.md) | opus | Eval metric design and implementation |
| ML Researcher | [ml-researcher.md](ml-researcher.md) | opus | LLM-as-Judge, embeddings, pipelines |
| Literature Reviewer | [literature-reviewer.md](literature-reviewer.md) | sonnet | Academic paper analysis |

### QA
| Agent | File | Model | Description |
|-------|------|-------|-------------|
| Functional QA | [functional-qa.md](functional-qa.md) | sonnet | Feature testing, bug reporting |
| Performance QA | [performance-qa.md](performance-qa.md) | sonnet | Load testing, benchmarks |
| Security QA | [security-qa.md](security-qa.md) | sonnet | OWASP, prompt injection, PII |

## Usage

Run an agent directly:
```bash
claude --agent orchestrator
claude --agent auto-dream
claude --agent product-manager
```

Run the full agent team programmatically:
```bash
uv run python scripts/run_agents.py --sprints 3 --model gpt-4o-mini
```

## Updating Agents

When the project evolves:
1. Run the **Auto Dream** agent to review and update all agent definitions
2. Or manually edit the `.md` files to reflect new capabilities
3. Keep the dream log updated in [dream-log.md](dream-log.md)
