"""Backend engineer agent for the multi-agent development team.

Specializes in API endpoints, eval pipeline logic, database models,
Pydantic schemas, and chatbot provider connectors. Uses LLM-driven
code generation to produce FastAPI routes, SQLAlchemy models, and
integration code.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.engineering.code_generator import CodeBlock, CodeGenerator, Language
from agents.engineering.prompts import BACKEND_SYSTEM_PROMPT
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import ProjectState, StoryStatus, TaskType

logger = structlog.get_logger()


class BackendAgent(BaseAgent):
    """Backend engineer agent.

    Handles:
    - FastAPI route generation for the eval platform API
    - SQLAlchemy model and migration scaffolding
    - Pydantic request/response schema creation
    - Evaluation pipeline orchestration logic
    - Chatbot provider connector implementations
    - Architecture decision proposals
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
    ) -> None:
        # Inject the backend system prompt if none was provided
        if not config.system_prompt:
            config = config.model_copy(update={"system_prompt": BACKEND_SYSTEM_PROMPT})
        super().__init__(config, message_bus, project_state)
        self.code_gen = CodeGenerator(
            model=config.model,
            temperature=0.4,
            max_tokens=config.max_tokens,
        )

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Design and implement FastAPI REST endpoints\n"
            "- Create SQLAlchemy ORM models and Pydantic schemas\n"
            "- Build evaluation pipeline orchestration logic\n"
            "- Implement chatbot provider connectors (OpenAI, Anthropic, etc.)\n"
            "- Propose and document architecture decisions\n"
            "- Write unit tests for backend services"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Process an incoming message and return response messages.

        Handles story assignments, task requests, bug reports, review
        requests, and queries from other agents.
        """
        responses: list[Message] = []

        logger.info(
            "backend_processing_message",
            agent_id=self.agent_id,
            message_type=message.message_type.value,
            subject=message.subject,
        )

        if message.message_type == MessageType.STORY:
            responses.extend(await self._handle_story(message))

        elif message.message_type == MessageType.TASK:
            responses.extend(await self._handle_task(message))

        elif message.message_type == MessageType.BUG_REPORT:
            responses.extend(await self._handle_bug(message))

        elif message.message_type == MessageType.REVIEW_REQUEST:
            responses.extend(await self._handle_review_request(message))

        elif message.message_type == MessageType.QUERY:
            responses.extend(await self._handle_query(message))

        return responses

    async def plan_work(self) -> list[dict[str, Any]]:
        """Plan the next unit of work by examining assigned stories and bugs.

        Returns a list of task dicts for ``execute_task`` to process.
        """
        tasks: list[dict[str, Any]] = []

        # Find stories assigned to this agent that are ready or in progress
        for story in self.state.stories.values():
            if (
                story.assigned_to == self.agent_id
                and story.status in (StoryStatus.READY, StoryStatus.IN_PROGRESS)
            ):
                tasks.append(
                    {
                        "type": "implement_story",
                        "story_id": story.id,
                        "title": story.title,
                        "description": story.description,
                        "task_type": story.task_type.value,
                    }
                )

        # Find bugs assigned to this agent
        for bug in self.state.bugs.values():
            if (
                bug.assigned_to == self.agent_id
                and bug.status not in (StoryStatus.DONE, StoryStatus.IN_REVIEW)
            ):
                tasks.append(
                    {
                        "type": "fix_bug",
                        "bug_id": bug.id,
                        "title": bug.title,
                        "description": bug.description,
                    }
                )

        if tasks:
            logger.info(
                "backend_planned_work",
                agent_id=self.agent_id,
                task_count=len(tasks),
            )

        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a planned task and return the result.

        Dispatches to the appropriate implementation method based on
        the task type.
        """
        task_type = task.get("type", "")

        logger.info(
            "backend_executing_task",
            agent_id=self.agent_id,
            task_type=task_type,
            title=task.get("title", ""),
        )

        try:
            if task_type == "implement_story":
                return await self._implement_story(task)
            elif task_type == "fix_bug":
                return await self._fix_bug(task)
            elif task_type == "generate_endpoint":
                return await self._generate_endpoint(task)
            elif task_type == "generate_model":
                return await self._generate_model(task)
            elif task_type == "propose_architecture":
                return await self._propose_architecture(task)
            else:
                logger.warning("backend_unknown_task_type", task_type=task_type)
                return {"status": "error", "reason": f"Unknown task type: {task_type}"}
        except Exception as e:
            logger.error(
                "backend_task_failed",
                agent_id=self.agent_id,
                task_type=task_type,
                error=str(e),
            )
            return {"status": "error", "reason": str(e)}

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_story(self, message: Message) -> list[Message]:
        """Accept a story assignment and acknowledge."""
        story_id = message.payload.get("story_id", "")
        if story_id and story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_PROGRESS)
            self.state.assign_story(story_id, self.agent_id, "engineering")

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.STATUS_UPDATE,
                subject=f"Accepted story: {message.subject}",
                payload={"story_id": story_id, "status": "in_progress"},
                reply_to=message.id,
            )
        ]

    async def _handle_task(self, message: Message) -> list[Message]:
        """Handle an ad-hoc task request from another agent."""
        result = await self.execute_task(message.payload)
        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.COMPLETION,
                subject=f"Completed: {message.subject}",
                payload=result,
                reply_to=message.id,
            )
        ]

    async def _handle_bug(self, message: Message) -> list[Message]:
        """Acknowledge a bug report and begin investigation."""
        bug_id = message.payload.get("bug_id", "")
        if bug_id and bug_id in self.state.bugs:
            self.state.bugs[bug_id].assigned_to = self.agent_id
            self.state.bugs[bug_id].status = StoryStatus.IN_PROGRESS

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.STATUS_UPDATE,
                subject=f"Investigating bug: {message.subject}",
                payload={"bug_id": bug_id, "status": "investigating"},
                reply_to=message.id,
            )
        ]

    async def _handle_review_request(self, message: Message) -> list[Message]:
        """Review code submitted by another agent."""
        code = message.payload.get("code", "")
        language_str = message.payload.get("language", "python")
        context = message.payload.get("context", "")

        try:
            language = Language(language_str)
        except ValueError:
            language = Language.PYTHON

        review = await self.code_gen.review_code(code, language, context)

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.REVIEW_RESULT,
                subject=f"Review: {message.subject}",
                payload={
                    "approved": review.approved,
                    "score": review.score,
                    "issues": review.issues,
                    "summary": review.summary,
                },
                reply_to=message.id,
            )
        ]

    async def _handle_query(self, message: Message) -> list[Message]:
        """Answer a technical question from another agent using the LLM."""
        question = message.payload.get("question", message.subject)
        answer = await self.call_llm(
            [{"role": "user", "content": question}],
            temperature=0.3,
        )

        return [
            Message(
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                message_type=MessageType.RESPONSE,
                subject=f"Re: {message.subject}",
                payload={"answer": answer},
                reply_to=message.id,
            )
        ]

    # ------------------------------------------------------------------
    # Task execution helpers
    # ------------------------------------------------------------------

    async def _implement_story(self, task: dict[str, Any]) -> dict[str, Any]:
        """Implement a full story: plan via LLM, generate code, store artifacts."""
        story_id = task["story_id"]
        description = task["description"]
        task_type = task.get("task_type", TaskType.STORY.value)

        # Ask LLM to break the story into implementation steps
        plan_response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Break down this backend story into implementation steps.\n\n"
                        f"Story: {task['title']}\n"
                        f"Description: {description}\n"
                        f"Type: {task_type}\n\n"
                        "Return a JSON object with:\n"
                        '  "steps": [list of step descriptions],\n'
                        '  "files_needed": [list of filenames to create/modify],\n'
                        '  "endpoints": [list of API endpoints if applicable],\n'
                        '  "models": [list of data models if applicable]'
                    ),
                }
            ],
            json_mode=True,
            temperature=0.3,
        )

        try:
            plan = json.loads(plan_response)
        except json.JSONDecodeError:
            plan = {"steps": [description], "files_needed": [], "endpoints": [], "models": []}

        # Generate code for each file identified in the plan
        artifacts: dict[str, str] = {}

        for filename in plan.get("files_needed", []):
            block = await self.code_gen.generate_python(
                task_description=f"Implement {filename} for story: {task['title']}",
                requirements=description,
                filename=filename,
                extra_context=f"Implementation plan:\n{json.dumps(plan, indent=2)}",
            )
            artifact_key = f"{story_id}/{filename}"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Move story to in-review
        if story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

        # Notify the team
        await self.send_message(
            to_team="engineering",
            message_type=MessageType.REVIEW_REQUEST,
            subject=f"Review: {task['title']}",
            payload={
                "story_id": story_id,
                "artifacts": list(artifacts.keys()),
                "plan": plan,
            },
        )

        return {
            "status": "completed",
            "story_id": story_id,
            "artifacts": list(artifacts.keys()),
            "plan": plan,
        }

    async def _fix_bug(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a fix for a reported bug."""
        bug_id = task["bug_id"]

        # Ask LLM for a diagnosis and fix
        fix_response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Diagnose and propose a fix for this bug.\n\n"
                        f"Bug: {task['title']}\n"
                        f"Description: {task['description']}\n\n"
                        "Return a JSON object with:\n"
                        '  "diagnosis": "root cause analysis",\n'
                        '  "fix_description": "what needs to change",\n'
                        '  "files_to_modify": ["list of files"]'
                    ),
                }
            ],
            json_mode=True,
            temperature=0.3,
        )

        try:
            diagnosis = json.loads(fix_response)
        except json.JSONDecodeError:
            diagnosis = {
                "diagnosis": "Unable to parse diagnosis",
                "fix_description": task["description"],
                "files_to_modify": [],
            }

        # Generate fix code
        fix_block = await self.code_gen.generate_python(
            task_description=f"Fix bug: {task['title']}",
            requirements=diagnosis.get("fix_description", task["description"]),
            filename=f"fix_{bug_id.lower().replace('-', '_')}.py",
        )

        artifact_key = f"{bug_id}/fix"
        self.state.artifacts[artifact_key] = fix_block.code

        if bug_id in self.state.bugs:
            self.state.bugs[bug_id].status = StoryStatus.IN_REVIEW

        return {
            "status": "fix_proposed",
            "bug_id": bug_id,
            "diagnosis": diagnosis,
            "artifact_key": artifact_key,
            "valid": fix_block.is_valid,
        }

    async def _generate_endpoint(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a single FastAPI endpoint."""
        endpoint = task.get("endpoint", "/api/v1/resource")
        method = task.get("method", "GET")
        description = task.get("description", f"{method} {endpoint}")

        block = await self.code_gen.generate_python(
            task_description=f"Create a FastAPI {method} endpoint at {endpoint}",
            requirements=description,
            filename=task.get("filename"),
            extra_context=(
                "Include:\n"
                "- Pydantic request/response models\n"
                "- Proper HTTP status codes\n"
                "- Dependency injection for DB session\n"
                "- Error handling with HTTPException"
            ),
        )

        artifact_key = f"endpoints/{endpoint.strip('/').replace('/', '_')}_{method.lower()}.py"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_model(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a SQLAlchemy model and its Pydantic schema."""
        model_name = task.get("model_name", "Resource")
        fields = task.get("fields", [])
        description = task.get("description", f"SQLAlchemy model for {model_name}")

        fields_str = "\n".join(f"- {f}" for f in fields) if fields else "Determine appropriate fields."

        block = await self.code_gen.generate_python(
            task_description=f"Create SQLAlchemy model '{model_name}' with Pydantic schemas",
            requirements=f"{description}\n\nFields:\n{fields_str}",
            filename=f"models/{model_name.lower()}.py",
            extra_context=(
                "Include:\n"
                "- SQLAlchemy 2.0 declarative model with Mapped[] annotations\n"
                "- Pydantic Create, Update, and Read schemas\n"
                "- Proper relationships and foreign keys if applicable\n"
                "- Timestamps (created_at, updated_at)"
            ),
        )

        artifact_key = f"models/{model_name.lower()}.py"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _propose_architecture(self, task: dict[str, Any]) -> dict[str, Any]:
        """Propose an architecture decision via LLM analysis."""
        topic = task.get("topic", "system architecture")
        constraints = task.get("constraints", "")

        response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Propose an architecture decision for: {topic}\n\n"
                        f"Constraints: {constraints}\n\n"
                        "Return a JSON object with:\n"
                        '  "title": "decision title",\n'
                        '  "context": "why this decision is needed",\n'
                        '  "options": [{"name": "...", "pros": [...], "cons": [...]}],\n'
                        '  "recommendation": "which option and why",\n'
                        '  "consequences": ["list of consequences"]'
                    ),
                }
            ],
            json_mode=True,
            temperature=0.5,
        )

        try:
            decision = json.loads(response)
        except json.JSONDecodeError:
            decision = {"title": topic, "recommendation": response}

        artifact_key = f"architecture/{topic.lower().replace(' ', '_')}.json"
        self.state.artifacts[artifact_key] = json.dumps(decision, indent=2)

        # Broadcast the proposal for discussion
        await self.broadcast(
            message_type=MessageType.STATUS_UPDATE,
            subject=f"Architecture proposal: {decision.get('title', topic)}",
            payload={"decision": decision, "artifact_key": artifact_key},
        )

        return {
            "status": "proposed",
            "artifact_key": artifact_key,
            "decision": decision,
        }
