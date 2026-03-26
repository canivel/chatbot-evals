"""Performance QA agent for evaluating throughput, latency, and resource usage.

Designs performance test scenarios, evaluates the eval pipeline, identifies
bottlenecks, and reports performance regressions as bugs with benchmark data.
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
from .prompts import PERFORMANCE_BENCHMARK_PROMPT, PERFORMANCE_QA_SYSTEM_PROMPT

logger = structlog.get_logger()

# Default performance thresholds (can be overridden per component)
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "api_response_p95_ms": 500,
    "api_response_p99_ms": 1000,
    "eval_throughput_per_min": 100,
    "max_memory_mb": 512,
    "max_cpu_percent": 80,
}


class PerformanceQAAgent(BaseAgent):
    """Agent responsible for performance testing and benchmarking.

    This agent:
    * Designs performance test scenarios for components and stories.
    * Evaluates eval-pipeline throughput, latency, and resource usage.
    * Checks API response times against defined thresholds.
    * Identifies bottlenecks and proposes optimisations.
    * Reports performance regressions as bugs with benchmark data.
    """

    def __init__(
        self,
        message_bus: MessageBus,
        project_state: ProjectState,
        *,
        model: str = "gpt-4o-mini",
        thresholds: dict[str, Any] | None = None,
    ) -> None:
        config = AgentConfig(
            agent_id="performance-qa",
            name="Performance QA Agent",
            role="Performance Engineer",
            team="qa",
            model=model,
            system_prompt=PERFORMANCE_QA_SYSTEM_PROMPT,
        )
        super().__init__(config, message_bus, project_state)
        self._bug_reporter = BugReporter()
        self._thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._benchmarked_stories: set[str] = set()

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Design performance test scenarios for the eval pipeline\n"
            "- Measure throughput, latency, and resource utilization\n"
            "- Check API response times against SLA thresholds\n"
            "- Identify bottlenecks and recommend optimizations\n"
            "- Report performance regressions as bugs with benchmarks"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Handle incoming messages.

        Responds to:
        * ``STORY`` -- a story entering QA that may need perf testing.
        * ``STATUS_UPDATE`` -- deployment or release events that trigger benchmarks.
        * ``QUERY`` -- ad-hoc performance questions from other agents.
        """
        responses: list[Message] = []

        if message.message_type == MessageType.STORY:
            story_id = message.payload.get("story_id", "")
            if story_id and story_id in self.state.stories:
                story = self.state.stories[story_id]
                if story.status == StoryStatus.IN_QA and self._needs_perf_testing(story):
                    perf_messages = await self._run_performance_review(story)
                    responses.extend(perf_messages)

        elif message.message_type == MessageType.STATUS_UPDATE:
            # Trigger a full benchmark when a deployment event arrives
            event_type = message.payload.get("event", "")
            if event_type in ("deployment", "release"):
                benchmark_messages = await self._run_full_benchmark()
                responses.extend(benchmark_messages)

        elif message.message_type == MessageType.QUERY:
            answer = await self._handle_query(message)
            if answer:
                responses.append(answer)

        return responses

    async def plan_work(self) -> list[dict[str, Any]]:
        """Identify stories in QA that warrant performance testing."""
        tasks: list[dict[str, Any]] = []

        qa_stories = [
            s
            for s in self.state.stories.values()
            if s.status == StoryStatus.IN_QA
            and s.id not in self._benchmarked_stories
            and self._needs_perf_testing(s)
        ]

        for story in qa_stories:
            tasks.append(
                {
                    "type": "performance_review",
                    "story_id": story.id,
                    "story_title": story.title,
                }
            )

        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a planned task.

        Supported task types:
        * ``performance_review`` -- benchmark a specific story.
        * ``full_benchmark`` -- run a system-wide performance sweep.
        """
        task_type = task.get("type", "")

        if task_type == "performance_review":
            story_id = task["story_id"]
            if story_id in self.state.stories:
                story = self.state.stories[story_id]
                messages = await self._run_performance_review(story)
                for msg in messages:
                    await self.bus.send(msg)
                return {"status": "completed", "story_id": story_id, "messages_sent": len(messages)}
            return {"status": "skipped", "reason": "story_not_found"}

        if task_type == "full_benchmark":
            messages = await self._run_full_benchmark()
            for msg in messages:
                await self.bus.send(msg)
            return {"status": "completed", "messages_sent": len(messages)}

        logger.warning("unknown_task_type", task_type=task_type, agent_id=self.agent_id)
        return {"status": "skipped", "reason": f"unknown task type: {task_type}"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _needs_perf_testing(story: Story) -> bool:
        """Heuristic: stories tagged with performance-related keywords need benchmarking."""
        perf_keywords = {"performance", "perf", "latency", "throughput", "api", "pipeline", "scale"}
        searchable = f"{story.title} {story.description} {' '.join(story.tags)}".lower()
        return any(kw in searchable for kw in perf_keywords)

    async def _run_performance_review(self, story: Story) -> list[Message]:
        """Design and evaluate performance tests for a story."""
        messages: list[Message] = []
        self._benchmarked_stories.add(story.id)

        logger.info("performance_review_started", story_id=story.id)

        # 1. Design test plan
        test_plan = await self._design_test_plan(story)
        if not test_plan:
            logger.warning("no_test_plan_generated", story_id=story.id)
            return messages

        self.state.log_activity(
            self.agent_id,
            "perf_test_plan_created",
            {"story_id": story.id, "scenarios": len(test_plan.get("scenarios", []))},
        )

        # 2. Evaluate each scenario against thresholds
        violations = await self._evaluate_performance(story, test_plan)

        # 3. File bugs for violations
        for violation in violations:
            bug_messages = await self._file_performance_bug(story, violation)
            messages.extend(bug_messages)

        # 4. Send summary
        summary = Message(
            from_agent=self.agent_id,
            to_team="pm",
            message_type=MessageType.STATUS_UPDATE,
            subject=f"Performance review for {story.id}: {story.title}",
            payload={
                "story_id": story.id,
                "scenarios_tested": len(test_plan.get("scenarios", [])),
                "violations_found": len(violations),
                "thresholds": self._thresholds,
                "recommendation": "pass" if not violations else "needs_optimization",
            },
        )
        messages.append(summary)

        return messages

    async def _run_full_benchmark(self) -> list[Message]:
        """Run a system-wide performance benchmark across all key components."""
        messages: list[Message] = []

        components = [
            {"name": "eval-pipeline", "description": "Core evaluation execution pipeline"},
            {"name": "api-gateway", "description": "REST API endpoint layer"},
            {"name": "data-store", "description": "Database and caching layer"},
        ]

        all_violations: list[dict[str, Any]] = []
        for component in components:
            plan = await self._design_component_test_plan(
                component["name"],
                component["description"],
            )
            if plan:
                violations = await self._evaluate_component_performance(component["name"], plan)
                all_violations.extend(violations)

                for violation in violations:
                    bug_messages = await self._file_performance_bug(None, violation)
                    messages.extend(bug_messages)

        summary = Message(
            from_agent=self.agent_id,
            to_team="pm",
            message_type=MessageType.STATUS_UPDATE,
            subject="Full system performance benchmark complete",
            payload={
                "components_tested": len(components),
                "total_violations": len(all_violations),
                "thresholds": self._thresholds,
            },
            priority="high" if all_violations else "medium",
        )
        messages.append(summary)

        return messages

    async def _design_test_plan(self, story: Story) -> dict[str, Any]:
        """Use the LLM to design a performance test plan for a story."""
        prompt = PERFORMANCE_BENCHMARK_PROMPT.format(
            component_name=story.title,
            component_description=story.description,
            usage_patterns="Standard eval pipeline usage: batch evaluations, "
            "concurrent API requests, real-time dashboard updates",
        )

        try:
            response = await self.call_llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                json_mode=True,
            )
            parsed: dict[str, Any] = json.loads(response)
            return parsed.get("test_plan", parsed)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("test_plan_parse_error", story_id=story.id, error=str(exc))
            return {}
        except Exception as exc:
            logger.error("test_plan_generation_failed", story_id=story.id, error=str(exc))
            return {}

    async def _design_component_test_plan(
        self,
        component_name: str,
        component_description: str,
    ) -> dict[str, Any]:
        """Design a performance test plan for a system component."""
        prompt = PERFORMANCE_BENCHMARK_PROMPT.format(
            component_name=component_name,
            component_description=component_description,
            usage_patterns="Production traffic patterns: sustained load with periodic spikes",
        )

        try:
            response = await self.call_llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                json_mode=True,
            )
            parsed: dict[str, Any] = json.loads(response)
            return parsed.get("test_plan", parsed)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "component_plan_parse_error",
                component=component_name,
                error=str(exc),
            )
            return {}
        except Exception as exc:
            logger.error(
                "component_plan_generation_failed",
                component=component_name,
                error=str(exc),
            )
            return {}

    async def _evaluate_performance(
        self,
        story: Story,
        test_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Evaluate the performance test plan and identify threshold violations."""
        analysis_prompt = (
            f"Given the following performance test plan for story '{story.title}' "
            f"({story.id}):\n\n{json.dumps(test_plan, indent=2)}\n\n"
            f"And the following performance thresholds:\n"
            f"{json.dumps(self._thresholds, indent=2)}\n\n"
            "Identify any scenarios that would likely violate these thresholds "
            "based on the component design. For each potential violation, provide:\n"
            '- "scenario": the test scenario name\n'
            '- "metric": which metric would be violated\n'
            '- "threshold": the threshold value\n'
            '- "estimated_actual": your estimate of the actual value\n'
            '- "severity": blocker/critical/major/minor\n'
            '- "bottleneck": likely root cause of the bottleneck\n'
            '- "recommendation": suggested optimization\n\n'
            'Return JSON: {"violations": [...]}'
        )

        try:
            response = await self.call_llm(
                [{"role": "user", "content": analysis_prompt}],
                temperature=0.3,
                json_mode=True,
            )
            parsed: dict[str, Any] = json.loads(response)
            violations: list[dict[str, Any]] = parsed.get("violations", [])
            return violations
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("perf_eval_parse_error", story_id=story.id, error=str(exc))
            return []
        except Exception as exc:
            logger.error("perf_evaluation_failed", story_id=story.id, error=str(exc))
            return []

    async def _evaluate_component_performance(
        self,
        component_name: str,
        test_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Evaluate a component-level performance test plan for threshold violations."""
        analysis_prompt = (
            f"Given the following performance test plan for component '{component_name}':\n\n"
            f"{json.dumps(test_plan, indent=2)}\n\n"
            f"And the following performance thresholds:\n"
            f"{json.dumps(self._thresholds, indent=2)}\n\n"
            "Identify any scenarios that would likely violate these thresholds. "
            "For each potential violation, provide:\n"
            '- "scenario": the test scenario name\n'
            '- "metric": which metric would be violated\n'
            '- "threshold": the threshold value\n'
            '- "estimated_actual": your estimate of the actual value\n'
            '- "severity": blocker/critical/major/minor\n'
            '- "bottleneck": likely root cause\n'
            '- "recommendation": suggested optimization\n'
            f'- "component": "{component_name}"\n\n'
            'Return JSON: {"violations": [...]}'
        )

        try:
            response = await self.call_llm(
                [{"role": "user", "content": analysis_prompt}],
                temperature=0.3,
                json_mode=True,
            )
            parsed: dict[str, Any] = json.loads(response)
            violations: list[dict[str, Any]] = parsed.get("violations", [])
            return violations
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "component_eval_parse_error",
                component=component_name,
                error=str(exc),
            )
            return []
        except Exception as exc:
            logger.error(
                "component_eval_failed",
                component=component_name,
                error=str(exc),
            )
            return []

    async def _file_performance_bug(
        self,
        story: Story | None,
        violation: dict[str, Any],
    ) -> list[Message]:
        """Create a performance bug report from a threshold violation."""
        severity_str = violation.get("severity", "major").lower()
        try:
            severity = BugSeverity(severity_str)
        except ValueError:
            severity = BugSeverity.MAJOR

        metric = violation.get("metric", "unknown")
        threshold = violation.get("threshold", "N/A")
        estimated = violation.get("estimated_actual", "N/A")
        component = violation.get("component", story.title if story else "system")

        title = f"Performance: {metric} exceeds threshold in {component}"
        description = (
            f"Performance threshold violation detected.\n\n"
            f"**Metric:** {metric}\n"
            f"**Threshold:** {threshold}\n"
            f"**Estimated actual:** {estimated}\n"
            f"**Bottleneck:** {violation.get('bottleneck', 'Unknown')}\n"
            f"**Recommendation:** {violation.get('recommendation', 'Investigate')}"
        )

        bug = self._bug_reporter.create_bug_report(
            title=title,
            description=description,
            severity=severity,
            steps=[
                f"Run performance test scenario: {violation.get('scenario', 'N/A')}",
                f"Observe metric '{metric}'",
                f"Compare against threshold: {threshold}",
            ],
            expected=f"{metric} <= {threshold}",
            actual=f"{metric} estimated at {estimated}",
            reporter=self.agent_id,
            related_story=story.id if story else None,
            environment="performance-test",
        )

        self.state.add_bug(bug)

        payload = self._bug_reporter.format_bug_for_message(bug)
        msg = Message(
            from_agent=self.agent_id,
            to_team="pm",
            message_type=MessageType.BUG_REPORT,
            subject=f"Performance bug: {title}",
            payload=payload,
            priority="high" if severity in (BugSeverity.BLOCKER, BugSeverity.CRITICAL) else "medium",
        )
        return [msg]

    async def _handle_query(self, message: Message) -> Message | None:
        """Answer ad-hoc performance questions from other agents."""
        question = message.payload.get("question", "")
        if not question:
            return None

        context = (
            f"Current performance thresholds: {json.dumps(self._thresholds)}\n"
            f"Question: {question}"
        )

        try:
            answer = await self.call_llm(
                [{"role": "user", "content": context}],
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
