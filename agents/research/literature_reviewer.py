"""Literature Reviewer agent for the research team.

Searches for and analyzes academic papers on LLM and chatbot evaluation,
extracts actionable insights, identifies coverage gaps, and proposes
new research directions for the evaluation platform.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType
from agents.research.prompts import (
    LITERATURE_REVIEW_PROMPT,
)
from agents.state import (
    ProjectState,
    Story,
    StoryStatus,
    TaskType,
)

logger = structlog.get_logger()

# Tags that indicate work relevant to literature review.
_LITERATURE_TAGS = frozenset({
    "research",
    "literature",
    "paper",
    "survey",
    "benchmark",
    "sota",
    "state-of-the-art",
    "academic",
    "spike",
})

# Core research topics the reviewer tracks.
_TRACKED_TOPICS: dict[str, str] = {
    "llm_evaluation": (
        "Evaluation methodologies for large language models including "
        "automated metrics, human evaluation, and benchmark suites."
    ),
    "faithfulness_and_hallucination": (
        "Techniques for detecting hallucinations and measuring faithfulness "
        "of LLM responses to source material."
    ),
    "llm_as_judge": (
        "Using large language models as automated evaluators, including "
        "calibration, bias mitigation, and agreement with human raters."
    ),
    "rag_evaluation": (
        "Evaluating retrieval-augmented generation systems across retrieval "
        "quality, context utilization, and answer quality dimensions."
    ),
    "safety_and_alignment": (
        "Evaluating LLM safety, alignment with human values, toxicity, "
        "bias detection, and red-teaming methodologies."
    ),
    "conversational_evaluation": (
        "Evaluating multi-turn conversational systems for coherence, "
        "context retention, engagement, and task completion."
    ),
    "benchmark_design": (
        "Design principles for evaluation benchmarks including data "
        "contamination, benchmark saturation, and dynamic evaluation."
    ),
}


def create_literature_reviewer(
    message_bus: MessageBus,
    project_state: ProjectState,
    *,
    agent_id: str = "literature-reviewer",
    model: str = "gpt-4o-mini",
) -> LiteratureReviewer:
    """Factory function to create a fully-configured LiteratureReviewer agent."""
    config = AgentConfig(
        agent_id=agent_id,
        name="Literature Reviewer",
        role="Academic Literature Reviewer",
        team="research",
        model=model,
        temperature=0.7,
        max_tokens=4096,
        system_prompt=(
            "You are an academic literature reviewer specializing in LLM and "
            "chatbot evaluation. You stay current with the latest research papers, "
            "benchmarks, and evaluation methodologies. You synthesize findings into "
            "actionable recommendations for the engineering and research teams."
        ),
    )
    return LiteratureReviewer(
        config=config, message_bus=message_bus, project_state=project_state,
    )


class LiteratureReviewer(BaseAgent):
    """Agent that reviews academic literature on LLM evaluation.

    Capabilities:
    - Simulates paper search and analysis using LLM knowledge.
    - Produces structured literature reviews on specific topics.
    - Identifies gaps in current evaluation coverage.
    - Proposes new research directions and metric implementations.
    - Summarizes papers and extracts actionable insights.
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
    ) -> None:
        super().__init__(config, message_bus, project_state)
        self._pending_reviews: list[dict[str, Any]] = []
        self._reviewed_topics: set[str] = set()

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Search for and analyze latest evaluation techniques from academic papers\n"
            "- Produce structured literature reviews with actionable insights\n"
            "- Identify gaps in the platform's current evaluation coverage\n"
            "- Propose new research directions and metric implementations\n"
            "- Summarize relevant papers for the research and engineering teams\n"
            "- Track key research topics: LLM evaluation, faithfulness, "
            "LLM-as-judge, RAG evaluation, safety, conversational evaluation\n"
            "- Provide evidence-based recommendations for metric design decisions"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Process an incoming message and return response messages.

        Handles:
        - STORY / TASK: If it's a research/spike story, queue a literature review.
        - QUERY: Answer questions about evaluation literature.
        - FEATURE_REQUEST: Assess whether academic research supports the request.
        """
        responses: list[Message] = []

        try:
            if message.message_type in (MessageType.STORY, MessageType.TASK):
                responses.extend(await self._handle_story_or_task(message))
            elif message.message_type == MessageType.QUERY:
                responses.extend(await self._handle_query(message))
            elif message.message_type == MessageType.FEATURE_REQUEST:
                responses.extend(await self._handle_feature_request(message))
            elif message.message_type == MessageType.REVIEW_REQUEST:
                responses.extend(await self._handle_review_request(message))
            else:
                logger.debug(
                    "literature_reviewer_ignored_message",
                    message_type=message.message_type.value,
                    subject=message.subject,
                )
        except Exception:
            logger.exception(
                "literature_reviewer_process_message_error",
                message_id=message.id,
                message_type=message.message_type.value,
            )

        return responses

    async def plan_work(self) -> list[dict[str, Any]]:
        """Plan the next unit of work.

        Scans for unclaimed research/spike stories, flushes pending reviews,
        and identifies topics that haven't been reviewed yet.
        """
        planned: list[dict[str, Any]] = []

        # 1. Flush pending reviews from message processing.
        if self._pending_reviews:
            planned.extend(self._pending_reviews)
            self._pending_reviews.clear()

        # 2. Claim unclaimed research/spike stories.
        backlog = self.state.get_backlog(team="research")
        for story in backlog:
            if self._is_literature_story(story) and story.assigned_to is None:
                self.state.assign_story(story.id, self.agent_id, "research")
                self.state.move_story(story.id, StoryStatus.IN_PROGRESS)
                planned.append({
                    "type": "literature_review",
                    "story_id": story.id,
                    "title": story.title,
                    "description": story.description,
                    "tags": story.tags,
                })
                logger.info(
                    "literature_reviewer_claimed_story",
                    story_id=story.id,
                    title=story.title,
                )

        # 3. Proactively review an unreviewed topic.
        topic_task = self._identify_unreviewed_topic()
        if topic_task:
            planned.append(topic_task)

        return planned

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a specific literature review task.

        Supported task types:
        - literature_review: Conduct a full literature review on a topic.
        - paper_analysis: Analyze a specific paper or set of papers.
        - gap_analysis: Identify gaps in evaluation coverage.
        - answer_query: Answer a literature-related question.
        - assess_feature: Assess academic support for a feature request.
        """
        task_type = task.get("type", "")

        try:
            if task_type == "literature_review":
                return await self._execute_literature_review(task)
            elif task_type == "paper_analysis":
                return await self._execute_paper_analysis(task)
            elif task_type == "gap_analysis":
                return await self._execute_gap_analysis(task)
            elif task_type == "answer_query":
                return await self._execute_answer_query(task)
            elif task_type == "assess_feature":
                return await self._execute_assess_feature(task)
            else:
                logger.warning("literature_reviewer_unknown_task_type", task_type=task_type)
                return {"status": "skipped", "reason": f"Unknown task type: {task_type}"}
        except Exception as exc:
            logger.exception("literature_reviewer_task_failed", task_type=task_type)
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_story_or_task(self, message: Message) -> list[Message]:
        """Handle a story or task assignment."""
        payload = message.payload
        story_id = payload.get("story_id", "")
        title = payload.get("title", message.subject)
        description = payload.get("description", "")
        tags = payload.get("tags", [])

        if self._is_relevant(title, description, tags):
            self._pending_reviews.append({
                "type": "literature_review",
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
                        f"I will conduct a literature review on '{title}' "
                        "and produce a summary with actionable recommendations."
                    ),
                },
            )

        return []

    async def _handle_query(self, message: Message) -> list[Message]:
        """Queue a literature query for answering."""
        question = message.payload.get("question", message.subject)
        self._pending_reviews.append({
            "type": "answer_query",
            "question": question,
            "from_agent": message.from_agent,
            "reply_to": message.id,
        })
        return []

    async def _handle_feature_request(self, message: Message) -> list[Message]:
        """Assess academic support for a feature request."""
        title = message.payload.get("title", message.subject)
        description = message.payload.get("description", "")

        if self._is_relevant(title, description, []):
            self._pending_reviews.append({
                "type": "assess_feature",
                "title": title,
                "description": description,
                "from_agent": message.from_agent,
                "reply_to": message.id,
            })

        return []

    async def _handle_review_request(self, message: Message) -> list[Message]:
        """Handle a request to review a research topic more deeply."""
        topic = message.payload.get("topic", message.subject)
        self._pending_reviews.append({
            "type": "literature_review",
            "title": topic,
            "description": message.payload.get("description", ""),
            "tags": message.payload.get("tags", []),
            "story_id": message.payload.get("story_id", ""),
        })
        return []

    # ------------------------------------------------------------------
    # Task executors
    # ------------------------------------------------------------------

    async def _execute_literature_review(self, task: dict[str, Any]) -> dict[str, Any]:
        """Conduct a structured literature review on a topic."""
        story_id = task.get("story_id", "")
        title = task.get("title", "")
        description = task.get("description", "")
        tags = task.get("tags", [])

        logger.info(
            "literature_reviewer_conducting_review",
            story_id=story_id,
            title=title,
        )

        # Determine the research topic and questions.
        topic = self._resolve_topic(title, description, tags)
        current_capabilities = self._summarize_current_capabilities()
        research_questions = self._generate_research_questions(topic, description)

        prompt = LITERATURE_REVIEW_PROMPT.format(
            topic=topic,
            current_capabilities=current_capabilities,
            research_questions=research_questions,
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=4096,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        # Store artifact.
        artifact_key = f"literature_review:{topic}"
        self.state.artifacts[artifact_key] = llm_response
        self.context.artifacts[artifact_key] = llm_response

        # Track this topic as reviewed.
        self._reviewed_topics.add(topic.lower())

        # Update story status.
        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        # Notify the team about findings.
        recommendations = result.get("recommendations", [])
        gaps = result.get("gaps", [])

        await self.send_message(
            to_team="research",
            message_type=MessageType.COMPLETION,
            subject=f"Literature review complete: {topic}",
            payload={
                "story_id": story_id,
                "topic": topic,
                "artifact_key": artifact_key,
                "paper_count": len(result.get("key_papers", [])),
                "recommendation_count": len(recommendations),
                "gap_count": len(gaps),
                "top_recommendations": recommendations[:3],
            },
        )

        # If gaps were found, propose them as research directions.
        if gaps:
            await self._propose_research_directions(gaps, topic)

        logger.info(
            "literature_reviewer_review_completed",
            story_id=story_id,
            topic=topic,
            papers=len(result.get("key_papers", [])),
            recommendations=len(recommendations),
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "topic": topic,
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_paper_analysis(self, task: dict[str, Any]) -> dict[str, Any]:
        """Analyze specific papers or research directions."""
        title = task.get("title", "")
        description = task.get("description", "")
        papers = task.get("papers", [])

        logger.info("literature_reviewer_analyzing_papers", title=title)

        papers_context = "\n".join(
            f"- {p}" for p in papers
        ) if papers else "Search for the most relevant recent papers."

        prompt = (
            "Analyze the following research papers/directions for their applicability "
            "to a chatbot evaluation platform.\n\n"
            f"## Topic\n{title}\n\n"
            f"## Description\n{description}\n\n"
            f"## Papers to Analyze\n{papers_context}\n\n"
            "For each paper/approach, provide:\n"
            "1. Key methodology and contributions\n"
            "2. Applicability to chatbot evaluation\n"
            "3. Implementation complexity\n"
            "4. Expected improvement over current approaches\n"
            "5. Data requirements\n\n"
            "Respond with a JSON object containing:\n"
            '- "analyses": [{title, methodology, applicability, complexity, '
            'improvement, data_requirements, recommendation}]\n'
            '- "synthesis": overall synthesis of findings\n'
            '- "next_steps": recommended next steps\n'
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        artifact_key = f"paper_analysis:{title}"
        self.state.artifacts[artifact_key] = llm_response

        return {
            "status": "completed",
            "title": title,
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_gap_analysis(self, task: dict[str, Any]) -> dict[str, Any]:
        """Identify gaps in the platform's evaluation coverage."""
        logger.info("literature_reviewer_conducting_gap_analysis")

        current_capabilities = self._summarize_current_capabilities()
        existing_reviews = [
            key.split(":", 1)[1]
            for key in self.state.artifacts
            if key.startswith("literature_review:")
        ]

        prompt = (
            "Conduct a gap analysis of the chatbot evaluation platform's current "
            "coverage compared to the state of the art.\n\n"
            f"## Current Capabilities\n{current_capabilities}\n\n"
            "## Existing Literature Reviews\n"
            + (", ".join(existing_reviews) if existing_reviews else "None yet")
            + "\n\n"
            "## Known Evaluation Dimensions\n"
            "- Faithfulness / Groundedness\n"
            "- Hallucination detection\n"
            "- Relevance / Answer correctness\n"
            "- Coherence / Fluency\n"
            "- Safety / Toxicity / Bias\n"
            "- Instruction following\n"
            "- Multi-turn conversational quality\n"
            "- RAG-specific metrics (context precision, recall)\n\n"
            "Identify gaps and prioritize them. Respond with JSON:\n"
            '- "gaps": [{dimension, description, severity, recommendation}]\n'
            '- "coverage_score": 0-100 (overall coverage percentage)\n'
            '- "priority_actions": [{action, rationale, complexity}]\n'
            '- "emerging_topics": [{topic, description, relevance}]\n'
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        artifact_key = "gap_analysis:latest"
        self.state.artifacts[artifact_key] = llm_response

        # Notify PM about priority gaps.
        priority_actions = result.get("priority_actions", [])
        if priority_actions:
            await self.send_message(
                to_team="pm",
                message_type=MessageType.STATUS_UPDATE,
                subject="Evaluation coverage gap analysis",
                payload={
                    "coverage_score": result.get("coverage_score", 0),
                    "gap_count": len(result.get("gaps", [])),
                    "priority_actions": priority_actions[:5],
                    "artifact_key": artifact_key,
                },
            )

        return {
            "status": "completed",
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_answer_query(self, task: dict[str, Any]) -> dict[str, Any]:
        """Answer a question about evaluation literature."""
        question = task.get("question", "")
        from_agent = task.get("from_agent", "")
        reply_to = task.get("reply_to", "")

        prompt = (
            "A colleague has asked the following question about evaluation research "
            "and academic literature. Provide a thorough answer with references to "
            "specific papers, benchmarks, and methodologies.\n\n"
            f"## Question\n{question}\n\n"
            "Include:\n"
            "- Key papers and their findings\n"
            "- Current best practices\n"
            "- Practical recommendations for our platform\n"
            "- Any caveats or limitations"
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

    async def _execute_assess_feature(self, task: dict[str, Any]) -> dict[str, Any]:
        """Assess whether academic research supports a feature request."""
        title = task.get("title", "")
        description = task.get("description", "")
        from_agent = task.get("from_agent", "")
        reply_to = task.get("reply_to", "")

        logger.info("literature_reviewer_assessing_feature", title=title)

        prompt = (
            "Assess whether academic research supports the following feature request "
            "for a chatbot evaluation platform.\n\n"
            f"## Feature\n{title}\n\n"
            f"## Description\n{description}\n\n"
            "Evaluate:\n"
            "1. Is there academic research supporting this approach?\n"
            "2. What are the proven methodologies for this?\n"
            "3. What results have been achieved in the literature?\n"
            "4. What are the known limitations?\n"
            "5. Is this approach mature enough for production use?\n\n"
            "Respond with JSON:\n"
            '- "supported": true/false (is there strong academic support?)\n'
            '- "confidence": "high"/"medium"/"low"\n'
            '- "key_references": [{title, finding}]\n'
            '- "proven_methodologies": [description]\n'
            '- "limitations": [description]\n'
            '- "maturity": "experimental"/"emerging"/"established"\n'
            '- "recommendation": description\n'
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        if from_agent:
            await self.send_message(
                to_agent=from_agent,
                message_type=MessageType.RESPONSE,
                subject=f"Research assessment: {title}",
                payload={
                    "supported": result.get("supported", False),
                    "confidence": result.get("confidence", "low"),
                    "maturity": result.get("maturity", "experimental"),
                    "recommendation": result.get("recommendation", ""),
                    "reply_to": reply_to,
                },
            )

        return {"status": "assessed", "title": title, "result": result}

    # ------------------------------------------------------------------
    # Proactive research
    # ------------------------------------------------------------------

    def _identify_unreviewed_topic(self) -> dict[str, Any] | None:
        """Find a tracked topic that hasn't been reviewed yet.

        Returns a literature_review task if an unreviewed topic is found.
        """
        for topic_key, description in _TRACKED_TOPICS.items():
            topic_display = topic_key.replace("_", " ").title()
            if topic_key not in self._reviewed_topics:
                # Also check if there's already an artifact for this topic.
                artifact_key = f"literature_review:{topic_display}"
                if artifact_key not in self.state.artifacts:
                    logger.info(
                        "literature_reviewer_unreviewed_topic_found",
                        topic=topic_key,
                    )
                    return {
                        "type": "literature_review",
                        "title": topic_display,
                        "description": description,
                        "tags": ["research", "literature", topic_key],
                        "story_id": "",
                    }

        return None

    async def _propose_research_directions(
        self, gaps: list[str], source_topic: str,
    ) -> None:
        """Propose new research directions based on identified gaps."""
        for gap in gaps[:3]:  # Limit to top 3 gaps.
            await self.send_message(
                to_team="research",
                message_type=MessageType.FEATURE_REQUEST,
                subject=f"Research direction: {gap[:80]}",
                payload={
                    "title": f"Research: {gap[:80]}",
                    "description": (
                        f"Identified during literature review of '{source_topic}'. "
                        f"Gap: {gap}"
                    ),
                    "source": self.agent_id,
                    "source_topic": source_topic,
                },
                priority="medium",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_relevant(title: str, description: str, tags: list[str]) -> bool:
        """Determine whether a story/task is relevant to literature review."""
        combined = f"{title} {description}".lower()
        tag_set = {t.lower() for t in tags}

        if tag_set & _LITERATURE_TAGS:
            return True

        keywords = [
            "research", "literature", "paper", "survey", "benchmark",
            "state of the art", "sota", "academic", "spike", "review",
            "study", "technique", "approach", "methodology",
        ]
        return any(kw in combined for kw in keywords)

    @staticmethod
    def _is_literature_story(story: Story) -> bool:
        """Check whether a story is a research or spike that needs literature review."""
        if story.task_type not in (TaskType.RESEARCH, TaskType.SPIKE):
            return False
        return LiteratureReviewer._is_relevant(
            story.title, story.description, story.tags,
        )

    def _resolve_topic(self, title: str, description: str, tags: list[str]) -> str:
        """Resolve the research topic from title, description, and tags."""
        combined = f"{title} {description}".lower()

        # Try to match a tracked topic.
        for topic_key, topic_desc in _TRACKED_TOPICS.items():
            topic_words = topic_key.replace("_", " ").split()
            if all(word in combined for word in topic_words):
                return topic_key.replace("_", " ").title()

        # Fall back to the title.
        return title

    def _summarize_current_capabilities(self) -> str:
        """Summarize what metrics and capabilities the platform currently has."""
        metrics = [
            key.split(":", 1)[1]
            for key in self.state.artifacts
            if key.startswith("metric_impl:") or key.startswith("metric_design:")
        ]
        judge_prompts = [
            key.split(":", 1)[1]
            for key in self.state.artifacts
            if key.startswith("judge_prompt:")
        ]
        pipelines = [
            key.split(":", 1)[1]
            for key in self.state.artifacts
            if key.startswith("eval_pipeline:")
        ]

        parts: list[str] = []
        if metrics:
            parts.append(f"Implemented metrics: {', '.join(metrics)}")
        if judge_prompts:
            parts.append(f"Judge prompts: {', '.join(judge_prompts)}")
        if pipelines:
            parts.append(f"Evaluation pipelines: {', '.join(pipelines)}")

        if not parts:
            parts.append(
                "The platform is in early development. The BaseMetric interface "
                "is defined but no specific metrics have been implemented yet."
            )

        return "\n".join(parts)

    @staticmethod
    def _generate_research_questions(topic: str, description: str) -> str:
        """Generate research questions based on the topic and description."""
        base_questions = [
            f"What are the current state-of-the-art approaches for {topic.lower()}?",
            "Which approaches are most suitable for production deployment at scale?",
            "What are the known limitations and failure modes?",
            "How do automated approaches compare with human evaluation?",
        ]

        if description:
            base_questions.append(
                f"Specifically: {description}"
            )

        return "\n".join(f"- {q}" for q in base_questions)

    @staticmethod
    def _parse_json_response(raw: str) -> dict[str, Any]:
        """Safely parse a JSON response from the LLM."""
        json_match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
        text = json_match.group(1).strip() if json_match else raw.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "literature_reviewer_json_parse_failed",
                raw_length=len(raw),
            )
            return {"raw_response": raw}
