"""Frontend engineer agent for the multi-agent development team.

Specializes in React/Next.js components, TailwindCSS styling,
TypeScript interfaces, and dashboard UI for the eval platform.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.engineering.code_generator import CodeBlock, CodeGenerator, Language
from agents.engineering.prompts import FRONTEND_SYSTEM_PROMPT
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import ProjectState, StoryStatus, TaskType

logger = structlog.get_logger()


class FrontendAgent(BaseAgent):
    """Frontend engineer agent.

    Handles:
    - React/Next.js component generation
    - TypeScript interface and type definitions
    - TailwindCSS-styled UI components
    - Dashboard page layouts and data visualizations
    - API client hooks (React Query)
    - Accessibility and responsive design
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
    ) -> None:
        if not config.system_prompt:
            config = config.model_copy(update={"system_prompt": FRONTEND_SYSTEM_PROMPT})
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
            "- Build React/Next.js components for the eval dashboard\n"
            "- Create TypeScript interfaces and types\n"
            "- Implement TailwindCSS-styled, accessible UI\n"
            "- Build data visualization components with Recharts\n"
            "- Create API client hooks with React Query\n"
            "- Ensure responsive design and proper loading/error states"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Process an incoming message and return response messages."""
        responses: list[Message] = []

        logger.info(
            "frontend_processing_message",
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
        """Plan the next unit of work from assigned stories and bugs."""
        tasks: list[dict[str, Any]] = []

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
                "frontend_planned_work",
                agent_id=self.agent_id,
                task_count=len(tasks),
            )

        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a planned task and return the result."""
        task_type = task.get("type", "")

        logger.info(
            "frontend_executing_task",
            agent_id=self.agent_id,
            task_type=task_type,
            title=task.get("title", ""),
        )

        try:
            if task_type == "implement_story":
                return await self._implement_story(task)
            elif task_type == "fix_bug":
                return await self._fix_bug(task)
            elif task_type == "generate_component":
                return await self._generate_component(task)
            elif task_type == "generate_page":
                return await self._generate_page(task)
            elif task_type == "generate_hook":
                return await self._generate_hook(task)
            else:
                logger.warning("frontend_unknown_task_type", task_type=task_type)
                return {"status": "error", "reason": f"Unknown task type: {task_type}"}
        except Exception as e:
            logger.error(
                "frontend_task_failed",
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
        """Handle an ad-hoc task request."""
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
        """Acknowledge and begin investigating a frontend bug."""
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
        language_str = message.payload.get("language", "typescript")
        context = message.payload.get("context", "")

        try:
            language = Language(language_str)
        except ValueError:
            language = Language.TYPESCRIPT

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
        """Answer a technical question using the LLM."""
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
        """Implement a full frontend story: plan, generate components, store artifacts."""
        story_id = task["story_id"]
        description = task["description"]

        # Plan the implementation
        plan_response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Break down this frontend story into implementation steps.\n\n"
                        f"Story: {task['title']}\n"
                        f"Description: {description}\n\n"
                        "Return a JSON object with:\n"
                        '  "steps": [list of step descriptions],\n'
                        '  "components": [list of React components to create],\n'
                        '  "pages": [list of Next.js pages if applicable],\n'
                        '  "hooks": [list of custom hooks if applicable],\n'
                        '  "types": [list of TypeScript interfaces]'
                    ),
                }
            ],
            json_mode=True,
            temperature=0.3,
        )

        try:
            plan = json.loads(plan_response)
        except json.JSONDecodeError:
            plan = {"steps": [description], "components": [], "pages": [], "hooks": [], "types": []}

        artifacts: dict[str, str] = {}

        # Generate components
        for component_name in plan.get("components", []):
            block = await self.code_gen.generate_typescript(
                task_description=f"Create React component '{component_name}' for: {task['title']}",
                requirements=description,
                filename=f"components/{component_name}.tsx",
                extra_context=f"Implementation plan:\n{json.dumps(plan, indent=2)}",
            )
            artifact_key = f"{story_id}/components/{component_name}.tsx"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Generate pages
        for page_name in plan.get("pages", []):
            block = await self.code_gen.generate_typescript(
                task_description=f"Create Next.js page '{page_name}' for: {task['title']}",
                requirements=description,
                filename=f"app/{page_name}/page.tsx",
                extra_context=f"Implementation plan:\n{json.dumps(plan, indent=2)}",
            )
            artifact_key = f"{story_id}/pages/{page_name}.tsx"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Generate custom hooks
        for hook_name in plan.get("hooks", []):
            block = await self.code_gen.generate_typescript(
                task_description=f"Create custom React hook '{hook_name}' for: {task['title']}",
                requirements=description,
                filename=f"hooks/{hook_name}.ts",
                extra_context=f"Implementation plan:\n{json.dumps(plan, indent=2)}",
            )
            artifact_key = f"{story_id}/hooks/{hook_name}.ts"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Move story to review
        if story_id in self.state.stories:
            self.state.move_story(story_id, StoryStatus.IN_REVIEW)

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
        """Generate a fix for a frontend bug."""
        bug_id = task["bug_id"]

        fix_response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Diagnose and propose a fix for this frontend bug.\n\n"
                        f"Bug: {task['title']}\n"
                        f"Description: {task['description']}\n\n"
                        "Return a JSON object with:\n"
                        '  "diagnosis": "root cause analysis",\n'
                        '  "fix_description": "what needs to change",\n'
                        '  "files_to_modify": ["list of files"],\n'
                        '  "component_affected": "name of the affected component"'
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
                "component_affected": "unknown",
            }

        fix_block = await self.code_gen.generate_typescript(
            task_description=f"Fix frontend bug: {task['title']}",
            requirements=diagnosis.get("fix_description", task["description"]),
            filename=f"fix_{bug_id.lower().replace('-', '_')}.tsx",
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

    async def _generate_component(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a single React component."""
        component_name = task.get("component_name", "Component")
        description = task.get("description", f"React component: {component_name}")
        props = task.get("props", [])

        props_str = "\n".join(f"- {p}" for p in props) if props else "Determine appropriate props."

        block = await self.code_gen.generate_typescript(
            task_description=f"Create React component '{component_name}'",
            requirements=f"{description}\n\nProps:\n{props_str}",
            filename=f"components/{component_name}.tsx",
            extra_context=(
                "Include:\n"
                "- TypeScript interface for props\n"
                "- TailwindCSS styling\n"
                "- Proper loading/error/empty states\n"
                "- Accessibility attributes\n"
                "- Export as default and named export"
            ),
        )

        artifact_key = f"components/{component_name}.tsx"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_page(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a Next.js page."""
        page_name = task.get("page_name", "page")
        description = task.get("description", f"Next.js page: {page_name}")

        block = await self.code_gen.generate_typescript(
            task_description=f"Create Next.js App Router page '{page_name}'",
            requirements=description,
            filename=f"app/{page_name}/page.tsx",
            extra_context=(
                "Include:\n"
                "- Server or client component annotation as appropriate\n"
                "- Metadata export for SEO\n"
                "- Suspense boundaries for data loading\n"
                "- Responsive layout with TailwindCSS"
            ),
        )

        artifact_key = f"pages/{page_name}/page.tsx"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_hook(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a custom React hook."""
        hook_name = task.get("hook_name", "useResource")
        description = task.get("description", f"Custom hook: {hook_name}")
        endpoint = task.get("endpoint", "")

        extra = "Include:\n- Proper TypeScript return type\n- Error handling\n"
        if endpoint:
            extra += f"- Fetches from API endpoint: {endpoint}\n- Uses React Query\n"

        block = await self.code_gen.generate_typescript(
            task_description=f"Create custom React hook '{hook_name}'",
            requirements=description,
            filename=f"hooks/{hook_name}.ts",
            extra_context=extra,
        )

        artifact_key = f"hooks/{hook_name}.ts"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }
