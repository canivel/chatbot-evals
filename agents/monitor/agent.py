"""Monitor Agent - Tracks project evolution and updates other agents.

This agent continuously monitors the project state, identifies patterns,
bottlenecks, and opportunities, then sends recommendations to other agents.
Inspired by DeerFlow's middleware pattern for cross-cutting concerns.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import BugSeverity, ProjectState, StoryStatus

logger = structlog.get_logger()


class MonitorAgent(BaseAgent):
    """Agent that monitors project evolution and updates other agents.

    Responsibilities:
    - Track sprint velocity and identify trends
    - Detect bottlenecks (too many bugs, blocked stories, unbalanced workload)
    - Monitor eval metric coverage gaps
    - Suggest process improvements to PM
    - Alert on quality regressions
    - Update agent configurations based on project evolution
    - Track which platform areas need more attention
    """

    def __init__(
        self,
        message_bus: MessageBus,
        project_state: ProjectState,
        config: AgentConfig | None = None,
    ) -> None:
        if config is None:
            config = AgentConfig(
                agent_id="monitor",
                name="Project Monitor",
                role="Project Evolution Monitor",
                team="monitor",
                system_prompt=(
                    "You monitor the chatbot eval platform project, tracking metrics, "
                    "identifying bottlenecks, and recommending improvements to the team."
                ),
            )
        super().__init__(config, message_bus, project_state)
        self._analysis_history: list[dict[str, Any]] = []

    def _get_responsibilities(self) -> str:
        return """
- Monitor sprint velocity and identify trends (improving/declining)
- Detect bottlenecks: too many bugs, blocked stories, unbalanced workload
- Track eval metric coverage and identify gaps
- Analyze bug patterns to suggest systemic improvements
- Monitor agent performance and suggest configuration changes
- Alert on quality regressions or process breakdowns
- Recommend focus areas for next sprints
- Track overall project health and readiness
"""

    async def process_message(self, message: Message) -> list[Message]:
        responses = []

        if message.message_type == MessageType.MONITOR_UPDATE:
            analysis = await self._analyze_sprint_results(message.payload)
            responses.extend(analysis)

        elif message.message_type == MessageType.SPRINT_EVENT:
            phase = message.payload.get("phase", "")
            if phase == "retrospective":
                health = await self._check_project_health()
                responses.extend(health)

        elif message.message_type == MessageType.BUG_REPORT:
            pattern_alerts = await self._analyze_bug_patterns()
            responses.extend(pattern_alerts)

        return responses

    async def plan_work(self) -> list[dict[str, Any]]:
        tasks = []

        # Check for bottlenecks
        metrics = self.state.get_metrics()
        open_bugs = metrics.get("open_bugs", 0)
        if open_bugs > 5:
            tasks.append({
                "type": "bottleneck_alert",
                "reason": f"High bug count: {open_bugs} open bugs",
            })

        # Check for blocked stories
        blocked = [
            s for s in self.state.stories.values()
            if s.status == StoryStatus.BLOCKED
        ]
        if blocked:
            tasks.append({
                "type": "blocked_alert",
                "stories": [s.id for s in blocked],
            })

        # Check workload balance
        team_loads = self._calculate_team_loads()
        max_load = max(team_loads.values()) if team_loads else 0
        min_load = min(team_loads.values()) if team_loads else 0
        if max_load > 0 and max_load > min_load * 2:
            tasks.append({
                "type": "workload_imbalance",
                "loads": team_loads,
            })

        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_type = task.get("type", "")

        if task_type == "bottleneck_alert":
            return await self._handle_bottleneck_alert(task)
        elif task_type == "blocked_alert":
            return await self._handle_blocked_alert(task)
        elif task_type == "workload_imbalance":
            return await self._handle_workload_imbalance(task)

        return {"status": "unknown_task_type"}

    async def _analyze_sprint_results(self, payload: dict[str, Any]) -> list[Message]:
        """Analyze sprint results and generate recommendations."""
        metrics = payload.get("metrics", {})
        messages = []

        analysis_prompt = f"""Analyze these sprint metrics and provide recommendations:

Metrics:
{json.dumps(metrics, indent=2)}

Previous analyses:
{json.dumps(self._analysis_history[-3:], indent=2) if self._analysis_history else "None yet"}

Provide:
1. Key observations about project health
2. Bottlenecks or risks identified
3. Recommendations for next sprint
4. Any agent configuration changes needed

