"""Central orchestrator for the multi-agent development team.

Manages sprint cycles, coordinates agent teams, routes work,
and drives the build-test-feedback loop inspired by DeerFlow's
hierarchical delegation and Stripe Minions' deterministic interleaving.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from agents.base_agent import AgentConfig, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import (
    BugReport,
    FeatureRequest,
    Priority,
    ProjectState,
    Story,
    StoryStatus,
    TaskType,
)

logger = structlog.get_logger()


class SprintPhase(str, Enum):
    PLANNING = "planning"
    DEVELOPMENT = "development"
    REVIEW = "review"
    QA = "qa"
    RETROSPECTIVE = "retrospective"


class OrchestratorState(BaseModel):
    phase: SprintPhase = SprintPhase.PLANNING
    agents_registered: dict[str, str] = Field(default_factory=dict)  # agent_id -> team
    phase_results: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    max_sprints: int = 10
    stories_per_sprint: int = 5


class Orchestrator:
    """Central coordinator for the multi-agent development team.

    Drives the sprint cycle:
    1. PLANNING: PM generates stories, orchestrator assigns to teams
    2. DEVELOPMENT: Engineering + Research teams build features
    3. REVIEW: Cross-team review of completed work
    4. QA: QA team tests features, reports bugs
    5. RETROSPECTIVE: Collect metrics, feed bugs/requests back to PM

    Inspired by:
    - DeerFlow: Hierarchical delegation with isolated agent contexts
    - Stripe Minions: Deterministic steps interleaved with agent creativity
    - Autoresearch: Constrained scope with clear evaluation metrics
    """

    def __init__(
        self,
        message_bus: MessageBus,
        project_state: ProjectState,
        config: OrchestratorState | None = None,
    ) -> None:
        self.bus = message_bus
        self.state = project_state
        self.config = config or OrchestratorState()
        self.agents: dict[str, BaseAgent] = {}
        self._running = False

        # Register orchestrator on the bus
        self.bus.register_agent("orchestrator", team="orchestrator")

    def register_agent(self, agent: BaseAgent) -> None:
        self.agents[agent.agent_id] = agent
        self.config.agents_registered[agent.agent_id] = agent.config.team
        logger.info(
            "orchestrator_agent_registered",
            agent_id=agent.agent_id,
            team=agent.config.team,
            role=agent.config.role,
        )

    def get_team(self, team_name: str) -> list[BaseAgent]:
        return [
            agent for agent in self.agents.values()
            if agent.config.team == team_name
        ]

    async def run_sprint(self) -> dict[str, Any]:
        """Execute a full sprint cycle."""
        sprint_num = self.state.current_sprint.number
        logger.info("sprint_started", sprint=sprint_num)

        results: dict[str, Any] = {"sprint": sprint_num, "phases": {}}

        # Phase 1: Planning
        self.config.phase = SprintPhase.PLANNING
        await self._broadcast_phase(SprintPhase.PLANNING)
        planning_results = await self._run_planning_phase()
        results["phases"]["planning"] = planning_results

        # Phase 2: Development
        self.config.phase = SprintPhase.DEVELOPMENT
        await self._broadcast_phase(SprintPhase.DEVELOPMENT)
        dev_results = await self._run_development_phase()
        results["phases"]["development"] = dev_results

        # Phase 3: Review
        self.config.phase = SprintPhase.REVIEW
        await self._broadcast_phase(SprintPhase.REVIEW)
        review_results = await self._run_review_phase()
        results["phases"]["review"] = review_results

        # Phase 4: QA
        self.config.phase = SprintPhase.QA
        await self._broadcast_phase(SprintPhase.QA)
        qa_results = await self._run_qa_phase()
        results["phases"]["qa"] = qa_results

        # Phase 5: Retrospective
        self.config.phase = SprintPhase.RETROSPECTIVE
        await self._broadcast_phase(SprintPhase.RETROSPECTIVE)
        retro_results = await self._run_retrospective()
        results["phases"]["retrospective"] = retro_results

        # Start new sprint
        self.state.start_new_sprint()
        logger.info("sprint_completed", sprint=sprint_num, results=results)

        return results

    async def _broadcast_phase(self, phase: SprintPhase) -> None:
        await self.bus.send(Message(
            from_agent="orchestrator",
            message_type=MessageType.SPRINT_EVENT,
            subject=f"Sprint phase: {phase.value}",
            payload={"phase": phase.value, "sprint": self.state.current_sprint.number},
        ))

    async def _run_planning_phase(self) -> dict[str, Any]:
        """PM generates stories and orchestrator assigns them."""
        pm_agents = self.get_team("pm")
        if not pm_agents:
            logger.warning("no_pm_agent_registered")
            return {"error": "No PM agent registered"}

        pm = pm_agents[0]

        # Ask PM to plan the sprint
        await self.bus.send(Message(
            from_agent="orchestrator",
            to_agent=pm.agent_id,
            message_type=MessageType.SPRINT_EVENT,
            subject="Plan sprint stories",
            payload={
                "action": "plan_sprint",
                "sprint": self.state.current_sprint.number,
                "max_stories": self.config.stories_per_sprint,
                "open_bugs": [b.model_dump() for b in self.state.get_open_bugs()],
                "feature_requests": [
                    fr.model_dump()
                    for fr in self.state.feature_requests.values()
                    if fr.converted_to_story is None
                ],
                "project_metrics": self.state.get_metrics(),
            },
        ))

        # Let PM run a turn to generate stories
        await pm.run_turn()

        # Assign stories to teams
        stories = self.state.get_backlog()
        assigned = 0
        for story in stories[: self.config.stories_per_sprint]:
            team = self._determine_team(story)
            agent = self._select_agent(team)
            if agent:
                self.state.assign_story(story.id, agent.agent_id, team)
                self.state.move_story(story.id, StoryStatus.READY)
                self.state.current_sprint.stories.append(story.id)
                assigned += 1

                await self.bus.send(Message(
                    from_agent="orchestrator",
                    to_agent=agent.agent_id,
                    message_type=MessageType.TASK,
                    subject=f"Assigned: {story.title}",
                    payload={"story": story.model_dump(), "action": "implement"},
                ))

        return {"stories_planned": len(stories), "stories_assigned": assigned}

    async def _run_development_phase(self) -> dict[str, Any]:
        """Engineering and Research teams build features."""
        dev_teams = ["engineering", "research"]
        dev_agents = [a for a in self.agents.values() if a.config.team in dev_teams]

        if not dev_agents:
            return {"error": "No development agents registered"}

        # Run all dev agents concurrently (DeerFlow-style parallel execution)
        tasks = [agent.run_turn() for agent in dev_agents]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Check completion
        sprint_stories = self.state.get_sprint_stories()
        completed = [s for s in sprint_stories if s.status == StoryStatus.DONE]
        in_progress = [s for s in sprint_stories if s.status == StoryStatus.IN_PROGRESS]

        return {
            "agents_active": len(dev_agents),
            "stories_completed": len(completed),
            "stories_in_progress": len(in_progress),
        }

    async def _run_review_phase(self) -> dict[str, Any]:
        """Cross-team review of completed work."""
        sprint_stories = self.state.get_sprint_stories()
        review_count = 0

        for story in sprint_stories:
            if story.status in (StoryStatus.DONE, StoryStatus.IN_REVIEW):
                self.state.move_story(story.id, StoryStatus.IN_QA)
                review_count += 1

        return {"stories_reviewed": review_count}

    async def _run_qa_phase(self) -> dict[str, Any]:
        """QA team tests completed features."""
        qa_agents = self.get_team("qa")
        if not qa_agents:
            return {"error": "No QA agents registered"}

        # Send stories to QA
        sprint_stories = self.state.get_sprint_stories()
        qa_stories = [s for s in sprint_stories if s.status == StoryStatus.IN_QA]

        for story in qa_stories:
            for qa in qa_agents:
                await self.bus.send(Message(
                    from_agent="orchestrator",
                    to_agent=qa.agent_id,
                    message_type=MessageType.TASK,
                    subject=f"Test: {story.title}",
                    payload={"story": story.model_dump(), "action": "test"},
                ))

        # Run QA agents
        tasks = [agent.run_turn() for agent in qa_agents]
        await asyncio.gather(*tasks, return_exceptions=True)

        bugs_found = len([
            b for b in self.state.bugs.values()
            if b.status == StoryStatus.BACKLOG
        ])

        return {"stories_tested": len(qa_stories), "bugs_found": bugs_found}

    async def _run_retrospective(self) -> dict[str, Any]:
        """Collect metrics and prepare for next sprint."""
        metrics = self.state.get_metrics()

        # Feed bugs and feature requests back to PM
        open_bugs = self.state.get_open_bugs()
        if open_bugs:
            pm_agents = self.get_team("pm")
            if pm_agents:
                await self.bus.send(Message(
                    from_agent="orchestrator",
                    to_agent=pm_agents[0].agent_id,
                    message_type=MessageType.BUG_REPORT,
                    subject=f"Sprint {self.state.current_sprint.number} bugs",
                    payload={
                        "bugs": [b.model_dump() for b in open_bugs],
                        "action": "triage_and_create_stories",
                    },
                ))

        # Notify monitor agent
        monitor_agents = self.get_team("monitor")
        if monitor_agents:
            await self.bus.send(Message(
                from_agent="orchestrator",
                to_agent=monitor_agents[0].agent_id,
                message_type=MessageType.MONITOR_UPDATE,
                subject=f"Sprint {self.state.current_sprint.number} complete",
                payload={"metrics": metrics, "action": "analyze_and_update"},
            ))

        return {"metrics": metrics}

    def _determine_team(self, story: Story) -> str:
        """Determine which team should handle a story based on tags and type."""
        tag_team_map = {
            "backend": "engineering",
            "frontend": "engineering",
            "api": "engineering",
            "database": "engineering",
            "infra": "engineering",
            "docker": "engineering",
            "eval": "research",
            "metrics": "research",
            "ml": "research",
            "llm": "research",
            "testing": "qa",
            "security": "qa",
        }

        for tag in story.tags:
            tag_lower = tag.lower()
            if tag_lower in tag_team_map:
                return tag_team_map[tag_lower]

        if story.task_type == TaskType.RESEARCH:
            return "research"
        if story.task_type == TaskType.BUG:
            return "engineering"

        return "engineering"  # default

    def _select_agent(self, team: str) -> BaseAgent | None:
        """Select the best agent from a team for assignment."""
        team_agents = self.get_team(team)
        if not team_agents:
            # Fallback to any available agent
            return next(iter(self.agents.values()), None)

        # Simple load balancing: assign to agent with fewest active stories
        def agent_load(agent: BaseAgent) -> int:
            return len([
                s for s in self.state.stories.values()
                if s.assigned_to == agent.agent_id
                and s.status not in (StoryStatus.DONE, StoryStatus.BACKLOG)
            ])

        return min(team_agents, key=agent_load)

    async def run(self, max_sprints: int | None = None) -> list[dict[str, Any]]:
        """Run the full development cycle for multiple sprints."""
        self._running = True
        sprints = max_sprints or self.config.max_sprints
        results = []

        for i in range(sprints):
            if not self._running:
                break
            sprint_result = await self.run_sprint()
            results.append(sprint_result)
            logger.info("sprint_cycle_complete", sprint=i + 1, of=sprints)

        self._running = False
        return results

    def stop(self) -> None:
        self._running = False
        for agent in self.agents.values():
            agent.stop()
