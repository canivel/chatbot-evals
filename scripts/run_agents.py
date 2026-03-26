#!/usr/bin/env python3
"""Entry point to run the multi-agent development team.

Initializes all agents, registers them with the orchestrator,
and runs sprint cycles to iteratively build the chatbot eval platform.

Usage:
    uv run python scripts/run_agents.py [--sprints N] [--model MODEL]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.message_bus import MessageBus
from agents.orchestrator import Orchestrator, OrchestratorState
from agents.state import ProjectState
from agents.base_agent import AgentConfig

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


def create_agents(bus: MessageBus, state: ProjectState, model: str):
    """Create and return all agents for the development team."""
    agents = []

    # PM Agent
    from agents.pm.agent import PMAgent
    pm = PMAgent(
        message_bus=bus,
        project_state=state,
        config=AgentConfig(
            agent_id="pm-lead",
            name="Product Manager",
            role="Lead Product Manager",
            team="pm",
            model=model,
        ),
    )
    agents.append(pm)

    # Engineering Team
    from agents.engineering.backend_agent import BackendAgent
    from agents.engineering.frontend_agent import FrontendAgent
    from agents.engineering.data_agent import DataAgent
    from agents.engineering.infra_agent import InfraAgent

    agents.extend([
        BackendAgent(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="eng-backend",
                name="Backend Engineer",
                role="Senior Backend Engineer",
                team="engineering",
                model=model,
            ),
        ),
        FrontendAgent(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="eng-frontend",
                name="Frontend Engineer",
                role="Senior Frontend Engineer",
                team="engineering",
                model=model,
            ),
        ),
        DataAgent(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="eng-data",
                name="Data Engineer",
                role="Senior Data Engineer",
                team="engineering",
                model=model,
            ),
        ),
        InfraAgent(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="eng-infra",
                name="Infrastructure Engineer",
                role="Senior Infrastructure Engineer",
                team="engineering",
                model=model,
            ),
        ),
    ])

    # Research Team
    from agents.research.eval_researcher import EvalResearcher
    from agents.research.ml_researcher import MLResearcher
    from agents.research.literature_reviewer import LiteratureReviewer

    agents.extend([
        EvalResearcher(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="res-eval",
                name="Eval Researcher",
                role="Evaluation Metrics Researcher",
                team="research",
                model=model,
            ),
        ),
        MLResearcher(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="res-ml",
                name="ML Researcher",
                role="Machine Learning Researcher",
                team="research",
                model=model,
            ),
        ),
        LiteratureReviewer(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="res-literature",
                name="Literature Reviewer",
                role="Academic Literature Reviewer",
                team="research",
                model=model,
            ),
        ),
    ])

    # QA Team
    from agents.qa.functional_qa import FunctionalQAAgent
    from agents.qa.performance_qa import PerformanceQAAgent
    from agents.qa.security_qa import SecurityQAAgent

    agents.extend([
        FunctionalQAAgent(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="qa-functional",
                name="Functional QA",
                role="Functional QA Engineer",
                team="qa",
                model=model,
            ),
        ),
        PerformanceQAAgent(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="qa-performance",
                name="Performance QA",
                role="Performance QA Engineer",
                team="qa",
                model=model,
            ),
        ),
        SecurityQAAgent(
            message_bus=bus,
            project_state=state,
            config=AgentConfig(
                agent_id="qa-security",
                name="Security QA",
                role="Security QA Engineer",
                team="qa",
                model=model,
            ),
        ),
    ])

    # Monitor Agent
    from agents.monitor.agent import MonitorAgent
    monitor = MonitorAgent(message_bus=bus, project_state=state)
    agents.append(monitor)

    return agents


async def main(sprints: int = 3, model: str = "gpt-4o-mini") -> None:
    """Run the multi-agent development team."""
    logger.info("initializing_agent_team", sprints=sprints, model=model)

    # Initialize shared infrastructure
    bus = MessageBus()
    state = ProjectState()

    # Create all agents
    agents = create_agents(bus, state, model)
    logger.info("agents_created", count=len(agents))

    # Create orchestrator
    orchestrator = Orchestrator(
        message_bus=bus,
        project_state=state,
        config=OrchestratorState(
            max_sprints=sprints,
            stories_per_sprint=5,
        ),
    )

    # Register agents
    for agent in agents:
        orchestrator.register_agent(agent)

    logger.info("orchestrator_ready", agents_registered=len(agents))

    # Run sprint cycles
    results = await orchestrator.run(max_sprints=sprints)

    # Print results
    logger.info("all_sprints_complete", total_sprints=len(results))
    print("\n" + "=" * 60)
    print("DEVELOPMENT TEAM RESULTS")
    print("=" * 60)

    for sprint_result in results:
        sprint_num = sprint_result.get("sprint", "?")
        print(f"\n--- Sprint {sprint_num} ---")
        for phase_name, phase_result in sprint_result.get("phases", {}).items():
            print(f"  {phase_name}: {json.dumps(phase_result, indent=4, default=str)}")

    # Print final metrics
    metrics = state.get_metrics()
    print("\n" + "=" * 60)
    print("FINAL PROJECT METRICS")
    print("=" * 60)
    for key, value in metrics.items():
        print(f"  {key}: {value}")

    # Generate evolution report from monitor
    monitor_agents = [a for a in agents if a.config.team == "monitor"]
    if monitor_agents:
        report = await monitor_agents[0].generate_evolution_report()
        print("\n" + "=" * 60)
        print("EVOLUTION REPORT")
        print("=" * 60)
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the multi-agent development team")
    parser.add_argument("--sprints", type=int, default=3, help="Number of sprints to run")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="LLM model to use")
    args = parser.parse_args()

    asyncio.run(main(sprints=args.sprints, model=args.model))
