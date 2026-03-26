"""Product Manager agent for the multi-agent chatbot eval platform.

Owns the product backlog: generates stories from requirements, triages bugs,
evaluates feature requests, and drives sprint planning.  All heavy thinking
is delegated to the LLM via the ``call_llm`` helper inherited from
``BaseAgent``.
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import (
    AcceptanceCriteria,
    BugReport,
    FeatureRequest,
    Priority,
    ProjectState,
    Story,
    StoryStatus,
    TaskType,
)

from .backlog import BacklogManager
from .prompts import BUG_TRIAGE_PROMPT, FEATURE_PRIORITIZATION_PROMPT, SPRINT_PLANNING_PROMPT
from .story_generator import StoryGenerator, _parse_json

logger = structlog.get_logger()

_PRIORITY_MAP: dict[str, Priority] = {
    "critical": Priority.CRITICAL,
    "high": Priority.HIGH,
    "medium": Priority.MEDIUM,
    "low": Priority.LOW,
}


class PMAgent(BaseAgent):
    """Product Manager agent.

    Capabilities:
    - Generate user stories from high-level requirements.
    - Triage incoming bug reports and convert them to fix stories.
    - Evaluate feature requests and prioritise them.
    - Plan sprints by selecting stories that fit capacity.
    - Generate the initial project backlog.
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
        sprint_capacity: int = 30,
    ) -> None:
        super().__init__(config, message_bus, project_state)

        # Compose helpers ------------------------------------------------
        self._story_gen = StoryGenerator(
            llm_caller=self._llm_bridge,
            created_by=self.agent_id,
        )
        self._backlog = BacklogManager(capacity=sprint_capacity)

        # Seed velocity history from any previously completed sprints.
        if self.state.completed_sprints:
            self._backlog.record_velocity_from_history(self.state.completed_sprints)

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Own the product backlog for the chatbot evaluation platform.\n"
            "- Generate detailed user stories from high-level requirements.\n"
            "- Triage bugs reported by QA and create fix stories.\n"
            "- Evaluate and prioritise feature requests.\n"
            "- Plan sprints: select stories that fit capacity and team velocity.\n"
            "- Communicate priorities and sprint plans to the engineering team.\n"
            "- Track delivery metrics and adjust plans accordingly."
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Route an incoming message to the appropriate handler."""
        handlers = {
            MessageType.BUG_REPORT: self._handle_bug_report,
            MessageType.FEATURE_REQUEST: self._handle_feature_request,
            MessageType.COMPLETION: self._handle_completion,
            MessageType.QUERY: self._handle_query,
            MessageType.STATUS_UPDATE: self._handle_status_update,
        }

        handler = handlers.get(message.message_type)
        if handler is None:
            logger.debug(
                "pm_unhandled_message_type",
                message_type=message.message_type.value,
                from_agent=message.from_agent,
            )
            return []

        try:
            return await handler(message)
        except Exception:
            logger.exception(
                "pm_message_handler_error",
                message_type=message.message_type.value,
                message_id=message.id,
            )
            return []

    async def plan_work(self) -> list[dict[str, Any]]:
        """Decide what the PM agent should do this turn.

        Checks for conditions that require action and returns a list of
        task dicts to be executed by ``execute_task``.
        """
        tasks: list[dict[str, Any]] = []

        # 1. If the backlog is empty, generate the initial backlog.
        if not self.state.stories:
            tasks.append({"type": "generate_initial_backlog"})
            return tasks

        # 2. If the current sprint has no stories, plan one.
        if not self.state.current_sprint.stories:
            tasks.append({"type": "plan_sprint"})

        # 3. If there are un-triaged bugs, triage them.
        untriaged = [
            b for b in self.state.bugs.values()
            if b.status == StoryStatus.BACKLOG and not b.assigned_to
        ]
        for bug in untriaged:
            tasks.append({"type": "triage_bug", "bug_id": bug.id})

        # 4. If there are un-converted feature requests, evaluate them.
        pending_features = [
            fr for fr in self.state.feature_requests.values()
            if fr.converted_to_story is None
        ]
        for fr in pending_features:
            tasks.append({"type": "evaluate_feature", "feature_id": fr.id})

        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a planned task and return the result."""
        task_type = task.get("type", "")
        dispatch = {
            "generate_initial_backlog": self._exec_generate_initial_backlog,
            "plan_sprint": self._exec_plan_sprint,
            "triage_bug": self._exec_triage_bug,
            "evaluate_feature": self._exec_evaluate_feature,
            "generate_story": self._exec_generate_story,
        }

        executor = dispatch.get(task_type)
        if executor is None:
            logger.warning("pm_unknown_task_type", task_type=task_type)
            return {"status": "skipped", "reason": f"unknown task type: {task_type}"}

        try:
            return await executor(task)
        except Exception:
            logger.exception("pm_task_execution_error", task_type=task_type)
            return {"status": "error", "task_type": task_type}

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_bug_report(self, message: Message) -> list[Message]:
        """Handle an incoming bug report from QA."""
        payload = message.payload
        bug = BugReport(
            title=payload.get("title", "Untitled Bug"),
            description=payload.get("description", ""),
            severity=payload.get("severity", "major"),
            steps_to_reproduce=payload.get("steps_to_reproduce", []),
            expected_behavior=payload.get("expected_behavior", ""),
            actual_behavior=payload.get("actual_behavior", ""),
            reported_by=message.from_agent,
            related_story=payload.get("related_story"),
            environment=payload.get("environment", ""),
            logs=payload.get("logs", ""),
        )
        bug_id = self.state.add_bug(bug)

        logger.info("pm_bug_received", bug_id=bug_id, severity=bug.severity)

        # Acknowledge receipt.
        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.RESPONSE,
                subject=f"Bug {bug_id} received and queued for triage",
                payload={"bug_id": bug_id},
                reply_to=message.id,
            )
        ]

    async def _handle_feature_request(self, message: Message) -> list[Message]:
        """Handle a feature request from any agent or external input."""
        payload = message.payload
        fr = FeatureRequest(
            title=payload.get("title", "Untitled Feature"),
            description=payload.get("description", ""),
            rationale=payload.get("rationale", ""),
            requested_by=message.from_agent,
        )
        fr_id = self.state.add_feature_request(fr)

        logger.info("pm_feature_request_received", feature_id=fr_id)

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.RESPONSE,
                subject=f"Feature request {fr_id} received",
                payload={"feature_id": fr_id},
                reply_to=message.id,
            )
        ]

    async def _handle_completion(self, message: Message) -> list[Message]:
        """Handle a story/task completion notification."""
        story_id = message.payload.get("story_id")
        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.DONE)
            logger.info("pm_story_completed", story_id=story_id)
        return []

    async def _handle_query(self, message: Message) -> list[Message]:
        """Respond to queries about backlog, sprint state, etc."""
        query = message.payload.get("query", "")
        response_payload: dict[str, Any]

        if query == "backlog":
            backlog = self.state.get_backlog()
            response_payload = {
                "stories": [s.model_dump(mode="json") for s in backlog],
            }
        elif query == "sprint":
            sprint_stories = self.state.get_sprint_stories()
            response_payload = {
                "sprint": self.state.current_sprint.model_dump(mode="json"),
                "stories": [s.model_dump(mode="json") for s in sprint_stories],
            }
        elif query == "metrics":
            response_payload = {
                "project": self.state.get_metrics(),
                "backlog": self._backlog.get_metrics(),
            }
        else:
            response_payload = {"error": f"Unknown query: {query}"}

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.RESPONSE,
                subject=f"Re: {message.subject}",
                payload=response_payload,
                reply_to=message.id,
            )
        ]

    async def _handle_status_update(self, message: Message) -> list[Message]:
        """Handle status updates (e.g. story moved to in_progress)."""
        story_id = message.payload.get("story_id")
        new_status = message.payload.get("status")
        if story_id and new_status:
            try:
                status = StoryStatus(new_status)
                self.state.move_story(story_id, status)
                logger.info(
                    "pm_story_status_updated",
                    story_id=story_id,
                    new_status=new_status,
                )
            except ValueError:
                logger.warning("pm_invalid_status", status=new_status)
        return []

    # ------------------------------------------------------------------
    # Task executors
    # ------------------------------------------------------------------

    async def _exec_generate_initial_backlog(
        self, _task: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate and register the initial project backlog."""
        stories = await self._story_gen.generate_initial_backlog(story_count=20)

        story_ids: list[str] = []
        for story in stories:
            sid = self.state.add_story(story)
            story_ids.append(sid)

        # Broadcast that the backlog is ready.
        await self.broadcast(
            message_type=MessageType.STATUS_UPDATE,
            subject="Initial backlog generated",
            payload={"story_ids": story_ids, "count": len(story_ids)},
        )

        logger.info("pm_initial_backlog_created", count=len(story_ids))
        return {"status": "ok", "stories_created": len(story_ids), "story_ids": story_ids}

    async def _exec_plan_sprint(self, _task: dict[str, Any]) -> dict[str, Any]:
        """Run LLM-assisted sprint planning and register results."""
        backlog = self.state.get_backlog()
        open_bugs = self.state.get_open_bugs()

        # Re-prioritize considering open bugs.
        if open_bugs:
            backlog = self._backlog.reprioritize_for_bugs(backlog, open_bugs)

        if not backlog:
            return {"status": "skipped", "reason": "empty backlog"}

        # Get algorithmic suggestion first.
        plan = self._backlog.suggest_sprint_scope(backlog)

        # Build summaries for the LLM prompt.
        backlog_summary = "\n".join(
            f"  - [{s.id}] {s.title} (P:{s.priority.value}, {s.story_points}pt, "
            f"tags:{','.join(s.tags)})"
            for s in backlog[:30]  # limit to keep prompt manageable
        )
        bugs_summary = "\n".join(
            f"  - [{b.id}] {b.title} (severity:{b.severity})"
            for b in open_bugs[:10]
        ) or "  None"
        completed_summary = "\n".join(
            f"  - [{sid}] {self.state.stories[sid].title}"
            for sid in self.state.current_sprint.completed_stories
            if sid in self.state.stories
        ) or "  None"

        prompt = SPRINT_PLANNING_PROMPT.format(
            capacity=plan.capacity,
            velocity=round(self._backlog.get_average_velocity(), 1),
            sprint_number=self.state.current_sprint.number,
            backlog_summary=backlog_summary or "  (empty)",
            bugs_summary=bugs_summary,
            completed_summary=completed_summary,
        )

        raw = await self.call_llm(
            [{"role": "user", "content": prompt}],
            json_mode=True,
        )

        data = _parse_json(raw)

        # Register the sprint.
        selected_ids: list[str] = data.get("selected_story_ids", [])
        valid_ids = [sid for sid in selected_ids if sid in self.state.stories]

        for sid in valid_ids:
            self.state.move_story(sid, StoryStatus.READY)
            self.state.current_sprint.stories.append(sid)

        sprint_goal = data.get("sprint_goal", "")
        risks = data.get("risks", [])

        # Notify the team.
        await self.broadcast(
            message_type=MessageType.SPRINT_EVENT,
            subject=f"Sprint {self.state.current_sprint.number} planned",
            payload={
                "sprint_number": self.state.current_sprint.number,
                "goal": sprint_goal,
                "story_ids": valid_ids,
                "total_points": data.get("total_points", 0),
                "risks": risks,
            },
        )

        logger.info(
            "pm_sprint_planned",
            sprint=self.state.current_sprint.number,
            stories=len(valid_ids),
            goal=sprint_goal,
        )
        return {
            "status": "ok",
            "sprint_number": self.state.current_sprint.number,
            "goal": sprint_goal,
            "stories_planned": len(valid_ids),
            "story_ids": valid_ids,
        }

    async def _exec_triage_bug(self, task: dict[str, Any]) -> dict[str, Any]:
        """Triage a bug and create a fix story."""
        bug_id = task.get("bug_id", "")
        bug = self.state.bugs.get(bug_id)
        if bug is None:
            return {"status": "skipped", "reason": f"bug {bug_id} not found"}

        prompt = BUG_TRIAGE_PROMPT.format(
            title=bug.title,
            description=bug.description,
            severity=bug.severity.value if hasattr(bug.severity, "value") else bug.severity,
            steps_to_reproduce="\n".join(f"  {i+1}. {s}" for i, s in enumerate(bug.steps_to_reproduce)) or "N/A",
            expected_behavior=bug.expected_behavior or "N/A",
            actual_behavior=bug.actual_behavior or "N/A",
            environment=bug.environment or "N/A",
            related_story=bug.related_story or "N/A",
        )

        raw = await self.call_llm(
            [{"role": "user", "content": prompt}],
            json_mode=True,
        )

        data = _parse_json(raw)

        raw_priority = str(data.get("priority", "high")).lower()
        priority = _PRIORITY_MAP.get(raw_priority, Priority.HIGH)
        raw_points = data.get("story_points", 3)
        story_points = _clamp_fibonacci(raw_points)

        fix_story = Story(
            title=str(data.get("fix_story_title", f"Fix: {bug.title}")),
            description=str(data.get("fix_story_description", "")),
            task_type=TaskType.BUG,
            priority=priority,
            acceptance_criteria=[
                AcceptanceCriteria(description=str(ac))
                for ac in data.get("acceptance_criteria", [])
                if ac
            ],
            story_points=story_points,
            tags=[str(t) for t in data.get("tags", ["bug-fix"])],
            created_by=self.agent_id,
            depends_on=[bug.related_story] if bug.related_story else [],
        )

        story_id = self.state.add_story(fix_story)
        bug.assigned_to = self.agent_id
        bug.status = StoryStatus.READY

        # Notify engineering.
        await self.send_message(
            to_team="engineering",
            message_type=MessageType.STORY,
            subject=f"Bug fix story created: {fix_story.title}",
            payload={
                "story_id": story_id,
                "bug_id": bug_id,
                "priority": priority.value,
                "root_cause_hypothesis": data.get("root_cause_hypothesis", ""),
                "impact_assessment": data.get("impact_assessment", ""),
            },
            priority="high",
        )

        logger.info(
            "pm_bug_triaged",
            bug_id=bug_id,
            fix_story_id=story_id,
            priority=priority.value,
        )
        return {
            "status": "ok",
            "bug_id": bug_id,
            "fix_story_id": story_id,
            "priority": priority.value,
        }

    async def _exec_evaluate_feature(self, task: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a feature request and optionally convert to a story."""
        feature_id = task.get("feature_id", "")
        fr = self.state.feature_requests.get(feature_id)
        if fr is None:
            return {"status": "skipped", "reason": f"feature {feature_id} not found"}

        # Gather context for the prompt.
        open_stories = [
            s for s in self.state.stories.values()
            if s.status.value not in ("done",)
        ]
        backlog_areas = sorted({
            tag for s in self.state.stories.values() for tag in s.tags
        })
        sprint_stories = self.state.get_sprint_stories()
        sprint_goal = (
            ", ".join(s.title for s in sprint_stories[:3])
            if sprint_stories
            else "No active sprint"
        )

        prompt = FEATURE_PRIORITIZATION_PROMPT.format(
            title=fr.title,
            description=fr.description,
            rationale=fr.rationale or "N/A",
            requested_by=fr.requested_by or "N/A",
            open_story_count=len(open_stories),
            sprint_goal=sprint_goal,
            backlog_areas=", ".join(backlog_areas) or "None",
        )

        raw = await self.call_llm(
            [{"role": "user", "content": prompt}],
            json_mode=True,
        )

        data = _parse_json(raw)

        raw_priority = str(data.get("recommended_priority", "medium")).lower()
        priority = _PRIORITY_MAP.get(raw_priority, Priority.MEDIUM)
        schedule = data.get("schedule_recommendation", "later")

        # Create a story for the feature.
        raw_points = data.get("story_points", 3)
        story_points = _clamp_fibonacci(raw_points)

        story = Story(
            title=str(data.get("story_title", fr.title)),
            description=str(data.get("story_description", fr.description)),
            task_type=TaskType.FEATURE_REQUEST,
            priority=priority,
            acceptance_criteria=[
                AcceptanceCriteria(description=str(ac))
                for ac in data.get("acceptance_criteria", [])
                if ac
            ],
            story_points=story_points,
            tags=[str(t) for t in data.get("tags", [])],
            created_by=self.agent_id,
        )

        story_id = self.state.add_story(story)
        fr.converted_to_story = story_id
        fr.priority = priority

        # Notify the requester.
        await self.send_message(
            to_agent=fr.requested_by if fr.requested_by else None,
            message_type=MessageType.RESPONSE,
            subject=f"Feature {feature_id} evaluated",
            payload={
                "feature_id": feature_id,
                "story_id": story_id,
                "priority": priority.value,
                "schedule": schedule,
                "reasoning": data.get("reasoning", ""),
            },
        )

        logger.info(
            "pm_feature_evaluated",
            feature_id=feature_id,
            story_id=story_id,
            priority=priority.value,
            schedule=schedule,
        )
        return {
            "status": "ok",
            "feature_id": feature_id,
            "story_id": story_id,
            "priority": priority.value,
            "schedule": schedule,
        }

    async def _exec_generate_story(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a single story from a requirement."""
        requirement = task.get("requirement", "")
        area = task.get("area", "eval_engine")

        if not requirement:
            return {"status": "skipped", "reason": "no requirement provided"}

        story = await self._story_gen.generate_story(requirement, area)
        story_id = self.state.add_story(story)

        logger.info("pm_story_generated", story_id=story_id, area=area)
        return {"status": "ok", "story_id": story_id, "title": story.title}

    # ------------------------------------------------------------------
    # LLM bridge for StoryGenerator
    # ------------------------------------------------------------------

    async def _llm_bridge(
        self,
        messages: list[dict[str, str]],
        json_mode: bool,
    ) -> str:
        """Adapter between StoryGenerator's expected signature and BaseAgent.call_llm."""
        return await self.call_llm(messages, json_mode=json_mode)


# ------------------------------------------------------------------
# Module-level helpers (duplicated from story_generator to keep agent
# self-contained; could also re-export from there).
# ------------------------------------------------------------------

_FIBONACCI = (1, 2, 3, 5, 8, 13)


def _clamp_fibonacci(value: Any) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 3
    return min(_FIBONACCI, key=lambda f: abs(f - v))