Format as JSON with keys: observations, bottlenecks, recommendations, config_changes"""

        try:
            response = await self.call_llm(
                [{"role": "user", "content": analysis_prompt}],
                json_mode=True,
            )
            analysis = json.loads(response)
            self._analysis_history.append(analysis)

            # Send recommendations to PM
            if analysis.get("recommendations"):
                messages.append(Message(
                    from_agent=self.agent_id,
                    to_team="pm",
                    message_type=MessageType.MONITOR_UPDATE,
                    subject="Sprint Analysis & Recommendations",
                    payload={
                        "analysis": analysis,
                        "action": "incorporate_recommendations",
                    },
                ))

            # Send config changes to orchestrator
            if analysis.get("config_changes"):
                messages.append(Message(
                    from_agent=self.agent_id,
                    to_agent="orchestrator",
                    message_type=MessageType.MONITOR_UPDATE,
                    subject="Agent Configuration Updates",
                    payload={
                        "config_changes": analysis["config_changes"],
                        "action": "update_agent_configs",
                    },
                ))

            self.state.log_activity(self.agent_id, "sprint_analysis", analysis)

        except Exception as e:
            logger.error("sprint_analysis_failed", error=str(e))

        return messages

    async def _check_project_health(self) -> list[Message]:
        """Comprehensive project health check."""
        messages = []
        metrics = self.state.get_metrics()
        issues = []

        # Velocity check
        avg_velocity = metrics.get("avg_velocity", 0)
        if avg_velocity > 0:
            current_completed = metrics.get("sprint_completed", 0)
            if current_completed < avg_velocity * 0.5:
                issues.append({
                    "type": "velocity_drop",
                    "message": f"Sprint velocity dropped significantly: {current_completed} vs avg {avg_velocity:.1f}",
                    "severity": "high",
                })

        # Bug ratio check
        total = metrics.get("total_stories", 1)
        bugs = metrics.get("open_bugs", 0)
        if total > 0 and bugs / total > 0.3:
            issues.append({
                "type": "high_bug_ratio",
                "message": f"Bug ratio is high: {bugs}/{total} ({bugs/total:.0%})",
                "severity": "critical",
            })

        # Critical bugs check
        critical_bugs = [
            b for b in self.state.bugs.values()
            if b.severity in (BugSeverity.BLOCKER, BugSeverity.CRITICAL)
            and b.status != StoryStatus.DONE
        ]
        if critical_bugs:
            issues.append({
                "type": "critical_bugs",
                "message": f"{len(critical_bugs)} critical/blocker bugs open",
                "severity": "critical",
                "bug_ids": [b.id for b in critical_bugs],
            })

        if issues:
            messages.append(Message(
                from_agent=self.agent_id,
                message_type=MessageType.BROADCAST,
                subject="Project Health Alert",
                payload={"issues": issues, "metrics": metrics},
            ))

        return messages

    async def _analyze_bug_patterns(self) -> list[Message]:
        """Analyze bug patterns to find systemic issues."""
        messages = []
        bugs = list(self.state.bugs.values())

        if len(bugs) < 3:
            return messages

        # Group bugs by related story/area
        story_bug_count: dict[str, int] = {}
        for bug in bugs:
            if bug.related_story:
                story_bug_count[bug.related_story] = story_bug_count.get(bug.related_story, 0) + 1

        # Alert if a story has too many bugs
        problematic_stories = {sid: count for sid, count in story_bug_count.items() if count >= 3}
        if problematic_stories:
            messages.append(Message(
                from_agent=self.agent_id,
                to_team="pm",
                message_type=MessageType.ESCALATION,
                subject="Systemic bug pattern detected",
                payload={
                    "problematic_stories": problematic_stories,
                    "recommendation": "Consider re-architecting these features",
                    "action": "review_and_replan",
                },
            ))

        return messages

    async def _handle_bottleneck_alert(self, task: dict[str, Any]) -> dict[str, Any]:
        """Handle high bug count bottleneck."""
        await self.send_message(
            to_team="pm",
            message_type=MessageType.ESCALATION,
            subject="Bug Bottleneck Alert",
            payload={
                "reason": task["reason"],
                "action": "prioritize_bug_fixes",
                "recommendation": "Dedicate next sprint to bug fixing",
            },
            priority="high",
        )
        return {"status": "alert_sent", "type": "bottleneck"}

    async def _handle_blocked_alert(self, task: dict[str, Any]) -> dict[str, Any]:
        """Handle blocked stories."""
        story_ids = task.get("stories", [])
        await self.send_message(
            to_agent="orchestrator",
            message_type=MessageType.ESCALATION,
            subject=f"{len(story_ids)} stories blocked",
            payload={
                "blocked_stories": story_ids,
                "action": "unblock_stories",
            },
            priority="high",
        )
        return {"status": "alert_sent", "type": "blocked"}

    async def _handle_workload_imbalance(self, task: dict[str, Any]) -> dict[str, Any]:
        """Handle workload imbalance between teams."""
        loads = task.get("loads", {})
        await self.send_message(
            to_agent="orchestrator",
            message_type=MessageType.MONITOR_UPDATE,
            subject="Workload Imbalance Detected",
            payload={
                "team_loads": loads,
                "action": "rebalance_workload",
                "recommendation": "Redistribute stories to balance team loads",
            },
        )
        return {"status": "alert_sent", "type": "workload_imbalance"}

    def _calculate_team_loads(self) -> dict[str, int]:
        """Calculate active story count per team."""
        loads: dict[str, int] = {}
        for story in self.state.stories.values():
            if story.assigned_team and story.status not in (StoryStatus.DONE, StoryStatus.BACKLOG):
                loads[story.assigned_team] = loads.get(story.assigned_team, 0) + 1
        return loads

    async def generate_evolution_report(self) -> dict[str, Any]:
        """Generate a comprehensive project evolution report."""
        metrics = self.state.get_metrics()

        report_prompt = f"""Generate a project evolution report for the Chatbot Evals Platform.

Current Metrics:
{json.dumps(metrics, indent=2)}

Sprint History:
{json.dumps([s.model_dump() for s in self.state.completed_sprints[-5:]], indent=2, default=str)}

Analysis History:
{json.dumps(self._analysis_history[-5:], indent=2)}

Generate a comprehensive report covering:
1. Project progress summary
2. Velocity trends
3. Quality trends (bug rates)
4. Team performance
5. Key risks and mitigations
6. Recommended focus areas
7. Suggested agent/process improvements

Format as JSON."""

        try:
            response = await self.call_llm(
                [{"role": "user", "content": report_prompt}],
                json_mode=True,
            )
            return json.loads(response)
        except Exception as e:
            logger.error("evolution_report_failed", error=str(e))
            return {"error": str(e), "metrics": metrics}
