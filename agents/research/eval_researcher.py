"""Eval Researcher agent for the research team.

Specializes in state-of-the-art evaluation metrics for chatbot and LLM
systems. Researches, designs, and produces metric implementations that
conform to the platform's BaseMetric interface.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType
from agents.research.prompts import (
    EVAL_RESEARCH_SYSTEM_PROMPT,
    METRIC_DESIGN_PROMPT,
)
from agents.state import (
    ProjectState,
    Story,
    StoryStatus,
    TaskType,
)

logger = structlog.get_logger()

# Metric categories this agent is qualified to research.
_EVAL_METRIC_TAGS = frozenset({
    "eval_engine",
    "metrics",
    "faithfulness",
    "groundedness",
    "hallucination",
    "toxicity",
    "coherence",
    "relevance",
    "answer_correctness",
    "safety",
    "evaluation",
})

# Well-known metric families the agent can propose implementations for.
_KNOWN_METRIC_FAMILIES: dict[str, str] = {
    "faithfulness": (
        "Measures whether the assistant's response is faithful to the "
        "provided context using NLI-based claim decomposition and "
        "entailment verification."
    ),
    "groundedness": (
        "Assesses whether claims in the response can be attributed to "
        "source documents through citation verification."
    ),
    "hallucination": (
        "Detects fabricated facts, unsupported claims, and entity/relation "
        "hallucinations using SelfCheckGPT and knowledge-grounded scoring."
    ),
    "toxicity": (
        "Detects harmful, biased, or inappropriate content using classifier "
        "ensembles and LLM-based safety checks."
    ),
    "coherence": (
        "Evaluates logical flow, consistency, and discourse structure using "
        "entity-graph and topical coherence analysis."
    ),
    "relevance": (
        "Measures how well responses address user queries via semantic "
        "similarity and information completeness scoring."
    ),
    "answer_correctness": (
        "Compares responses against ground-truth answers using F1, "
        "BERTScore, and semantic equivalence."
    ),
}


def create_eval_researcher(
    message_bus: MessageBus,
    project_state: ProjectState,
    *,
    agent_id: str = "eval-researcher",
    model: str = "gpt-4o-mini",
) -> EvalResearcher:
    """Factory function to create a fully-configured EvalResearcher agent."""
    config = AgentConfig(
        agent_id=agent_id,
        name="Eval Researcher",
        role="Evaluation Metrics Researcher",
        team="research",
        model=model,
        temperature=0.7,
        max_tokens=4096,
        system_prompt=EVAL_RESEARCH_SYSTEM_PROMPT,
    )
    return EvalResearcher(config=config, message_bus=message_bus, project_state=project_state)


class EvalResearcher(BaseAgent):
    """Agent that researches and designs evaluation metrics.

    Capabilities:
    - Identifies stories related to evaluation metrics and claims them.
    - Uses LLM to research the best evaluation approach for a given metric.
    - Produces metric implementation artifacts conforming to BaseMetric.
    - Knows DeepEval, RAGAS, and academic eval approaches.
    - Proposes new metric implementations when gaps are identified.
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
    ) -> None:
        super().__init__(config, message_bus, project_state)
        self._pending_research: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Research state-of-the-art evaluation metrics for chatbot/LLM systems\n"
            "- Design and implement metrics conforming to the BaseMetric interface\n"
            "- Produce metric implementation artifacts in platform/eval_engine/metrics/\n"
            "- Stay current with DeepEval, RAGAS, and academic evaluation approaches\n"
            "- Propose new metrics to fill coverage gaps\n"
            "- Advise other agents on evaluation methodology\n"
            "- Provide scoring rubrics and validation strategies for each metric"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Process an incoming message and return response messages.

        Handles:
        - STORY / TASK: If related to eval metrics, queue for research.
        - QUERY: Answer evaluation methodology questions.
        - REVIEW_REQUEST: Review proposed metric implementations.
        """
        responses: list[Message] = []

        try:
            if message.message_type in (MessageType.STORY, MessageType.TASK):
                responses.extend(await self._handle_story_or_task(message))
            elif message.message_type == MessageType.QUERY:
                responses.extend(await self._handle_query(message))
            elif message.message_type == MessageType.REVIEW_REQUEST:
                responses.extend(await self._handle_review_request(message))
            elif message.message_type == MessageType.FEATURE_REQUEST:
                responses.extend(await self._handle_feature_request(message))
            else:
                logger.debug(
                    "eval_researcher_ignored_message",
                    message_type=message.message_type.value,
                    subject=message.subject,
                )
        except Exception:
            logger.exception(
                "eval_researcher_process_message_error",
                message_id=message.id,
                message_type=message.message_type.value,
            )

        return responses

    async def plan_work(self) -> list[dict[str, Any]]:
        """Plan the next unit of work.

        Scans the backlog for unassigned stories tagged with eval-metric
        keywords and queues research tasks.  Also checks for metric
        coverage gaps and proposes new metrics.
        """
        planned: list[dict[str, Any]] = []

        # 1. Pick up any pending research from processed messages.
        if self._pending_research:
            planned.extend(self._pending_research)
            self._pending_research.clear()

        # 2. Scan backlog for unclaimed eval-metric stories.
        backlog = self.state.get_backlog(team="research")
        for story in backlog:
            if self._is_eval_metric_story(story) and story.assigned_to is None:
                self.state.assign_story(story.id, self.agent_id, "research")
                self.state.move_story(story.id, StoryStatus.IN_PROGRESS)
                planned.append({
                    "type": "research_metric",
                    "story_id": story.id,
                    "title": story.title,
                    "description": story.description,
                    "tags": story.tags,
                })
                logger.info(
                    "eval_researcher_claimed_story",
                    story_id=story.id,
                    title=story.title,
                )

        # 3. Propose new metrics if coverage gaps exist.
        gap_task = await self._identify_coverage_gaps()
        if gap_task:
            planned.append(gap_task)

        return planned

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a specific research task and return the result.

        Supported task types:
        - research_metric: Research and design a metric implementation.
        - propose_metric: Propose a new metric to fill a coverage gap.
        - answer_query: Answer an evaluation methodology question.
        - review_metric: Review a proposed metric implementation.
        """
        task_type = task.get("type", "")

        try:
            if task_type == "research_metric":
                return await self._execute_research_metric(task)
            elif task_type == "propose_metric":
                return await self._execute_propose_metric(task)
            elif task_type == "answer_query":
                return await self._execute_answer_query(task)
            elif task_type == "review_metric":
                return await self._execute_review_metric(task)
            else:
                logger.warning("eval_researcher_unknown_task_type", task_type=task_type)
                return {"status": "skipped", "reason": f"Unknown task type: {task_type}"}
        except Exception as exc:
            logger.exception("eval_researcher_task_failed", task_type=task_type)
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_story_or_task(self, message: Message) -> list[Message]:
        """Handle a story or task assignment message."""
        responses: list[Message] = []
        payload = message.payload
        story_id = payload.get("story_id", "")
        title = payload.get("title", message.subject)
        description = payload.get("description", "")
        tags = payload.get("tags", [])

        if self._is_relevant(title, description, tags):
            self._pending_research.append({
                "type": "research_metric",
                "story_id": story_id,
                "title": title,
                "description": description,
                "tags": tags,
            })

            await self.send_message(
                to_agent=message.from_agent,
                message_type=MessageType.STATUS_UPDATE,
                subject=f"Accepted: {title}",
                payload={
                    "story_id": story_id,
                    "status": "accepted",
                    "agent": self.agent_id,
                    "message": (
                        f"I will research the best evaluation approach for '{title}' "
                        "and produce a metric implementation artifact."
                    ),
                },
            )
            responses.append(Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.STATUS_UPDATE,
                subject=f"Accepted: {title}",
                payload={"story_id": story_id, "status": "accepted"},
            ))

        return responses

    async def _handle_query(self, message: Message) -> list[Message]:
        """Answer evaluation methodology questions using LLM."""
        question = message.payload.get("question", message.subject)
        self._pending_research.append({
            "type": "answer_query",
            "question": question,
            "from_agent": message.from_agent,
            "reply_to": message.id,
        })
        return []

    async def _handle_review_request(self, message: Message) -> list[Message]:
        """Queue a metric review task."""
        self._pending_research.append({
            "type": "review_metric",
            "code": message.payload.get("code", ""),
            "metric_name": message.payload.get("metric_name", ""),
            "from_agent": message.from_agent,
            "reply_to": message.id,
        })
        return []

    async def _handle_feature_request(self, message: Message) -> list[Message]:
        """Handle a feature request that might require a new metric."""
        title = message.payload.get("title", message.subject)
        description = message.payload.get("description", "")

        if self._is_relevant(title, description, []):
            self._pending_research.append({
                "type": "propose_metric",
                "title": title,
                "description": description,
                "requested_by": message.from_agent,
            })

        return []

    # ------------------------------------------------------------------
    # Task executors
    # ------------------------------------------------------------------

    async def _execute_research_metric(self, task: dict[str, Any]) -> dict[str, Any]:
        """Research and design a metric, producing an implementation artifact."""
        story_id = task.get("story_id", "")
        title = task.get("title", "")
        description = task.get("description", "")
        tags = task.get("tags", [])

        logger.info(
            "eval_researcher_researching_metric",
            story_id=story_id,
            title=title,
        )

        # Determine metric category from tags / title.
        category = self._infer_category(title, description, tags)
        existing_metrics = self._get_existing_metric_names()

        # Build the metric design prompt.
        prompt = METRIC_DESIGN_PROMPT.format(
            category=category,
            metric_name=title,
            purpose=description,
            requirements=self._extract_requirements(description),
            existing_metrics=", ".join(existing_metrics) if existing_metrics else "None yet",
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=4096,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        # Store the implementation as an artifact.
        artifact_key = f"metric_design:{title}"
        self.state.artifacts[artifact_key] = llm_response
        self.context.artifacts[artifact_key] = llm_response

        # If there is an implementation in the result, store it separately.
        implementation = result.get("implementation", "")
        if implementation:
            impl_key = f"metric_impl:{result.get('metric_name', title)}"
            self.state.artifacts[impl_key] = implementation

        # Update story status.
        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        # Notify the team about the completed research.
        await self.send_message(
            to_team="research",
            message_type=MessageType.COMPLETION,
            subject=f"Metric research complete: {title}",
            payload={
                "story_id": story_id,
                "metric_name": result.get("metric_name", title),
                "category": result.get("category", category),
                "approach": result.get("approach", ""),
                "artifact_key": artifact_key,
                "dependencies": result.get("dependencies", []),
                "estimated_latency": result.get("estimated_latency", "unknown"),
            },
        )

        logger.info(
            "eval_researcher_metric_designed",
            story_id=story_id,
            metric_name=result.get("metric_name", title),
            category=result.get("category", category),
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "metric_name": result.get("metric_name", title),
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_propose_metric(self, task: dict[str, Any]) -> dict[str, Any]:
        """Propose a new metric to address a coverage gap or feature request."""
        title = task.get("title", "")
        description = task.get("description", "")

        logger.info("eval_researcher_proposing_metric", title=title)

        prompt = (
            "Based on the following requirement, propose a new evaluation metric.\n\n"
            f"## Requirement\n{title}\n\n"
            f"## Description\n{description}\n\n"
            "## Known Metric Families\n"
            + "\n".join(f"- **{k}**: {v}" for k, v in _KNOWN_METRIC_FAMILIES.items())
            + "\n\n"
            "Respond with a JSON object containing:\n"
            '- "metric_name": proposed metric name\n'
            '- "category": metric category\n'
            '- "approach": high-level approach\n'
            '- "rationale": why this metric is needed\n'
            '- "estimated_complexity": low/medium/high\n'
            '- "story_title": suggested story title for implementation\n'
            '- "story_description": suggested story description\n'
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        # Store as artifact.
        artifact_key = f"metric_proposal:{result.get('metric_name', title)}"
        self.state.artifacts[artifact_key] = llm_response

        # Notify PM about the proposed metric.
        await self.send_message(
            to_team="pm",
            message_type=MessageType.FEATURE_REQUEST,
            subject=f"New metric proposal: {result.get('metric_name', title)}",
            payload={
                "metric_name": result.get("metric_name", title),
                "category": result.get("category", "custom"),
                "approach": result.get("approach", ""),
                "rationale": result.get("rationale", ""),
                "estimated_complexity": result.get("estimated_complexity", "medium"),
                "suggested_story_title": result.get("story_title", ""),
                "suggested_story_description": result.get("story_description", ""),
                "artifact_key": artifact_key,
            },
        )

        return {
            "status": "proposed",
            "metric_name": result.get("metric_name", title),
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_answer_query(self, task: dict[str, Any]) -> dict[str, Any]:
        """Answer an evaluation methodology question."""
        question = task.get("question", "")
        from_agent = task.get("from_agent", "")
        reply_to = task.get("reply_to", "")

        prompt = (
            "A colleague has asked the following evaluation methodology question. "
            "Provide a clear, actionable answer grounded in current best practices.\n\n"
            f"## Question\n{question}\n\n"
            "Include references to specific frameworks (DeepEval, RAGAS) or academic "
            "approaches where relevant."
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )

        if from_agent:
            await self.send_message(
                to_agent=from_agent,
                message_type=MessageType.RESPONSE,
                subject=f"Re: {question[:80]}",
                payload={
                    "answer": llm_response,
                    "reply_to": reply_to,
                },
            )

        return {"status": "answered", "question": question, "answer": llm_response}

    async def _execute_review_metric(self, task: dict[str, Any]) -> dict[str, Any]:
        """Review a proposed metric implementation."""
        code = task.get("code", "")
        metric_name = task.get("metric_name", "")
        from_agent = task.get("from_agent", "")
        reply_to = task.get("reply_to", "")

        prompt = (
            "Review the following evaluation metric implementation for correctness, "
            "completeness, and adherence to best practices.\n\n"
            f"## Metric Name\n{metric_name}\n\n"
            f"## Implementation\n```python\n{code}\n```\n\n"
            "Assess:\n"
            "1. Does it conform to the BaseMetric interface?\n"
            "2. Is the scoring methodology sound?\n"
            "3. Are edge cases handled?\n"
            "4. Is the score properly normalized to 0-1?\n"
            "5. Are there any obvious bugs or issues?\n\n"
            "Respond with JSON:\n"
            '- "approved": true/false\n'
            '- "score": 1-10\n'
            '- "issues": [{"severity": "...", "description": "...", "suggestion": "..."}]\n'
            '- "summary": "overall assessment"\n'
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        if from_agent:
            await self.send_message(
                to_agent=from_agent,
                message_type=MessageType.REVIEW_RESULT,
                subject=f"Review: {metric_name}",
                payload={
                    "metric_name": metric_name,
                    "approved": result.get("approved", False),
                    "score": result.get("score", 0),
                    "issues": result.get("issues", []),
                    "summary": result.get("summary", ""),
                    "reply_to": reply_to,
                },
            )

        return {"status": "reviewed", "metric_name": metric_name, "result": result}

    # ------------------------------------------------------------------
    # Coverage gap analysis
    # ------------------------------------------------------------------

    async def _identify_coverage_gaps(self) -> dict[str, Any] | None:
        """Check whether any well-known metric families lack implementations.

        Returns a propose_metric task if a gap is found, otherwise None.
        """
        existing = self._get_existing_metric_names()
        existing_lower = {name.lower() for name in existing}

        for family, description in _KNOWN_METRIC_FAMILIES.items():
            if family not in existing_lower and not self._has_story_for_metric(family):
                logger.info(
                    "eval_researcher_coverage_gap_found",
                    metric_family=family,
                )
                return {
                    "type": "propose_metric",
                    "title": f"{family.replace('_', ' ').title()} Metric",
                    "description": description,
                    "requested_by": self.agent_id,
                }

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_relevant(title: str, description: str, tags: list[str]) -> bool:
        """Determine whether a story/task is relevant to eval metrics research."""
        combined = f"{title} {description}".lower()
        tag_set = {t.lower() for t in tags}

        # Check tag overlap.
        if tag_set & _EVAL_METRIC_TAGS:
            return True

        # Check keyword presence.
        keywords = [
            "metric", "evaluation", "eval", "faithfulness", "groundedness",
            "hallucination", "toxicity", "coherence", "relevance", "scoring",
            "deepeval", "ragas", "answer correctness", "safety metric",
        ]
        return any(kw in combined for kw in keywords)

    @staticmethod
    def _is_eval_metric_story(story: Story) -> bool:
        """Check whether a story is about eval metrics."""
        return EvalResearcher._is_relevant(
            story.title, story.description, story.tags
        ) and story.task_type in (TaskType.STORY, TaskType.RESEARCH, TaskType.SPIKE)

    @staticmethod
    def _infer_category(title: str, description: str, tags: list[str]) -> str:
        """Infer the metric category from title, description, and tags."""
        combined = f"{title} {description} {' '.join(tags)}".lower()
        category_keywords: dict[str, list[str]] = {
            "faithfulness": ["faithful", "faithfulness", "entailment", "nli"],
            "relevance": ["relevant", "relevance", "query-answer", "information completeness"],
            "safety": ["toxic", "toxicity", "safety", "harmful", "bias"],
            "quality": ["coherence", "coherent", "quality", "fluency", "discourse"],
            "performance": ["latency", "performance", "throughput"],
            "cost": ["cost", "token usage", "api cost"],
        }
        for category, keywords in category_keywords.items():
            if any(kw in combined for kw in keywords):
                return category
        return "custom"

    @staticmethod
    def _extract_requirements(description: str) -> str:
        """Extract concrete requirements from a story description."""
        # Return the description as-is; the LLM will interpret it.
        return description if description else "No specific requirements provided."

    def _get_existing_metric_names(self) -> list[str]:
        """Retrieve names of metrics already implemented or designed."""
        names: list[str] = []
        for key in self.state.artifacts:
            if key.startswith("metric_impl:") or key.startswith("metric_design:"):
                names.append(key.split(":", 1)[1])
        return names

    def _has_story_for_metric(self, metric_family: str) -> bool:
        """Check whether there is already a story covering this metric family."""
        family_lower = metric_family.lower()
        for story in self.state.stories.values():
            combined = f"{story.title} {story.description}".lower()
            if family_lower in combined and story.status != StoryStatus.DONE:
                return True
        return False

    @staticmethod
    def _parse_json_response(raw: str) -> dict[str, Any]:
        """Safely parse a JSON response from the LLM.

        Handles responses wrapped in markdown code fences.
        """
        import re

        # Try to extract JSON from fenced block.
        json_match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
        text = json_match.group(1).strip() if json_match else raw.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "eval_researcher_json_parse_failed",
                raw_length=len(raw),
            )
            return {"raw_response": raw}
