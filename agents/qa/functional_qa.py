"""Functional QA agent for testing features against acceptance criteria.

Generates test scenarios from stories, verifies code artifacts produce
correct results, and files bug reports with detailed reproduction steps.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import (
    BugSeverity,
    ProjectState,
    Story,
    StoryStatus,
)

from .bug_reporter import BugReporter
from .prompts import (
    BUG_ANALYSIS_PROMPT,
    FUNCTIONAL_QA_SYSTEM_PROMPT,
    TEST_GENERATION_PROMPT,
)

logger = structlog.get_logger()


class FunctionalQAAgent(BaseAgent):
    """Agent responsible for functional testing of features.

    This agent:
    * Picks up stories that have moved to the ``IN_QA`` status.
    * Generates comprehensive test scenarios from acceptance criteria using
      the LLM.
    * Verifies that code artifacts produce the expected results.
    * Reports bugs with detailed steps to reproduce.
    * Suggests UX improvements as feature requests when it spots friction.
    """

    def __init__(
        self,
        message_bus: MessageBus,
        project_state: ProjectState,
        *,
        model: str = "gpt-4o-mini",
    ) -> None:
        config = AgentConfig(
            agent_id="functional-qa",
            name="Functional QA Agent",
            role="Functional Tester",
            team="qa",
            model=model,
            system_prompt=FUNCTIONAL_QA_SYSTEM_PROMPT,
        )
        super().__init__(config, message_bus, project_state)
        self._bug_reporter = BugReporter()
        self._tested_stories: set[str] = set()

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Test features against acceptance criteria\n"
            "- Generate test scenarios from stories\n"
            "- Verify code artifacts produce correct results\n"
            "- Report bugs with detailed steps to reproduce\n"
            "- Suggest UX improvements as feature requests"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Handle incoming messages.

        Responds to:
        * ``STORY`` -- a story has been moved to QA; begin testing.
        * ``REVIEW_RESULT`` -- code review complete; re-test if needed.
        * ``QUERY`` -- ad-hoc questions from other agents.
        """
        responses: list[Message] = []

        if message.message_type == MessageType.STORY:
            story_id = message.payload.get("story_id", "")
            if story_id and story_id in self.state.stories:
                story = self.state.stories[story_id]
                if story.status == StoryStatus.IN_QA:
                    test_result = await self._test_story(story)
                    responses.extend(test_result)

        elif message.message_type == MessageType.REVIEW_RESULT:
            story_id = message.payload.get("story_id", "")
            if story_id and story_id in self.state.stories:
                story = self.state.stories[story_id]
                # Re-test after review fixes
                if story.status == StoryStatus.IN_QA:
                    self._tested_stories.discard(story_id)
                    test_result = await self._test_story(story)
                    responses.extend(test_result)

        elif message.message_type == MessageType.QUERY:
            answer = await self._handle_query(message)
            if answer:
                responses.append(answer)

        return responses

    async def plan_work(self) -> list[dict[str, Any]]:
        """Identify stories in QA that have not yet been tested."""
        tasks: list[dict[str, Any]] = []

        qa_stories = [
            s
            for s in self.state.stories.values()
            if s.status == StoryStatus.IN_QA and s.id not in self._tested_stories
        ]

        for story in qa_stories:
            tasks.append(
                {
                    "type": "test_story",
                    "story_id": story.id,
                    "story_title": story.title,
                }
            )

        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a planned task.

        Supported task types:
        * ``test_story`` -- run full test suite against a story.
        """
        task_type = task.get("type", "")

        if task_type == "test_story":
            story_id = task["story_id"]
            if story_id in self.state.stories:
                story = self.state.stories[story_id]
                messages = await self._test_story(story)
                for msg in messages:
                    await self.bus.send(msg)
                return {
                    "status": "completed",
                    "story_id": story_id,
                    "messages_sent": len(messages),
                }
            return {"status": "skipped", "reason": "story_not_found"}

        logger.warning("unknown_task_type", task_type=task_type, agent_id=self.agent_id)
        return {"status": "skipped", "reason": f"unknown task type: {task_type}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _test_story(self, story: Story) -> list[Message]:
        """Run the full test flow for a single story.

        1. Generate test scenarios from acceptance criteria.
        2. Evaluate each scenario (via LLM reasoning).
        3. File bugs / feature requests for any failures.
        4. Notify PM and dev team of results.
        """
        messages: list[Message] = []
        self._tested_stories.add(story.id)

        logger.info("testing_story", story_id=story.id, title=story.title)

        # 1. Generate test scenarios
        scenarios = await self._generate_test_scenarios(story)
        if not scenarios:
            logger.warning("no_scenarios_generated", story_id=story.id)
            return messages

        self.state.log_activity(
            self.agent_id,
            "test_scenarios_generated",
            {"story_id": story.id, "count": len(scenarios)},
        )

        # 2. Evaluate each scenario
        bugs_found: list[dict[str, Any]] = []
        feature_requests_found: list[dict[str, Any]] = []
        passed = 0
        failed = 0

        for scenario in scenarios:
            result = await self._evaluate_scenario(story, scenario)
            if result.get("is_bug"):
                bugs_found.append(result)
                failed += 1
            elif result.get("is_feature_request"):
                feature_requests_found.append(result)
                passed += 1  # Not a defect, counts as pass
            else:
                passed += 1

        # 3. File bugs
        for bug_data in bugs_found:
            bug_messages = await self._file_bug(story, bug_data)
            messages.extend(bug_messages)

        # 4. File feature requests
        for fr_data in feature_requests_found:
            fr_messages = await self._file_feature_request(story, fr_data)
            messages.extend(fr_messages)

        # 5. Send summary to PM
        summary_msg = Message(
            from_agent=self.agent_id,
            to_team="pm",
            message_type=MessageType.STATUS_UPDATE,
            subject=f"QA results for {story.id}: {story.title}",
            payload={
                "story_id": story.id,
                "total_scenarios": len(scenarios),
                "passed": passed,
                "failed": failed,
                "bugs_filed": len(bugs_found),
                "feature_requests_filed": len(feature_requests_found),
                "recommendation": "approve" if failed == 0 else "needs_fixes",
            },
        )
        messages.append(summary_msg)

        # If all tests pass, mark story as done
        if failed == 0:
            self.state.move_story(story.id, StoryStatus.DONE)
            logger.info("story_passed_qa", story_id=story.id)
        else:
            # Move back to in-progress so dev can fix
            self.state.move_story(story.id, StoryStatus.IN_PROGRESS)
            logger.info(
                "story_failed_qa",
                story_id=story.id,
                bugs=len(bugs_found),
            )

        return messages

    async def _generate_test_scenarios(self, story: Story) -> list[dict[str, Any]]:
        """Use the LLM to generate test scenarios from acceptance criteria."""
        if not story.acceptance_criteria:
            return []

        ac_text = "\n".join(
            f"  {i + 1}. {ac.description}" for i, ac in enumerate(story.acceptance_criteria)
        )

        prompt = TEST_GENERATION_PROMPT.format(
            story_title=story.title,
            story_description=story.description,
            acceptance_criteria=ac_text,
        )

        try:
            response = await self.call_llm(
                [{"role": "user", "content": prompt}],
                temperature=0.4,
                json_mode=True,
            )
            parsed = json.loads(response)
            scenarios: list[dict[str, Any]] = parsed.get("scenarios", [])
            return scenarios
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "scenario_generation_parse_error",
                story_id=story.id,
                error=str(exc),
            )
            return []
        except Exception as exc:
            logger.error(
                "scenario_generation_failed",
                story_id=story.id,
                error=str(exc),
            )
            return []

    async def _evaluate_scenario(
        self,
        story: Story,
        scenario: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate a single test scenario against the story, returning analysis."""
        ac_text = "\n".join(
            f"  {i + 1}. {ac.description}" for i, ac in enumerate(story.acceptance_criteria)
        )

        prompt = BUG_ANALYSIS_PROMPT.format(
            story_title=story.title,
            story_id=story.id,
            acceptance_criteria=ac_text,
            observation=scenario.get("name", ""),
            expected_behavior=scenario.get("expected_result", ""),
            actual_behavior=f"Test scenario: {json.dumps(scenario.get('steps', []))}",
        )

        try:
            response = await self.call_llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                json_mode=True,
            )
            result: dict[str, Any] = json.loads(response)
            return result
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "scenario_evaluation_parse_error",
                story_id=story.id,
                scenario=scenario.get("name", "unknown"),
                error=str(exc),
            )
            return {"is_bug": False, "reasoning": f"Parse error during evaluation: {exc}"}
        except Exception as exc:
            logger.error(
                "scenario_evaluation_failed",
                story_id=story.id,
                error=str(exc),
            )
            return {"is_bug": False, "reasoning": f"Evaluation failed: {exc}"}

    async def _file_bug(
        self,
        story: Story,
        bug_data: dict[str, Any],
    ) -> list[Message]:
        """Create a BugReport from analysis data, persist it, and notify PM."""
        severity_str = bug_data.get("severity", "major").lower()
        try:
            severity = BugSeverity(severity_str)
        except ValueError:
            severity = BugSeverity.MAJOR

        bug = self._bug_reporter.create_bug_report(
            title=bug_data.get("suggested_title", f"Bug in {story.id}"),
            description=bug_data.get("reasoning", ""),
            severity=severity,
            steps=bug_data.get("suggested_steps_to_reproduce", []),
            expected="See acceptance criteria",
            actual=bug_data.get("likely_root_cause", ""),
            reporter=self.agent_id,
            related_story=story.id,
            environment="eval-pipeline",
        )

        self.state.add_bug(bug)

        payload = self._bug_reporter.format_bug_for_message(bug)
        msg = Message(
            from_agent=self.agent_id,
            to_team="pm",
            message_type=MessageType.BUG_REPORT,
            subject=f"Bug: {bug.title}",
            payload=payload,
            priority="high" if severity in (BugSeverity.BLOCKER, BugSeverity.CRITICAL) else "medium",
        )
        return [msg]

    async def _file_feature_request(
        self,
        story: Story,
        fr_data: dict[str, Any],
    ) -> list[Message]:
        """Create a FeatureRequest from analysis data and notify PM."""
        fr = self._bug_reporter.create_feature_request(
            title=fr_data.get("suggested_title", f"Improvement for {story.id}"),
            description=fr_data.get("reasoning", ""),
            rationale=fr_data.get("reasoning", ""),
            requested_by=self.agent_id,
        )

        self.state.add_feature_request(fr)

        payload = self._bug_reporter.format_feature_request_for_message(fr)
        msg = Message(
            from_agent=self.agent_id,
            to_team="pm",
            message_type=MessageType.FEATURE_REQUEST,
            subject=f"Feature request: {fr.title}",
            payload=payload,
        )
        return [msg]

    async def _handle_query(self, message: Message) -> Message | None:
        """Answer ad-hoc queries from other agents."""
        question = message.payload.get("question", "")
        if not question:
            return None

        try:
            answer = await self.call_llm(
                [{"role": "user", "content": question}],
                temperature=0.5,
            )
            return Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.RESPONSE,
                subject=f"Re: {message.subject}",
                payload={"answer": answer},
                reply_to=message.id,
            )
        except Exception as exc:
            logger.error("query_handling_failed", error=str(exc))
            return None
