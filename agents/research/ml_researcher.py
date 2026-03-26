"""ML Researcher agent for the research team.

Specializes in LLM-as-Judge implementations, embedding-based similarity
metrics, evaluation pipeline design, and fine-tuning strategies for
custom evaluation models.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.message_bus import Message, MessageBus, MessageType
from agents.research.prompts import (
    EVALUATION_STRATEGY_PROMPT,
    JUDGE_PROMPT_DESIGN,
    ML_RESEARCH_SYSTEM_PROMPT,
)
from agents.state import (
    ProjectState,
    Story,
    StoryStatus,
    TaskType,
)

logger = structlog.get_logger()

# Tags that indicate ML-research-relevant work.
_ML_RESEARCH_TAGS = frozenset({
    "llm-as-judge",
    "judge",
    "embedding",
    "similarity",
    "fine-tuning",
    "pipeline",
    "evaluation_strategy",
    "ml",
    "eval_engine",
})

# Evaluation dimensions this agent can design judge prompts for.
_JUDGE_DIMENSIONS: dict[str, str] = {
    "helpfulness": "How helpful and useful the assistant's response is to the user.",
    "harmlessness": "Whether the response avoids harmful, toxic, or dangerous content.",
    "honesty": "Whether the response is truthful and acknowledges uncertainty.",
    "instruction_following": "How well the response follows the user's instructions.",
    "reasoning": "Quality of logical reasoning and problem-solving in the response.",
    "creativity": "Originality and creative quality of the response.",
    "conciseness": "Whether the response is appropriately concise without losing substance.",
    "factual_accuracy": "Whether factual claims in the response are correct.",
}


def create_ml_researcher(
    message_bus: MessageBus,
    project_state: ProjectState,
    *,
    agent_id: str = "ml-researcher",
    model: str = "gpt-4o-mini",
) -> MLResearcher:
    """Factory function to create a fully-configured MLResearcher agent."""
    config = AgentConfig(
        agent_id=agent_id,
        name="ML Researcher",
        role="Machine Learning Research Scientist",
        team="research",
        model=model,
        temperature=0.7,
        max_tokens=4096,
        system_prompt=ML_RESEARCH_SYSTEM_PROMPT,
    )
    return MLResearcher(config=config, message_bus=message_bus, project_state=project_state)


class MLResearcher(BaseAgent):
    """Agent that designs LLM-as-Judge systems, embedding metrics, and eval pipelines.

    Capabilities:
    - Designs optimal LLM judge prompts with bias mitigation.
    - Proposes embedding-based similarity metrics.
    - Architects multi-stage evaluation pipelines.
    - Researches fine-tuning approaches for custom eval models.
    - Produces evaluation strategy artifacts.
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
    ) -> None:
        super().__init__(config, message_bus, project_state)
        self._pending_tasks: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Design LLM-as-Judge prompts with scoring rubrics and bias mitigation\n"
            "- Research and propose embedding-based similarity metrics\n"
            "- Architect evaluation pipelines (data flow, metric composition, aggregation)\n"
            "- Propose fine-tuning strategies for custom evaluation models\n"
            "- Design evaluation strategies for specific chatbot domains\n"
            "- Advise on statistical methods for evaluation (inter-annotator agreement, "
            "confidence intervals)\n"
            "- Optimize evaluation cost through cascading and caching strategies"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Process an incoming message and return response messages.

        Handles:
        - STORY / TASK: If related to ML research topics, queue for execution.
        - QUERY: Answer ML methodology questions.
        - REVIEW_REQUEST: Review judge prompts or pipeline designs.
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
                    "ml_researcher_ignored_message",
                    message_type=message.message_type.value,
                    subject=message.subject,
                )
        except Exception:
            logger.exception(
                "ml_researcher_process_message_error",
                message_id=message.id,
                message_type=message.message_type.value,
            )

        return responses

    async def plan_work(self) -> list[dict[str, Any]]:
        """Plan the next unit of work.

        Scans for unclaimed ML-research stories and checks whether any
        evaluation dimensions lack judge prompts.
        """
        planned: list[dict[str, Any]] = []

        # 1. Flush pending tasks from message processing.
        if self._pending_tasks:
            planned.extend(self._pending_tasks)
            self._pending_tasks.clear()

        # 2. Claim unclaimed ML-research stories.
        backlog = self.state.get_backlog(team="research")
        for story in backlog:
            if self._is_ml_research_story(story) and story.assigned_to is None:
                self.state.assign_story(story.id, self.agent_id, "research")
                self.state.move_story(story.id, StoryStatus.IN_PROGRESS)
                task_type = self._classify_story(story)
                planned.append({
                    "type": task_type,
                    "story_id": story.id,
                    "title": story.title,
                    "description": story.description,
                    "tags": story.tags,
                })
                logger.info(
                    "ml_researcher_claimed_story",
                    story_id=story.id,
                    title=story.title,
                    task_type=task_type,
                )

        # 3. Propose judge prompts for uncovered dimensions.
        gap_task = self._identify_judge_gaps()
        if gap_task:
            planned.append(gap_task)

        return planned

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a specific ML research task.

        Supported task types:
        - design_judge_prompt: Design an LLM-as-Judge prompt.
        - design_eval_pipeline: Design an evaluation pipeline.
        - research_embeddings: Research embedding-based metrics.
        - design_eval_strategy: Design a comprehensive eval strategy.
        - research_fine_tuning: Research fine-tuning approaches.
        - answer_query: Answer an ML methodology question.
        - review_artifact: Review a judge prompt or pipeline design.
        """
        task_type = task.get("type", "")

        try:
            if task_type == "design_judge_prompt":
                return await self._execute_design_judge_prompt(task)
            elif task_type == "design_eval_pipeline":
                return await self._execute_design_eval_pipeline(task)
            elif task_type == "research_embeddings":
                return await self._execute_research_embeddings(task)
            elif task_type == "design_eval_strategy":
                return await self._execute_design_eval_strategy(task)
            elif task_type == "research_fine_tuning":
                return await self._execute_research_fine_tuning(task)
            elif task_type == "answer_query":
                return await self._execute_answer_query(task)
            elif task_type == "review_artifact":
                return await self._execute_review_artifact(task)
            else:
                logger.warning("ml_researcher_unknown_task_type", task_type=task_type)
                return {"status": "skipped", "reason": f"Unknown task type: {task_type}"}
        except Exception as exc:
            logger.exception("ml_researcher_task_failed", task_type=task_type)
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
            task_type = self._classify_from_text(title, description)
            self._pending_tasks.append({
                "type": task_type,
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
                    "task_type": task_type,
                },
            )

        return []

    async def _handle_query(self, message: Message) -> list[Message]:
        """Queue an ML methodology query for answering."""
        question = message.payload.get("question", message.subject)
        self._pending_tasks.append({
            "type": "answer_query",
            "question": question,
            "from_agent": message.from_agent,
            "reply_to": message.id,
        })
        return []

    async def _handle_review_request(self, message: Message) -> list[Message]:
        """Queue an artifact review task."""
        self._pending_tasks.append({
            "type": "review_artifact",
            "artifact": message.payload.get("artifact", ""),
            "artifact_type": message.payload.get("artifact_type", "judge_prompt"),
            "from_agent": message.from_agent,
            "reply_to": message.id,
        })
        return []

    async def _handle_feature_request(self, message: Message) -> list[Message]:
        """Handle feature requests related to ML evaluation."""
        title = message.payload.get("title", message.subject)
        description = message.payload.get("description", "")

        if self._is_relevant(title, description, []):
            task_type = self._classify_from_text(title, description)
            self._pending_tasks.append({
                "type": task_type,
                "title": title,
                "description": description,
                "requested_by": message.from_agent,
            })

        return []

    # ------------------------------------------------------------------
    # Task executors
    # ------------------------------------------------------------------

    async def _execute_design_judge_prompt(self, task: dict[str, Any]) -> dict[str, Any]:
        """Design an LLM-as-Judge prompt for a specific evaluation dimension."""
        story_id = task.get("story_id", "")
        title = task.get("title", "")
        description = task.get("description", "")

        dimension = self._infer_judge_dimension(title, description)
        dimension_description = _JUDGE_DIMENSIONS.get(dimension, description)

        logger.info(
            "ml_researcher_designing_judge_prompt",
            story_id=story_id,
            dimension=dimension,
        )

        prompt = JUDGE_PROMPT_DESIGN.format(
            dimension=dimension,
            scoring_scale="1-5 (1=poor, 2=below average, 3=average, 4=good, 5=excellent)",
            context=(
                f"Dimension description: {dimension_description}\n\n"
                f"Additional context: {description}"
            ),
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=4096,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        # Store artifact.
        artifact_key = f"judge_prompt:{dimension}"
        self.state.artifacts[artifact_key] = llm_response
        self.context.artifacts[artifact_key] = llm_response

        # Update story status.
        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        # Notify team.
        await self.send_message(
            to_team="research",
            message_type=MessageType.COMPLETION,
            subject=f"Judge prompt designed: {dimension}",
            payload={
                "story_id": story_id,
                "dimension": dimension,
                "artifact_key": artifact_key,
                "recommended_model": result.get("recommended_model", ""),
                "bias_mitigation": result.get("bias_mitigation_techniques", []),
            },
        )

        logger.info(
            "ml_researcher_judge_prompt_designed",
            story_id=story_id,
            dimension=dimension,
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "dimension": dimension,
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_design_eval_pipeline(self, task: dict[str, Any]) -> dict[str, Any]:
        """Design a multi-stage evaluation pipeline."""
        story_id = task.get("story_id", "")
        title = task.get("title", "")
        description = task.get("description", "")

        logger.info(
            "ml_researcher_designing_eval_pipeline",
            story_id=story_id,
            title=title,
        )

        prompt = (
            "Design a multi-stage evaluation pipeline for the following requirement.\n\n"
            f"## Requirement\n{title}\n\n"
            f"## Description\n{description}\n\n"
            "The pipeline should specify:\n"
            "1. Data flow from raw conversations to final scores\n"
            "2. Metric execution stages (parallel vs sequential)\n"
            "3. Metric composition and aggregation strategy\n"
            "4. Quality gates between stages\n"
            "5. Caching and cost optimization\n"
            "6. Error handling and fallback strategies\n\n"
            "Respond with a JSON object containing:\n"
            '- "pipeline_name": descriptive name\n'
            '- "stages": [{name, metrics, parallel, gate_condition}]\n'
            '- "aggregation": {method, formula}\n'
            '- "caching_strategy": description\n'
            '- "error_handling": description\n'
            '- "estimated_latency_per_eval": estimate\n'
            '- "estimated_cost_per_eval": estimate\n'
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        artifact_key = f"eval_pipeline:{result.get('pipeline_name', title)}"
        self.state.artifacts[artifact_key] = llm_response
        self.context.artifacts[artifact_key] = llm_response

        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        await self.send_message(
            to_team="engineering",
            message_type=MessageType.COMPLETION,
            subject=f"Eval pipeline designed: {title}",
            payload={
                "story_id": story_id,
                "pipeline_name": result.get("pipeline_name", title),
                "artifact_key": artifact_key,
                "stages": result.get("stages", []),
            },
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_research_embeddings(self, task: dict[str, Any]) -> dict[str, Any]:
        """Research embedding-based similarity metrics."""
        story_id = task.get("story_id", "")
        title = task.get("title", "")
        description = task.get("description", "")

        logger.info(
            "ml_researcher_researching_embeddings",
            story_id=story_id,
            title=title,
        )

        prompt = (
            "Research embedding-based similarity metrics for chatbot evaluation.\n\n"
            f"## Context\n{title}\n\n"
            f"## Description\n{description}\n\n"
            "Cover the following aspects:\n"
            "1. **Embedding models**: Compare SentenceTransformers, OpenAI embeddings, "
            "Cohere embeddings for evaluation use cases. Include model names, dimensions, "
            "and performance characteristics.\n"
            "2. **Similarity metrics**: Cosine similarity, Euclidean distance, "
            "Mahalanobis distance - when to use each.\n"
            "3. **Applications**: Semantic similarity scoring, answer-reference comparison, "
            "retrieval quality (context relevance), diversity measurement.\n"
            "4. **Implementation**: Recommended approach for our platform, including "
            "batching, caching, and fallback strategies.\n"
            "5. **Benchmarks**: Expected score distributions for good vs poor responses.\n\n"
            "Respond with a JSON object containing:\n"
            '- "recommended_models": [{name, provider, dimensions, use_case}]\n'
            '- "similarity_metrics": [{name, formula, when_to_use}]\n'
            '- "applications": [{name, description, recommended_model, recommended_metric}]\n'
            '- "implementation_plan": description\n'
            '- "caching_strategy": description\n'
            '- "estimated_latency": description\n'
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        artifact_key = f"embedding_research:{title}"
        self.state.artifacts[artifact_key] = llm_response

        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        await self.send_message(
            to_team="research",
            message_type=MessageType.COMPLETION,
            subject=f"Embedding research complete: {title}",
            payload={
                "story_id": story_id,
                "artifact_key": artifact_key,
                "recommended_models": result.get("recommended_models", []),
            },
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_design_eval_strategy(self, task: dict[str, Any]) -> dict[str, Any]:
        """Design a comprehensive evaluation strategy for a specific use case."""
        story_id = task.get("story_id", "")
        title = task.get("title", "")
        description = task.get("description", "")

        logger.info(
            "ml_researcher_designing_eval_strategy",
            story_id=story_id,
            title=title,
        )

        # Gather existing metric names for context.
        existing_metrics = [
            key.split(":", 1)[1]
            for key in self.state.artifacts
            if key.startswith("metric_impl:") or key.startswith("judge_prompt:")
        ]

        prompt = EVALUATION_STRATEGY_PROMPT.format(
            use_case=title,
            domain=self._infer_domain(description),
            available_metrics=", ".join(existing_metrics) if existing_metrics else "Standard metrics (faithfulness, relevance, coherence, safety)",
            constraints=description if description else "No specific constraints.",
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=4096,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        artifact_key = f"eval_strategy:{result.get('strategy_name', title)}"
        self.state.artifacts[artifact_key] = llm_response

        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        await self.send_message(
            to_team="research",
            message_type=MessageType.COMPLETION,
            subject=f"Eval strategy designed: {title}",
            payload={
                "story_id": story_id,
                "strategy_name": result.get("strategy_name", title),
                "artifact_key": artifact_key,
                "metrics": result.get("metrics", []),
                "estimated_cost": result.get("estimated_cost_per_eval", ""),
            },
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_research_fine_tuning(self, task: dict[str, Any]) -> dict[str, Any]:
        """Research fine-tuning approaches for custom evaluation models."""
        story_id = task.get("story_id", "")
        title = task.get("title", "")
        description = task.get("description", "")

        logger.info(
            "ml_researcher_researching_fine_tuning",
            story_id=story_id,
            title=title,
        )

        prompt = (
            "Research fine-tuning approaches for building custom evaluation models.\n\n"
            f"## Context\n{title}\n\n"
            f"## Description\n{description}\n\n"
            "Cover the following:\n"
            "1. **Reward modeling**: Training a reward model on human evaluation data "
            "to score chatbot responses. Include data requirements, model selection, "
            "and training methodology.\n"
            "2. **DPO (Direct Preference Optimization)**: Using preference pairs to train "
            "an evaluation model without explicit reward modeling.\n"
            "3. **Classification fine-tuning**: Fine-tuning a classifier for specific "
            "evaluation dimensions (e.g., toxicity, relevance).\n"
            "4. **Data collection strategy**: How to gather high-quality human annotations "
            "for fine-tuning, including annotation guidelines and quality control.\n"
            "5. **Evaluation of the evaluator**: How to validate that the fine-tuned model "
            "correlates well with human judgments.\n\n"
            "Respond with a JSON object containing:\n"
            '- "approaches": [{name, methodology, data_requirements, pros, cons}]\n'
            '- "recommended_approach": which approach to start with and why\n'
            '- "data_collection_plan": description\n'
            '- "validation_methodology": description\n'
            '- "estimated_effort": description\n'
            '- "risks": [description]\n'
        )

        llm_response = await self.call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            json_mode=True,
        )

        result = self._parse_json_response(llm_response)

        artifact_key = f"fine_tuning_research:{title}"
        self.state.artifacts[artifact_key] = llm_response

        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        await self.send_message(
            to_team="research",
            message_type=MessageType.COMPLETION,
            subject=f"Fine-tuning research complete: {title}",
            payload={
                "story_id": story_id,
                "artifact_key": artifact_key,
                "recommended_approach": result.get("recommended_approach", ""),
            },
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "artifact_key": artifact_key,
            "result": result,
        }

    async def _execute_answer_query(self, task: dict[str, Any]) -> dict[str, Any]:
        """Answer an ML methodology question."""
        question = task.get("question", "")
        from_agent = task.get("from_agent", "")
        reply_to = task.get("reply_to", "")

        prompt = (
            "A colleague has asked the following ML/evaluation question. "
            "Provide a clear, actionable answer.\n\n"
            f"## Question\n{question}\n\n"
            "Focus on practical recommendations grounded in current best practices. "
            "Reference specific models, techniques, and tools where appropriate."
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

    async def _execute_review_artifact(self, task: dict[str, Any]) -> dict[str, Any]:
        """Review a judge prompt or pipeline design artifact."""
        artifact = task.get("artifact", "")
        artifact_type = task.get("artifact_type", "judge_prompt")
        from_agent = task.get("from_agent", "")
        reply_to = task.get("reply_to", "")

        prompt = (
            f"Review the following {artifact_type} for quality and correctness.\n\n"
            f"## Artifact\n{artifact}\n\n"
            "Assess:\n"
            "1. Is the design sound and well-motivated?\n"
            "2. Are known biases addressed?\n"
            "3. Is the output format clearly specified?\n"
            "4. Are edge cases considered?\n"
            "5. Is it practically implementable?\n\n"
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
                subject=f"Review: {artifact_type}",
                payload={
                    "artifact_type": artifact_type,
                    "approved": result.get("approved", False),
                    "score": result.get("score", 0),
                    "issues": result.get("issues", []),
                    "summary": result.get("summary", ""),
                    "reply_to": reply_to,
                },
            )

        return {"status": "reviewed", "artifact_type": artifact_type, "result": result}

    # ------------------------------------------------------------------
    # Judge gap analysis
    # ------------------------------------------------------------------

    def _identify_judge_gaps(self) -> dict[str, Any] | None:
        """Check whether any standard evaluation dimensions lack judge prompts.

        Returns a design_judge_prompt task if a gap is found, otherwise None.
        """
        existing_keys = {
            key.split(":", 1)[1]
            for key in self.state.artifacts
            if key.startswith("judge_prompt:")
        }

        for dimension, description in _JUDGE_DIMENSIONS.items():
            if dimension not in existing_keys and not self._has_story_for_dimension(dimension):
                logger.info(
                    "ml_researcher_judge_gap_found",
                    dimension=dimension,
                )
                return {
                    "type": "design_judge_prompt",
                    "title": f"LLM-as-Judge: {dimension.replace('_', ' ').title()}",
                    "description": description,
                }

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_relevant(title: str, description: str, tags: list[str]) -> bool:
        """Determine whether a story/task is relevant to ML research."""
        combined = f"{title} {description}".lower()
        tag_set = {t.lower() for t in tags}

        if tag_set & _ML_RESEARCH_TAGS:
            return True

        keywords = [
            "judge", "llm-as-judge", "llm as judge", "embedding", "similarity",
            "fine-tun", "fine_tun", "pipeline", "eval strategy", "evaluation strategy",
            "reward model", "dpo", "preference", "scoring rubric", "aggregat",
            "cascade", "multi-stage",
        ]
        return any(kw in combined for kw in keywords)

    @staticmethod
    def _is_ml_research_story(story: Story) -> bool:
        """Check whether a story is about ML research topics."""
        return MLResearcher._is_relevant(
            story.title, story.description, story.tags
        ) and story.task_type in (TaskType.STORY, TaskType.RESEARCH, TaskType.SPIKE)

    @staticmethod
    def _classify_story(story: Story) -> str:
        """Classify a story into a specific ML research task type."""
        return MLResearcher._classify_from_text(story.title, story.description)

    @staticmethod
    def _classify_from_text(title: str, description: str) -> str:
        """Classify text into a specific ML research task type."""
        combined = f"{title} {description}".lower()
        if any(kw in combined for kw in ["judge", "rubric", "scoring prompt"]):
            return "design_judge_prompt"
        if any(kw in combined for kw in ["pipeline", "multi-stage", "cascade"]):
            return "design_eval_pipeline"
        if any(kw in combined for kw in ["embedding", "similarity", "vector"]):
            return "research_embeddings"
        if any(kw in combined for kw in ["fine-tun", "fine_tun", "reward model", "dpo"]):
            return "research_fine_tuning"
        if any(kw in combined for kw in ["strategy", "evaluation plan"]):
            return "design_eval_strategy"
        return "design_eval_strategy"

    @staticmethod
    def _infer_judge_dimension(title: str, description: str) -> str:
        """Infer the evaluation dimension from title and description."""
        combined = f"{title} {description}".lower()
        for dimension in _JUDGE_DIMENSIONS:
            if dimension.replace("_", " ") in combined or dimension in combined:
                return dimension
        return "helpfulness"

    @staticmethod
    def _infer_domain(description: str) -> str:
        """Infer the chatbot domain from a description."""
        desc_lower = description.lower()
        domain_keywords: dict[str, list[str]] = {
            "customer_support": ["customer", "support", "helpdesk", "ticket"],
            "healthcare": ["health", "medical", "clinical", "patient"],
            "education": ["education", "learning", "tutoring", "student"],
            "e_commerce": ["commerce", "shopping", "product", "retail"],
            "finance": ["finance", "banking", "trading", "investment"],
            "legal": ["legal", "law", "compliance", "contract"],
        }
        for domain, keywords in domain_keywords.items():
            if any(kw in desc_lower for kw in keywords):
                return domain
        return "general_purpose"

    def _has_story_for_dimension(self, dimension: str) -> bool:
        """Check whether there is already a story covering this judge dimension."""
        dim_lower = dimension.lower().replace("_", " ")
        for story in self.state.stories.values():
            combined = f"{story.title} {story.description}".lower()
            if dim_lower in combined and "judge" in combined and story.status != StoryStatus.DONE:
                return True
        return False

    @staticmethod
    def _parse_json_response(raw: str) -> dict[str, Any]:
        """Safely parse a JSON response from the LLM."""
        json_match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
        text = json_match.group(1).strip() if json_match else raw.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "ml_researcher_json_parse_failed",
                raw_length=len(raw),
            )
            return {"raw_response": raw}
