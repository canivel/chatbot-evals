"""Data engineer agent for the multi-agent development team.

Specializes in data pipelines, ETL processes, database schema design,
Alembic migrations, and conversation data ingestion/preprocessing.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.base_agent import AgentConfig, BaseAgent
from agents.engineering.code_generator import CodeBlock, CodeGenerator, Language
from agents.engineering.prompts import DATA_ENGINEERING_PROMPT
from agents.message_bus import Message, MessageBus, MessageType
from agents.state import ProjectState, StoryStatus, TaskType

logger = structlog.get_logger()


class DataAgent(BaseAgent):
    """Data engineer agent.

    Handles:
    - Database schema design and evolution
    - Alembic migration generation
    - ETL pipeline implementation for conversation ingestion
    - Data validation and quality checks
    - Batch processing for evaluation pipelines
    - Query optimization and indexing strategies
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: MessageBus,
        project_state: ProjectState,
    ) -> None:
        if not config.system_prompt:
            config = config.model_copy(update={"system_prompt": DATA_ENGINEERING_PROMPT})
        super().__init__(config, message_bus, project_state)
        self.code_gen = CodeGenerator(
            model=config.model,
            temperature=0.3,
            max_tokens=config.max_tokens,
        )

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def _get_responsibilities(self) -> str:
        return (
            "- Design and maintain database schemas (PostgreSQL)\n"
            "- Generate Alembic migration scripts\n"
            "- Build ETL pipelines for conversation data ingestion\n"
            "- Implement data validation and quality checks\n"
            "- Optimize queries and indexing strategies\n"
            "- Design batch processing for evaluation workloads"
        )

    async def process_message(self, message: Message) -> list[Message]:
        """Process an incoming message and return response messages."""
        responses: list[Message] = []

        logger.info(
            "data_processing_message",
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
                "data_planned_work",
                agent_id=self.agent_id,
                task_count=len(tasks),
            )

        return tasks

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a planned task and return the result."""
        task_type = task.get("type", "")

        logger.info(
            "data_executing_task",
            agent_id=self.agent_id,
            task_type=task_type,
            title=task.get("title", ""),
        )

        try:
            if task_type == "implement_story":
                return await self._implement_story(task)
            elif task_type == "fix_bug":
                return await self._fix_bug(task)
            elif task_type == "generate_schema":
                return await self._generate_schema(task)
            elif task_type == "generate_migration":
                return await self._generate_migration(task)
            elif task_type == "generate_pipeline":
                return await self._generate_pipeline(task)
            elif task_type == "generate_validation":
                return await self._generate_validation(task)
            else:
                logger.warning("data_unknown_task_type", task_type=task_type)
                return {"status": "error", "reason": f"Unknown task type: {task_type}"}
        except Exception as e:
            logger.error(
                "data_task_failed",
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
        """Acknowledge and begin investigating a data-related bug."""
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
        """Implement a data engineering story end-to-end."""
        story_id = task["story_id"]
        description = task["description"]

        plan_response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Break down this data engineering story into implementation steps.\n\n"
                        f"Story: {task['title']}\n"
                        f"Description: {description}\n\n"
                        "Return a JSON object with:\n"
                        '  "steps": [list of step descriptions],\n'
                        '  "schemas": [list of database tables/schemas to create],\n'
                        '  "migrations": [list of migration descriptions],\n'
                        '  "pipelines": [list of ETL pipelines to build],\n'
                        '  "validations": [list of data validation rules]'
                    ),
                }
            ],
            json_mode=True,
            temperature=0.3,
        )

        try:
            plan = json.loads(plan_response)
        except json.JSONDecodeError:
            plan = {
                "steps": [description],
                "schemas": [],
                "migrations": [],
                "pipelines": [],
                "validations": [],
            }

        artifacts: dict[str, str] = {}

        # Generate schemas
        for schema_name in plan.get("schemas", []):
            block = await self.code_gen.generate_python(
                task_description=f"Create SQLAlchemy schema for '{schema_name}'",
                requirements=description,
                filename=f"models/{schema_name}.py",
                extra_context=f"Implementation plan:\n{json.dumps(plan, indent=2)}",
            )
            artifact_key = f"{story_id}/schemas/{schema_name}.py"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Generate migrations
        for migration_desc in plan.get("migrations", []):
            block = await self.code_gen.generate_python(
                task_description=f"Create Alembic migration: {migration_desc}",
                requirements=migration_desc,
                filename="migration.py",
                extra_context=(
                    "Use Alembic migration template with:\n"
                    "- revision ID placeholder\n"
                    "- upgrade() and downgrade() functions\n"
                    "- op.create_table / op.add_column / etc."
                ),
            )
            safe_name = migration_desc[:40].lower().replace(" ", "_").replace("/", "_")
            artifact_key = f"{story_id}/migrations/{safe_name}.py"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

        # Generate pipelines
        for pipeline_name in plan.get("pipelines", []):
            block = await self.code_gen.generate_python(
                task_description=f"Create ETL pipeline: {pipeline_name}",
                requirements=description,
                filename=f"pipelines/{pipeline_name}.py",
                extra_context=(
                    "Include:\n"
                    "- Extract, transform, load functions\n"
                    "- Batch processing support\n"
                    "- Error handling and retry logic\n"
                    "- Structured logging for observability"
                ),
            )
            safe_name = pipeline_name[:40].lower().replace(" ", "_").replace("/", "_")
            artifact_key = f"{story_id}/pipelines/{safe_name}.py"
            artifacts[artifact_key] = block.code
            self.state.artifacts[artifact_key] = block.code

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
        """Generate a fix for a data-related bug."""
        bug_id = task["bug_id"]

        fix_response = await self.call_llm(
            [
                {
                    "role": "user",
                    "content": (
                        f"Diagnose and propose a fix for this data engineering bug.\n\n"
                        f"Bug: {task['title']}\n"
                        f"Description: {task['description']}\n\n"
                        "Return a JSON object with:\n"
                        '  "diagnosis": "root cause analysis",\n'
                        '  "fix_description": "what needs to change",\n'
                        '  "data_impact": "potential impact on existing data",\n'
                        '  "requires_migration": true/false'
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
                "data_impact": "unknown",
                "requires_migration": False,
            }

        fix_block = await self.code_gen.generate_python(
            task_description=f"Fix data bug: {task['title']}",
            requirements=diagnosis.get("fix_description", task["description"]),
            filename=f"fix_{bug_id.lower().replace('-', '_')}.py",
        )

        artifact_key = f"{bug_id}/fix"
        self.state.artifacts[artifact_key] = fix_block.code

        # If a migration is needed, generate it as well
        if diagnosis.get("requires_migration"):
            migration_block = await self.code_gen.generate_python(
                task_description=f"Migration for bug fix: {task['title']}",
                requirements=diagnosis.get("fix_description", ""),
                filename=f"migrations/fix_{bug_id.lower().replace('-', '_')}.py",
                extra_context="Generate an Alembic migration with upgrade() and downgrade().",
            )
            migration_key = f"{bug_id}/migration"
            self.state.artifacts[migration_key] = migration_block.code

        if bug_id in self.state.bugs:
            self.state.bugs[bug_id].status = StoryStatus.IN_REVIEW

        return {
            "status": "fix_proposed",
            "bug_id": bug_id,
            "diagnosis": diagnosis,
            "artifact_key": artifact_key,
            "valid": fix_block.is_valid,
        }

    async def _generate_schema(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a database schema with SQLAlchemy models."""
        table_name = task.get("table_name", "resource")
        columns = task.get("columns", [])
        relationships = task.get("relationships", [])
        description = task.get("description", f"Database schema for {table_name}")

        columns_str = "\n".join(f"- {c}" for c in columns) if columns else "Determine appropriate columns."
        rels_str = "\n".join(f"- {r}" for r in relationships) if relationships else "No explicit relationships."

        block = await self.code_gen.generate_python(
            task_description=f"Create SQLAlchemy 2.0 model for table '{table_name}'",
            requirements=f"{description}\n\nColumns:\n{columns_str}\n\nRelationships:\n{rels_str}",
            filename=f"models/{table_name}.py",
            extra_context=(
                "Include:\n"
                "- SQLAlchemy 2.0 declarative model with Mapped[] type annotations\n"
                "- Proper column types, constraints, and indexes\n"
                "- created_at and updated_at timestamps\n"
                "- __repr__ and __tablename__\n"
                "- Pydantic schemas for CRUD operations"
            ),
        )

        artifact_key = f"schemas/{table_name}.py"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_migration(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate an Alembic migration script."""
        migration_name = task.get("migration_name", "update_schema")
        description = task.get("description", f"Migration: {migration_name}")
        operations = task.get("operations", [])

        ops_str = "\n".join(f"- {op}" for op in operations) if operations else description

        block = await self.code_gen.generate_python(
            task_description=f"Create Alembic migration: {migration_name}",
            requirements=f"Operations:\n{ops_str}",
            filename=f"migrations/versions/{migration_name}.py",
            extra_context=(
                "Follow Alembic migration template:\n"
                "- Include revision and down_revision variables\n"
                "- Implement upgrade() with the schema changes\n"
                "- Implement downgrade() to reverse changes\n"
                "- Use op.create_table, op.add_column, op.create_index, etc."
            ),
        )

        artifact_key = f"migrations/{migration_name}.py"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_pipeline(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate an ETL data pipeline."""
        pipeline_name = task.get("pipeline_name", "data_pipeline")
        source = task.get("source", "")
        destination = task.get("destination", "")
        description = task.get("description", f"ETL pipeline: {pipeline_name}")
        transformations = task.get("transformations", [])

        transforms_str = (
            "\n".join(f"- {t}" for t in transformations)
            if transformations
            else "Determine appropriate transformations."
        )

        block = await self.code_gen.generate_python(
            task_description=f"Create ETL pipeline '{pipeline_name}'",
            requirements=(
                f"{description}\n"
                f"Source: {source or 'configurable'}\n"
                f"Destination: {destination or 'PostgreSQL'}\n"
                f"Transformations:\n{transforms_str}"
            ),
            filename=f"pipelines/{pipeline_name}.py",
            extra_context=(
                "Include:\n"
                "- Async extract(), transform(), load() functions\n"
                "- A run_pipeline() orchestrator function\n"
                "- Batch processing with configurable batch size\n"
                "- Error handling with dead-letter queue pattern\n"
                "- Structured logging at each stage\n"
                "- Data validation before loading"
            ),
        )

        artifact_key = f"pipelines/{pipeline_name}.py"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }

    async def _generate_validation(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate data validation rules and checks."""
        dataset_name = task.get("dataset_name", "dataset")
        description = task.get("description", f"Data validation for {dataset_name}")
        rules = task.get("rules", [])

        rules_str = "\n".join(f"- {r}" for r in rules) if rules else "Determine appropriate validation rules."

        block = await self.code_gen.generate_python(
            task_description=f"Create data validation for '{dataset_name}'",
            requirements=f"{description}\n\nRules:\n{rules_str}",
            filename=f"validations/{dataset_name}_validator.py",
            extra_context=(
                "Include:\n"
                "- Pydantic models for row-level validation\n"
                "- Aggregate validation checks (nulls, ranges, uniqueness)\n"
                "- A ValidationReport dataclass with pass/fail counts\n"
                "- Async validate_batch() function\n"
                "- Structured logging for validation failures"
            ),
        )

        artifact_key = f"validations/{dataset_name}_validator.py"
        self.state.artifacts[artifact_key] = block.code

        return {
            "status": "generated",
            "artifact_key": artifact_key,
            "valid": block.is_valid,
            "errors": block.errors,
        }
